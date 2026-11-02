//! The strategies the tick loop runs, by the reference engine's protocol (`fefat.reference.strategy`):
//! at each decision instant, a bar close, a strategy places orders through a [`DecisionContext`],
//! each active the run's latency after the decision (F-ACT-01) and seeing only the records after
//! it. [`ScenarioOrders`] places an order scenario's orders at their instants; the execution
//! template is [`crate::template::TemplateStrategy`].

use fefat_core::instants::Ts;
use fefat_core::ledger::{Ledger, LedgerError, Position};
use fefat_core::orders::{ExitReason, TimeInForce};
use fefat_core::orders::{OcoGroupId, Order, OrderId, OrderKind, OrderRole, OrderState, Side};
use fefat_core::units::{Money, Overflow, Price, Qty};
use thiserror::Error;

use crate::book::{Book, BracketLink, Closing, WorkingOrder};
use crate::event_log::LogEntry;
use crate::exit_plan::{ExitPlan, PlanError, PlanRow};

mod scenario;
#[cfg(test)]
mod tests;

pub use scenario::{ScenarioOrder, ScenarioOrders};

/// A strategy: the instants it decides at and what it decides there.
pub trait Strategy {
    /// The instants of its decisions, each once and in ascending order.
    fn decision_instants(&self) -> Vec<Ts>;

    /// Its decision at `now`, one of its decision instants.
    fn on_decision(
        &mut self,
        now: Ts,
        context: &mut DecisionContext<'_>,
    ) -> Result<(), DecisionError>;

    /// The highest id it gives its own orders, after which the run numbers its own, a roll's legs
    /// (F-ROL-02); none when the run numbers every order.
    fn highest_order_id(&self) -> Option<OrderId> {
        None
    }
}

/// A decision the engine refused.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum DecisionError {
    /// An entry while a position is open or orders work: one position per strategy.
    #[error(
        "Expected an entry while flat with no working orders (one position per strategy), got \
         {position} and {working} working orders at {at}"
    )]
    NotFlat {
        /// The position held.
        position: Position,
        /// How many orders work.
        working: usize,
        /// The decision's instant.
        at: Ts,
    },
    /// An order of no lots, or of fewer than none.
    #[error("Expected order {order} of one lot or more, got {lots} lots at {at}")]
    NoLots {
        /// The order.
        order: u64,
        /// Its lots.
        lots: Qty,
        /// The decision's instant.
        at: Ts,
    },
    /// A signal row the template cannot act on.
    #[error("Expected {expected}, got {actual} on the signal close of {at}")]
    Signal {
        /// What the template needs.
        expected: String,
        /// What the row holds.
        actual: String,
        /// The row's close.
        at: Ts,
    },
    /// A signal row an exit plan cannot follow (F-RND-01, F-TRL-02).
    #[error(transparent)]
    Plan(#[from] PlanError),
    /// Equity the ledger cannot work out, a position without a mark.
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    /// An instant or a price beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
}

/// What a strategy sees and does at one decision: the instant, its position and the mark, and its
/// working orders; and the orders it places, each active the run's latency later and seeing only
/// the records after the decision (F-ACT-01).
pub struct DecisionContext<'run> {
    book: &'run mut Book,
    log: &'run mut Vec<LogEntry>,
    ledger: &'run Ledger,
    closed_trades: &'run [ClosedTrade],
    now: Ts,
    timeline: usize,
    latency_nanoseconds: i64,
    roll_gap: Price,
}

impl<'run> DecisionContext<'run> {
    pub(crate) const fn new(
        book: &'run mut Book,
        log: &'run mut Vec<LogEntry>,
        ledger: &'run Ledger,
        closed_trades: &'run [ClosedTrade],
        now: Ts,
        timeline: usize,
        latency_nanoseconds: i64,
    ) -> Self {
        Self {
            book,
            log,
            ledger,
            closed_trades,
            now,
            timeline,
            latency_nanoseconds,
            roll_gap: Price(0),
        }
    }

    /// The context of a decision taken while a roll's legs are on their way, `gap` the roll's
    /// gap: equity values the position at the mark less it, its own contract's price (F-ROL-03).
    #[must_use]
    pub(crate) const fn before_the_legs(mut self, gap: Price) -> Self {
        self.roll_gap = gap;
        self
    }

    /// The position held.
    pub const fn position(&self) -> Position {
        self.ledger.position()
    }

    /// The mark, the last tradeable price before the decision (F-MRK-01), none before the first.
    pub const fn mark(&self) -> Option<Price> {
        self.ledger.mark()
    }

    /// Cash plus the open position's value at the mark, floored (F-MRK-01), or, while a roll's
    /// legs are on their way, at the mark less the roll's gap (F-ROL-03), as the run's equity at
    /// each decision is.
    pub fn equity(&self) -> Result<Money, DecisionError> {
        let (cash, position) = (self.ledger.cash(), self.ledger.position());
        if position == Position::Flat {
            return Ok(cash);
        }
        let mark = self
            .ledger
            .mark()
            .ok_or(LedgerError::UnmarkedPosition { position })?;
        let value = self
            .ledger
            .instrument()
            .value(mark.checked_sub(self.roll_gap)?, position.signed_lots())?;
        Ok(cash.checked_add(value)?)
    }

    /// The trades closed so far but the first `after` (F-LIM-02).
    pub fn closed_trades(&self, after: usize) -> &[ClosedTrade] {
        self.closed_trades.get(after..).unwrap_or_default()
    }

    /// The instant of the fill that opened the position, none when flat or for a position held
    /// when the tape starts (F-TIM-02).
    pub const fn opened_at(&self) -> Option<Ts> {
        self.ledger.opened_at()
    }

    /// Whether any order works or waits.
    pub fn has_working_orders(&self) -> bool {
        self.book.has_live()
    }

    /// Whether a market order is on its way out of the position: one [`Self::flatten`] placed,
    /// or a stop triggered on TBBO, which no decision cancels (F-STP-02).
    pub fn is_exiting(&self) -> bool {
        self.book.is_exiting()
    }

    /// Whether an entry stop triggered on TBBO is on its way into a position, a market order from
    /// its trigger that no decision cancels (F-STP-02, F-ENT-03).
    pub fn is_entering(&self) -> bool {
        self.book.is_entering()
    }

    /// The decision's turn of each live exit plan on `row` (F-PLN-04): a trailing stop by a
    /// feature takes the row's distance, and one that moves at decisions moves (F-TRL-02,
    /// F-TRL-04), the market at the mark.
    pub fn update_exit_plans(&mut self, row: &PlanRow) -> Result<(), DecisionError> {
        let Some(mark) = self.ledger.mark() else {
            return Ok(());
        };
        let tick = self.ledger.instrument().tick_size();
        let moves = self.book.at_decision(row, mark, tick)?;
        let entries = moves.iter().map(|moved| LogEntry::moved(self.now, moved));
        self.log.extend(entries);
        Ok(())
    }

    /// Places an order scenario's order under its own id, in any position, its bracket as an
    /// exit plan.
    pub fn place(&mut self, order: &ScenarioOrder) -> Result<(), DecisionError> {
        let entry = PlacedEntry {
            id: order.id,
            side: order.side,
            lots: order.lots,
            kind: order.kind,
            role: OrderRole::Entry,
            time_in_force: TimeInForce::GoodTillCancelled,
            oco: order.oco,
            plan: order.bracket.map(ExitPlan::from),
        };
        self.placed(entry)
    }

    /// Places `entries`, one entry or a long and short pair, the pair as one OCO group
    /// (F-ENT-01), and returns their ids. A strategy holds one position at a time, so it enters
    /// flat with nothing working, or, `reversing`, right after [`Self::flatten`] placed its exit,
    /// whose id comes first (F-ENT-04).
    pub fn enter(
        &mut self,
        entries: Vec<Entry>,
        reversing: bool,
    ) -> Result<Vec<OrderId>, DecisionError> {
        if !reversing {
            self.require_flat()?;
        }
        let ids: Vec<OrderId> = entries.iter().map(|_| self.book.new_id()).collect();
        let pair = ids.first().filter(|_| ids.len() > 1);
        let group = pair.map(|first| OcoGroupId(first.0));
        for (&id, entry) in ids.iter().zip(entries) {
            self.placed(PlacedEntry {
                id,
                side: entry.side,
                lots: entry.lots,
                kind: entry.kind,
                role: OrderRole::Entry,
                time_in_force: entry.time_in_force,
                oco: group,
                plan: entry.plan,
            })?;
        }
        Ok(ids)
    }

    /// Cancels the live entries placed at or before `at`, whose time to live has ended
    /// (F-ENT-03); an entry stop triggered on TBBO, a market order already sent, stays (F-STP-02).
    pub fn cancel_entries_placed_by(&mut self, at: Ts) {
        let ended: Vec<OrderId> = self
            .book
            .live()
            .filter(|order| order.order.role == OrderRole::Entry && order.order.placed_at <= at)
            .filter(|order| order.state() != OrderState::Triggered)
            .map(|order| order.order.id)
            .collect();
        for id in ended {
            self.book.close(id, Closing::Cancelled);
            self.log.push(LogEntry::expired(self.now, id));
        }
    }

    /// Logs an entry signal the strategy could not act on, and why (F-ENT-02, F-SIZ-04).
    pub fn skipped(&mut self, why: &str, rule: &'static str) {
        self.log.push(LogEntry::skipped(self.now, why, rule));
    }

    fn require_flat(&self) -> Result<(), DecisionError> {
        if self.position() != Position::Flat || self.book.has_live() {
            return Err(DecisionError::NotFlat {
                position: self.position(),
                working: self.book.live_ids().len(),
                at: self.now,
            });
        }
        Ok(())
    }

    /// Cancels every working order and, with a position open, places a market order that closes
    /// it, its role the exit's `reason` (F-TAG-01); nothing while a market order is already on its
    /// way out of the position ([`Self::is_exiting`]), and a stop triggered on TBBO stays, since
    /// no decision cancels it (F-STP-02).
    pub fn flatten(&mut self, reason: ExitReason) -> Result<(), DecisionError> {
        if self.is_exiting() {
            return Ok(());
        }
        for id in self.book.live_ids() {
            if self.book.live_in(id, OrderState::Triggered).is_some() {
                continue;
            }
            self.book.close(id, Closing::Cancelled);
            self.log.push(LogEntry::cancelled_by_strategy(self.now, id));
        }
        let (side, held) = match self.position() {
            Position::Flat => return Ok(()),
            Position::Long(held) => (Side::Sell, held),
            Position::Short(held) => (Side::Buy, held),
        };
        let exit = PlacedEntry {
            id: self.book.new_id(),
            side,
            lots: held.lots(),
            kind: OrderKind::Market,
            role: OrderRole::Exit(reason),
            time_in_force: TimeInForce::GoodTillCancelled,
            oco: None,
            plan: None,
        };
        self.placed(exit)
    }

    fn placed(&mut self, entry: PlacedEntry) -> Result<(), DecisionError> {
        if entry.lots.0 < 1 {
            return Err(DecisionError::NoLots {
                order: entry.id.0,
                lots: entry.lots,
                at: self.now,
            });
        }
        let order = Order {
            id: entry.id,
            side: entry.side,
            lots: entry.lots,
            kind: entry.kind,
            role: entry.role,
            time_in_force: entry.time_in_force,
            placed_at: self.now,
            activation: self.now.checked_add_nanoseconds(self.latency_nanoseconds)?,
            oco: entry.oco,
        };
        self.log.push(LogEntry::placed(&order));
        let link = entry.plan.map_or(BracketLink::Unbracketed, |plan| {
            BracketLink::Entry(Box::new(plan))
        });
        self.book
            .place(WorkingOrder::placed(order, self.timeline, link));
        Ok(())
    }
}

/// A trade that closed (`docs/spec/fill-semantics.md` §20): the instant of the fill that left
/// the position flat, and what its fills moved the cash by, less their fees, a loss below zero.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClosedTrade {
    /// The instant of the fill that left the position flat.
    pub closed_at: Ts,
    /// What its fills moved the cash by, less their fees.
    pub pnl: Money,
}

/// An entry a decision places: its side, its class with its price, its lots, how long it works,
/// and the exit plan its fill places (F-PLN-01).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    /// Buy or sell.
    pub side: Side,
    /// Market, stop-market, or limit, with its price.
    pub kind: OrderKind,
    /// Its lots.
    pub lots: Qty,
    /// How long it works: a resting entry's time to live, in signal bars (F-ENT-03).
    pub time_in_force: TimeInForce,
    /// The exit plan its fill places.
    pub plan: Option<ExitPlan>,
}

/// What a decision places.
struct PlacedEntry {
    id: OrderId,
    side: Side,
    lots: Qty,
    kind: OrderKind,
    role: OrderRole,
    time_in_force: TimeInForce,
    oco: Option<OcoGroupId>,
    plan: Option<ExitPlan>,
}
