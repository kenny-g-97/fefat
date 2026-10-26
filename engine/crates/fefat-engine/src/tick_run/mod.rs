//! The event loop over the tick level of a [`MarketDataReader`] for one instrument (step 2.6), as
//! `fefat.reference.engine.ReferenceEngine` runs trades and TBBO records. Events come in the
//! order of F-CLK-02: at one instant the records received then, in the order the data holds them
//! (F-CLK-03), and then the decision. A record received while the market is closed is not
//! tradeable (F-SES-02), and the working orders stay (F-SES-01). On a tradeable record, the
//! orders that see their first record activate (F-ACT-01), and a market order or a stop through
//! the market fills on it (F-MKT-01, F-MKT-02, F-STP-05); stops triggered on the record before
//! fill at its quote (F-STP-02); stops trigger (F-STP-01), on trades filling at once (F-STP-03);
//! limits fill (F-LMT-01 to F-LMT-04); and the position is marked (F-MRK-01). Each fill cancels
//! its OCO group (F-OCO-01), places its bracket (F-OCO-02), and is booked in the [`Ledger`].

mod fills;
mod outcomes;
#[cfg(test)]
mod properties;
mod records;
#[cfg(test)]
mod tests;

pub use outcomes::{BookedFill, RunError, RunOutputs, Stepped};
pub use records::{Quote, TickFidelity, TickRecord};

use fefat_core::instants::{TradeDate, Ts};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{MarketDataError, MarketDataReader};
use fefat_core::orders::OrderId;

use records::DayRecords;

use crate::book::{Book, WorkingOrder};
use crate::event_log::LogEntry;
use crate::hours::TradingHours;
use crate::settings::RunSettings;
use crate::strategy::{DecisionContext, Strategy};

/// One run of a strategy over the tick level of one contract's trade dates.
pub struct TickRun<'run, R: MarketDataReader> {
    reader: &'run R,
    level: TickFidelity,
    hours: &'run TradingHours,
    settings: RunSettings,
    strategy: &'run mut dyn Strategy,
    book: Book,
    ledger: Ledger,
    fills: Vec<BookedFill>,
    log: Vec<LogEntry>,
    in_break: bool,
    decisions: Vec<Ts>,
    next_decision: usize,
    next_day: usize,
    day: Option<DayRecords<'run>>,
    next_record: usize,
    last_record: Option<Ts>,
    timeline: usize,
}

impl<'run, R: MarketDataReader> TickRun<'run, R> {
    /// A run of `strategy` over `reader`'s records of `level`, open during `hours`, under
    /// `settings`, from `ledger`: the run's capital, and the position held when the tape starts.
    pub fn new(
        reader: &'run R,
        level: TickFidelity,
        hours: &'run TradingHours,
        settings: RunSettings,
        ledger: Ledger,
        strategy: &'run mut dyn Strategy,
    ) -> Result<Self, RunError> {
        let decisions = strategy.decision_instants();
        let pairs = decisions.iter().zip(decisions.iter().skip(1));
        if let Some((&previous, &next)) =
            pairs.into_iter().find(|(previous, next)| next <= previous)
        {
            return Err(RunError::DecisionsOutOfOrder { previous, next });
        }
        Ok(Self {
            reader,
            level,
            hours,
            settings,
            strategy,
            book: Book::default(),
            ledger,
            fills: Vec::new(),
            log: Vec::new(),
            in_break: false,
            decisions,
            next_decision: 0,
            next_day: 0,
            day: None,
            next_record: 0,
            last_record: None,
            timeline: 0,
        })
    }

    /// Runs to the end of the records and the decisions.
    pub fn run(mut self) -> Result<RunOutputs, RunError> {
        while self.step()?.is_some() {}
        Ok(RunOutputs {
            orders: self.book.into_orders(),
            fills: self.fills,
            log: self.log,
            ledger: self.ledger,
        })
    }

    /// Handles the next event, a record or a decision, and says which; none once both have run
    /// out. At one instant the records come before the decision (F-CLK-02).
    pub fn step(&mut self) -> Result<Option<Stepped>, RunError> {
        let record = self.peek_record()?;
        let decision = self.decisions.get(self.next_decision).copied();
        let index = self.timeline;
        let stepped = match (record, decision) {
            (Some(record), Some(now)) if now < record.ts => self.decide(now, index)?,
            (Some(record), _) => self.receive(record, index)?,
            (None, Some(now)) => self.decide(now, index)?,
            (None, None) => return Ok(None),
        };
        self.timeline += 1;
        Ok(Some(stepped))
    }

    /// The ledger as the run stands.
    pub const fn ledger(&self) -> &Ledger {
        &self.ledger
    }

    /// The fills so far.
    pub fn fills(&self) -> &[BookedFill] {
        &self.fills
    }

    /// The order `id`, live or closed.
    pub fn order(&self, id: OrderId) -> Option<&WorkingOrder> {
        self.book.order(id)
    }

    fn peek_record(&mut self) -> Result<Option<TickRecord>, RunError> {
        loop {
            let next = self.day.as_ref().and_then(|day| day.get(self.next_record));
            if next.is_some() {
                return Ok(next);
            }
            let Some(&trade_date) = self.reader.trade_dates().get(self.next_day) else {
                return Ok(None);
            };
            self.day = Some(self.day_records(trade_date)?);
            self.next_day += 1;
            self.next_record = 0;
        }
    }

    fn day_records(&self, trade_date: TradeDate) -> Result<DayRecords<'run>, MarketDataError> {
        let reader: &'run R = self.reader;
        Ok(match self.level {
            TickFidelity::Tbbo => DayRecords::Tbbo(reader.tbbo(trade_date)?),
            TickFidelity::Trades => DayRecords::Trades(reader.trades(trade_date)?),
        })
    }

    fn decide(&mut self, now: Ts, index: usize) -> Result<Stepped, RunError> {
        self.next_decision += 1;
        let latency = self.settings.latency_nanoseconds();
        let position = self.ledger.position();
        let mut context =
            DecisionContext::new(&mut self.book, &mut self.log, position, now, index, latency);
        self.strategy.on_decision(now, &mut context)?;
        Ok(Stepped::Decision(now))
    }

    fn receive(&mut self, record: TickRecord, index: usize) -> Result<Stepped, RunError> {
        if let Some(previous) = self.last_record.filter(|previous| record.ts < *previous) {
            return Err(RunError::RecordsOutOfOrder {
                previous,
                next: record.ts,
            });
        }
        self.last_record = Some(record.ts);
        self.next_record += 1;
        self.on_record(&record, index)?;
        Ok(Stepped::Record(record))
    }
}
