//! The event loop over one instrument's records (steps 2.6 and 2.7), as
//! `fefat.reference.engine.ReferenceEngine` runs them. Each trade date is filled on the finest
//! level it holds at or coarser than the run's fidelity: trades, TBBO records, or stored bars of a
//! timeframe, 1-second, 1-minute, or an import's coarser bars. Events come in the order of
//! F-CLK-02: at one instant the bars that close then and the records received then, in the order
//! the data holds them (F-CLK-03), and then the decision. A record received, or a bar opening,
//! while the market is closed is not tradeable (F-SES-02), and the working orders stay
//! (F-SES-01). On a tradeable record, the orders that see their first record activate
//! (F-ACT-01), and a market order or a stop through the market fills on it (F-MKT-01, F-MKT-02,
//! F-STP-05); stops triggered on the record before fill at its quote (F-STP-02); stops trigger
//! (F-STP-01), on trades filling at once (F-STP-03); limits fill (F-LMT-01 to F-LMT-04); and the
//! position is marked (F-MRK-01). A bar is replayed as its pseudo-ticks (F-BAR-01 to F-BAR-07,
//! F-ACT-02, F-MKT-03, F-STP-04). Each fill cancels its OCO group (F-OCO-01), places its bracket
//! (F-OCO-02), and is booked in the [`Ledger`]. With [`Replay::Skipping`] the loop passes over
//! blocks of records that no order can act on, by the bars above them (`02` §4).

mod bars;
mod descent;
mod fills;
mod outcomes;
#[cfg(test)]
mod plan_properties;
#[cfg(test)]
mod properties;
mod records;
#[cfg(test)]
mod skip_equals_full;
#[cfg(test)]
mod tests;

pub use descent::Replay;
pub use outcomes::{BookedFill, RunError, RunOutputs, Stepped};
pub use records::{Quote, TickRecord};

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::OrderId;

use descent::BarLevel;
use records::{DayRecords, Unit};

use crate::book::{Book, WorkingOrder};
use crate::event_log::LogEntry;
use crate::hours::TradingHours;
use crate::settings::RunSettings;
use crate::strategy::{DecisionContext, Strategy};

/// One run of a strategy over one contract's trade dates.
pub struct TickRun<'run, R: MarketDataReader> {
    reader: &'run R,
    cap: Fidelity,
    replay: Replay,
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
    day: Option<Day<'run>>,
    fidelity: Fidelity,
    next_record: usize,
    last_record: Option<Ts>,
    timeline: usize,
}

/// The trade date the run reads: its records of the level it fills on and, when it skips, the
/// bar levels above them that nest them, coarsest first.
struct Day<'run> {
    records: DayRecords<'run>,
    levels: Vec<BarLevel<'run>>,
}

impl<'run, R: MarketDataReader> TickRun<'run, R> {
    /// A run of `strategy` over `reader`, filling each trade date on its finest level at or
    /// coarser than `fidelity`, replayed as `replay` says, open during `hours`, under `settings`,
    /// from `ledger`: the run's capital, and the position held when the tape starts.
    pub fn new(
        reader: &'run R,
        fidelity: Fidelity,
        replay: Replay,
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
            cap: fidelity,
            replay,
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
            fidelity,
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

    /// Handles the next event, a record, a bar, a block of records skipped whole, or a decision,
    /// and says which; none once the records and the decisions have run out. At one instant the
    /// records and the bars come before the decision (F-CLK-02).
    pub fn step(&mut self) -> Result<Option<Stepped>, RunError> {
        let unit = self.peek_unit()?;
        let decision = self.decisions.get(self.next_decision).copied();
        let index = self.timeline;
        let stepped = match (unit, decision) {
            (Some(unit), Some(now)) if now < unit.ts() => self.decide(now, index)?,
            (Some(unit), _) => match self.skippable() {
                Some(block) => self.skip(unit, block)?,
                None => self.receive(unit, index)?,
            },
            (None, Some(now)) => self.decide(now, index)?,
            (None, None) => return Ok(None),
        };
        self.timeline += stepped.events();
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

    fn peek_unit(&mut self) -> Result<Option<Unit>, RunError> {
        loop {
            let next = self
                .day
                .as_ref()
                .and_then(|day| day.records.get(self.next_record));
            if next.is_some() {
                return Ok(next);
            }
            let Some(&trade_date) = self.reader.trade_dates().get(self.next_day) else {
                return Ok(None);
            };
            let day = self.day_of(trade_date)?;
            self.fidelity = day.records.fidelity();
            self.day = Some(day);
            self.next_day += 1;
            self.next_record = 0;
        }
    }

    /// The trade date's records of its finest level at or coarser than the run's fidelity and,
    /// when the run skips, the bar levels above them that nest them, coarsest first.
    fn day_of(&self, trade_date: TradeDate) -> Result<Day<'run>, RunError> {
        let reader: &'run R = self.reader;
        let levels = reader.levels(trade_date)?;
        let Some(&finest) = levels.iter().find(|level| **level >= self.cap) else {
            return Err(RunError::NoLevelAtOrCoarser {
                trade_date,
                fidelity: self.cap,
                present: levels.to_vec(),
            });
        };
        let records = match finest {
            Fidelity::Tbbo => DayRecords::Tbbo(reader.tbbo(trade_date)?),
            Fidelity::Trades => DayRecords::Trades(reader.trades(trade_date)?),
            Fidelity::Bars(timeframe) => {
                DayRecords::Bars(reader.bars(trade_date, timeframe)?, timeframe)
            }
        };
        let mut above = Vec::new();
        if self.replay == Replay::Skipping {
            for &level in levels.iter().rev() {
                let Fidelity::Bars(timeframe) = level else {
                    continue;
                };
                if level > finest && finest.nests_in(timeframe) {
                    above.push(BarLevel {
                        bars: reader.bars(trade_date, timeframe)?,
                        offsets: reader.offsets(trade_date, timeframe, finest)?,
                    });
                }
            }
        }
        Ok(Day {
            records,
            levels: above,
        })
    }

    fn decide(&mut self, now: Ts, index: usize) -> Result<Stepped, RunError> {
        self.next_decision += 1;
        let latency = self.settings.latency_nanoseconds();
        let (book, log, ledger) = (&mut self.book, &mut self.log, &self.ledger);
        let mut context = DecisionContext::new(book, log, ledger, now, index, latency);
        self.strategy.on_decision(now, &mut context)?;
        Ok(Stepped::Decision(now))
    }

    fn receive(&mut self, unit: Unit, index: usize) -> Result<Stepped, RunError> {
        self.check_order(unit.ts())?;
        self.last_record = Some(unit.ts());
        self.next_record += 1;
        match unit {
            Unit::Tick(record) => {
                self.on_record(&record, index)?;
                Ok(Stepped::Record(record))
            }
            Unit::Bar(bar) => {
                self.on_bar(&bar, index)?;
                Ok(Stepped::Bar(bar))
            }
        }
    }

    /// Refuses a record available before the one read last, across trade dates; the readers hold
    /// each date's records in order.
    fn check_order(&self, ts: Ts) -> Result<(), RunError> {
        match self.last_record.filter(|previous| ts < *previous) {
            Some(previous) => Err(RunError::RecordsOutOfOrder { previous, next: ts }),
            None => Ok(()),
        }
    }
}
