//! The strategies the tick loop runs, by the reference engine's protocol (`fefat.reference.strategy`):
//! at each decision instant, a bar close, a strategy places orders through a [`DecisionContext`],
//! each active the run's latency after the decision (F-ACT-01) and seeing only the records after
//! it. [`ScenarioOrders`] places an order scenario's orders at their instants; the execution
//! template is [`crate::template::TemplateStrategy`].

use fefat_core::instants::Ts;
use fefat_core::ledger::Position;
use fefat_core::orders::TimeInForce;
use fefat_core::orders::{OcoGroupId, Order, OrderId, OrderKind, OrderRole, OrderState, Side};
use fefat_core::units::{Overflow, Qty};
use thiserror::Error;

use crate::book::{Book, Bracket, WorkingOrder};
use crate::event_log::LogEntry;

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
    /// An instant or a price beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
}

/// What a strategy sees and does at one decision: the instant, its position, and its working
/// orders; and the orders it places, each active the run's latency later and seeing only the
/// records after the decision (F-ACT-01).
pub struct DecisionContext<'run> {
    book: &'run mut Book,
    log: &'run mut Vec<LogEntry>,
    position: Position,
    now: Ts,
    timeline: usize,
    latency_nanoseconds: i64,
}

impl<'run> DecisionContext<'run> {
    pub(crate) const fn new(
        book: &'run mut Book,
        log: &'run mut Vec<LogEntry>,
        position: Position,
        now: Ts,
        timeline: usize,
        latency_nanoseconds: i64,
    ) -> Self {
        Self {
            book,
            log,
            position,
            now,
            timeline,
            latency_nanoseconds,
        }
    }

    /// The decision's instant.
    pub const fn now(&self) -> Ts {
        self.now
    }

    /// The position held.
    pub const fn position(&self) -> Position {
        self.position
    }

    /// Whether any order works or waits.
    pub fn has_working_orders(&self) -> bool {
        self.book.has_live()
    }

    /// Whether the market order that [`Self::flatten`] placed to close the position still works.
    pub fn is_exiting(&self) -> bool {
        self.book.is_exiting()
    }

    /// Places an order scenario's order under its own id, in any position.
    pub fn place(&mut self, order: &ScenarioOrder) -> Result<(), DecisionError> {
        let entry = PlacedEntry {
            id: order.id,
            side: order.side,
            lots: order.lots,
            kind: order.kind,
            role: OrderRole::Entry,
            oco: order.oco,
            bracket: order.bracket,
        };
        self.placed(entry)
    }

    /// Enters at the market with `lots`, its bracket placed when it fills (F-OCO-02), and returns
    /// its id. A strategy holds one position at a time, so it enters flat and with nothing
    /// working.
    pub fn market(
        &mut self,
        side: Side,
        lots: Qty,
        bracket: Option<Bracket>,
    ) -> Result<OrderId, DecisionError> {
        if self.position != Position::Flat || self.book.has_live() {
            return Err(DecisionError::NotFlat {
                position: self.position,
                working: self.book.live_ids().len(),
                at: self.now,
            });
        }
        let id = self.book.new_id();
        let entry = PlacedEntry {
            id,
            side,
            lots,
            kind: OrderKind::Market,
            role: OrderRole::Entry,
            oco: None,
            bracket,
        };
        self.placed(entry)?;
        Ok(id)
    }

    /// Cancels every working order and, with a position open, places a market order that closes
    /// it.
    pub fn flatten(&mut self) -> Result<(), DecisionError> {
        for id in self.book.live_ids() {
            self.book.close(id, OrderState::Cancelled);
            self.log.push(LogEntry::cancelled_by_strategy(self.now, id));
        }
        let (side, held) = match self.position {
            Position::Flat => return Ok(()),
            Position::Long(held) => (Side::Sell, held),
            Position::Short(held) => (Side::Buy, held),
        };
        let exit = PlacedEntry {
            id: self.book.new_id(),
            side,
            lots: held.lots(),
            kind: OrderKind::Market,
            role: OrderRole::Exit,
            oco: None,
            bracket: None,
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
            time_in_force: TimeInForce::GoodTillCancelled,
            placed_at: self.now,
            activation: self.now.checked_add_nanoseconds(self.latency_nanoseconds)?,
            oco: entry.oco,
        };
        self.log.push(LogEntry::placed(&order));
        self.book.place(WorkingOrder {
            order,
            state: OrderState::Waiting,
            rested: false,
            seen_after: self.timeline,
            bracket: entry.bracket,
            bracket_of: None,
        });
        Ok(())
    }
}

/// What a decision places.
struct PlacedEntry {
    id: OrderId,
    side: Side,
    lots: Qty,
    kind: OrderKind,
    role: OrderRole,
    oco: Option<OcoGroupId>,
    bracket: Option<Bracket>,
}

/// An order of an order scenario: placed at `placed_at`, a decision instant, under its own id,
/// with its OCO group and its bracket.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ScenarioOrder {
    /// The decision instant that places it.
    pub placed_at: Ts,
    /// Its id.
    pub id: OrderId,
    /// Buy or sell.
    pub side: Side,
    /// Its lots.
    pub lots: Qty,
    /// Market, stop-market, or limit, with its price.
    pub kind: OrderKind,
    /// Its OCO group, if any.
    pub oco: Option<OcoGroupId>,
    /// The bracket its fill places, if any.
    pub bracket: Option<Bracket>,
}

/// An order scenario's orders, each placed at its decision instant, in the scenario's order
/// (`fefat.reference.scenario_runner`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScenarioOrders {
    orders: Vec<ScenarioOrder>,
}

impl ScenarioOrders {
    /// The strategy that places `orders`.
    pub const fn new(orders: Vec<ScenarioOrder>) -> Self {
        Self { orders }
    }
}

impl Strategy for ScenarioOrders {
    fn decision_instants(&self) -> Vec<Ts> {
        let mut instants: Vec<Ts> = self.orders.iter().map(|order| order.placed_at).collect();
        instants.sort_unstable();
        instants.dedup();
        instants
    }

    fn on_decision(
        &mut self,
        now: Ts,
        context: &mut DecisionContext<'_>,
    ) -> Result<(), DecisionError> {
        for order in self.orders.iter().filter(|order| order.placed_at == now) {
            context.place(order)?;
        }
        Ok(())
    }
}
