//! The event loop over one instrument's records (steps 2.6 and 2.7), as
//! `fefat.reference.engine.ReferenceEngine` runs them. Each trade date is filled on the finest
//! level it holds at or coarser than the run's fidelity: trades, TBBO records, or stored bars of a
//! timeframe, 1-second, 1-minute, or an import's coarser bars, and the run counts it in the
//! fidelity era of that level (`02` §1.6). Events come in the order of
//! F-CLK-02: at one instant the bars that close then and the records received then, in the order
//! the data holds them (F-CLK-03), and then the decision. A record received, or a bar opening,
//! while the market is closed is not tradeable (F-SES-02), and the working orders stay
//! (F-SES-01). On a tradeable record, the orders that see their first record activate
//! (F-ACT-01), and a market order or a stop through the market fills on it (F-MKT-01, F-MKT-02,
//! F-STP-05); stops triggered on the record before fill at its quote (F-STP-02); stops trigger
//! (F-STP-01), on trades filling at once (F-STP-03); limits fill (F-LMT-01 to F-LMT-04); and the
//! position is marked (F-MRK-01). A bar is replayed as its pseudo-ticks (F-BAR-01 to F-BAR-07,
//! F-ACT-02, F-MKT-03, F-STP-04). Each fill cancels its OCO group (F-OCO-01), places its bracket
//! (F-OCO-02), and is booked in the [`Ledger`] with its fee (§14). A perpetual's funding times
//! and a future's rolls are session and timer events (F-CLK-02, F-FND-01, §29). With
//! [`Replay::Skipping`] the loop passes over blocks of records that no order can act on, and that
//! add nothing to the open trade's path, by the bars above them (`02` §4). Each trade's path
//! (`paths`, step 2.13) follows the prices marked and the fills, as a pure observer: no fill
//! depends on it.

mod bars;
#[cfg(test)]
mod cost_properties;
mod descent;
mod execution;
mod fills;
#[cfg(test)]
mod limit_properties;
mod outcomes;
#[cfg(test)]
mod path_probe;
mod paths;
#[cfg(test)]
mod paths_tests;
#[cfg(test)]
mod plan_properties;
#[cfg(test)]
mod properties;
mod records;
#[cfg(test)]
mod roll_tests;
mod rolls;
#[cfg(test)]
mod skip_equals_full;
#[cfg(test)]
mod tests;
mod timers;
mod trades;

pub use descent::Replay;
pub use outcomes::{BookedFill, EquityPoint, FidelityEra, RunError, RunOutputs, Stepped};
pub use paths::{PathPoint, PathPointKind, Recording, TradePath};
pub use records::{Quote, TickRecord};
pub use trades::Trade;

use fefat_core::costs::CostLine;
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{BarRow, MarketDataReader};
use fefat_core::orders::OrderId;
use fefat_core::rolls::Roll;
use fefat_core::units::{Money, Price};

use descent::BarLevel;
use records::{DayRecords, Unit};
use rolls::Transfer;
use timers::Timer;
use trades::{Mark, TradeBook};

use crate::book::{Book, WorkingOrder};
use crate::event_log::LogEntry;
use crate::hours::TradingHours;
use crate::rules::Extreme;
use crate::settings::{RollHandling, RunCosts, RunSettings};
use crate::strategy::{ClosedTrade, DecisionContext, Strategy};

/// One run of a strategy over a future's fronts' or another instrument's trade dates.
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
    trade_cash: Money,
    closed_trades: Vec<ClosedTrade>,
    in_break: bool,
    decisions: Vec<Ts>,
    next_decision: usize,
    next_day: usize,
    day: Option<Day<'run>>,
    fidelity: Fidelity,
    trade_date: TradeDate,
    next_record: usize,
    last_record: Option<Ts>,
    timeline: usize,
    costs: RunCosts,
    next_funding: usize,
    cost_lines: Vec<CostLine>,
    warned: bool,
    rolls: Vec<Roll>,
    roll_handling: RollHandling,
    next_roll: usize,
    front: Contract,
    transfer: Option<Transfer>,
    trades: TradeBook,
    equity: Vec<EquityPoint>,
    eras: Vec<FidelityEra>,
}

/// What comes next in the order of F-CLK-02.
enum Next {
    Unit(Unit),
    Timer(Timer),
    Decision(Ts),
    Done,
}

/// The order of events at one instant (F-CLK-02): the bars closing then, the session events and
/// timers, the records received then, and the decision.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Phase {
    Bars,
    Timers,
    Records,
    Decisions,
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
        let mut book = Book::default();
        book.reserve_through(strategy.highest_order_id());
        let trades = TradeBook::holding(ledger.position().signed_lots().0);
        Ok(Self {
            reader,
            cap: fidelity,
            replay,
            hours,
            settings,
            strategy,
            book,
            ledger,
            fills: Vec::new(),
            log: Vec::new(),
            trade_cash: Money(0),
            closed_trades: Vec::new(),
            in_break: false,
            decisions,
            next_decision: 0,
            next_day: 0,
            day: None,
            fidelity,
            trade_date: TradeDate(0),
            next_record: 0,
            last_record: None,
            timeline: 0,
            costs: RunCosts::default(),
            next_funding: 0,
            cost_lines: Vec::new(),
            warned: false,
            rolls: Vec::new(),
            roll_handling: RollHandling::Transfer,
            next_roll: 0,
            front: reader.contract().clone(),
            transfer: None,
            trades,
            equity: Vec::new(),
            eras: Vec::new(),
        })
    }

    /// The run, recording of its trades' paths what `recording` says: each trade's compact path
    /// unless told otherwise, or none, as a sweep's trials may run (`02` §7).
    #[must_use]
    pub fn with_recording(mut self, recording: Recording) -> Self {
        self.trades = self.trades.recording(recording);
        self
    }

    /// Runs to the end of the records, the timers, and the decisions.
    pub fn run(mut self) -> Result<RunOutputs, RunError> {
        while self.step()?.is_some() {}
        self.value_before_the_legs()?;
        let (trades, trade_paths) = self.trades.into_closed();
        Ok(RunOutputs {
            orders: self.book.into_orders(),
            fills: self.fills,
            log: self.log,
            ledger: self.ledger,
            cost_lines: self.cost_lines,
            trades,
            trade_paths,
            equity: self.equity,
            eras: self.eras,
        })
    }

    /// Handles the next event, a record, a bar, a block of records skipped whole, a roll or a
    /// funding time, or a decision, and says which; none once they have all run out. At one
    /// instant the bars closing then come first, then the timers, then the records received
    /// then, and last the decision (F-CLK-02).
    pub fn step(&mut self) -> Result<Option<Stepped>, RunError> {
        let unit = self.peek_unit()?;
        let index = self.timeline;
        let stepped = match self.next_event(unit) {
            Next::Unit(unit) => match self.skippable() {
                Some(block) => self.skip(unit, block)?,
                None => self.receive(unit, index)?,
            },
            Next::Timer(timer) => self.on_timer(timer, index)?,
            Next::Decision(now) => self.decide(now, index)?,
            Next::Done => return Ok(None),
        };
        self.timeline += stepped.events();
        Ok(Some(stepped))
    }

    /// The cost lines so far.
    pub fn cost_lines(&self) -> &[CostLine] {
        &self.cost_lines
    }

    /// What comes next of `unit`, the next record or bar, the next timer, and the next decision:
    /// the first by instant and phase, compared on those keys alone, which never tie, since each
    /// of the three has a phase of its own.
    fn next_event(&self, unit: Option<Unit>) -> Next {
        let timer = self.next_timer();
        let decision = self.decisions.get(self.next_decision).copied();
        let unit_key = unit.map(|unit| {
            let phase = match unit {
                Unit::Bar(_) => Phase::Bars,
                Unit::Tick(_) => Phase::Records,
            };
            (unit.ts(), phase)
        });
        let timer_key = timer.map(|timer| (timer.at(), Phase::Timers));
        let decision_key = decision.map(|now| (now, Phase::Decisions));
        let first = [unit_key, timer_key, decision_key]
            .into_iter()
            .flatten()
            .min();
        match (unit, timer, decision) {
            (Some(unit), _, _) if first == unit_key => Next::Unit(unit),
            (_, Some(timer), _) if first == timer_key => Next::Timer(timer),
            (_, _, Some(now)) if first == decision_key => Next::Decision(now),
            _ => Next::Done,
        }
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
            self.trade_date = trade_date;
            outcomes::count_in_its_era(&mut self.eras, trade_date, self.fidelity);
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
                    above.push(BarLevel::new(
                        reader.bars(trade_date, timeframe)?,
                        reader.offsets(trade_date, timeframe, finest)?,
                    ));
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
        let trades = &self.closed_trades;
        let mut context = DecisionContext::new(book, log, ledger, trades, now, index, latency);
        self.strategy.on_decision(now, &mut context)?;
        let point = self.equity_at(now)?;
        self.equity.push(point);
        Ok(Stepped::Decision(now))
    }

    /// The account at the decision `now`: the position valued at the mark, or, while a roll's
    /// legs are on their way, at the mark less the gap, its own contract's price (F-ROL-03).
    fn equity_at(&self, now: Ts) -> Result<EquityPoint, RunError> {
        let (cash, position) = (self.ledger.cash(), self.ledger.position().signed_lots());
        let gap = self.transfer.as_ref().map_or(Price(0), Transfer::gap);
        let mark = self
            .ledger
            .mark()
            .map(|mark| mark.checked_sub(gap))
            .transpose()?;
        let equity = match (position.0, mark) {
            (0, _) => Some(cash),
            (_, Some(mark)) => {
                let value = self.ledger.instrument().value(mark, position)?;
                Some(cash.checked_add(value)?)
            }
            (_, None) => None,
        };
        Ok(EquityPoint {
            ts: now,
            cash,
            position,
            mark,
            equity,
        })
    }

    /// Marks the position at `price`, a record's received at `ts` (F-MRK-01), which the open
    /// trade's excursions and its path follow.
    pub(super) fn mark_at(&mut self, ts: Ts, price: Price) -> Result<(), RunError> {
        self.ledger.mark_at(price);
        Ok(self.trades.marked(&self.mark(ts, price, None))?)
    }

    /// A price marked at `ts` on the trade date being read, at a bar's extreme pseudo-tick the
    /// extreme and the bar.
    const fn mark(&self, ts: Ts, price: Price, extreme: Option<(Extreme, BarRow)>) -> Mark {
        Mark {
            ts,
            price,
            fidelity: self.fidelity,
            extreme,
        }
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
