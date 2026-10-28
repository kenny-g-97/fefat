//! The strategies the tick loop runs, by the reference engine's protocol (`fefat.reference.strategy`):
//! at each decision instant, a bar close, a strategy places orders through a [`DecisionContext`],
//! each active the run's latency after the decision (F-ACT-01) and seeing only the records after
//! it. [`ScenarioOrders`] places an order scenario's orders at their instants; the execution
//! template is [`crate::template::TemplateStrategy`].

use fefat_core::instants::Ts;
use fefat_core::ledger::{Ledger, Position};
use fefat_core::orders::{ExitReason, TimeInForce};
use fefat_core::orders::{OcoGroupId, Order, OrderId, OrderKind, OrderRole, OrderState, Side};
use fefat_core::units::{Overflow, Qty};
use thiserror::Error;

use crate::book::{Book, Bracket, BracketLink, Closing, WorkingOrder};
use crate::event_log::LogEntry;
use crate::exit_plan::{ExitPlan, PlanError, PlanRow};

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
    /// A signal row an exit plan cannot follow (F-RND-01, F-TRL-02).
    #[error(transparent)]
    Plan(#[from] PlanError),
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
    now: Ts,
    timeline: usize,
    latency_nanoseconds: i64,
}

impl<'run> DecisionContext<'run> {
    pub(crate) const fn new(
        book: &'run mut Book,
        log: &'run mut Vec<LogEntry>,
        ledger: &'run Ledger,
        now: Ts,
        timeline: usize,
        latency_nanoseconds: i64,
    ) -> Self {
        Self {
            book,
            log,
            ledger,
            now,
            timeline,
            latency_nanoseconds,
        }
    }

    /// The position held.
    pub const fn position(&self) -> Position {
        self.ledger.position()
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
            oco: order.oco,
            plan: order.bracket.map(ExitPlan::from),
        };
        self.placed(entry)
    }

    /// Enters at the market with `lots`, its exit plan placed when it fills (F-OCO-02, F-PLN-01),
    /// and returns its id. A strategy holds one position at a time, so it enters flat and with
    /// nothing working.
    pub fn market(
        &mut self,
        side: Side,
        lots: Qty,
        plan: Option<ExitPlan>,
    ) -> Result<OrderId, DecisionError> {
        if self.position() != Position::Flat || self.book.has_live() {
            return Err(DecisionError::NotFlat {
                position: self.position(),
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
            plan,
        };
        self.placed(entry)?;
        Ok(id)
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
            time_in_force: TimeInForce::GoodTillCancelled,
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

/// What a decision places.
struct PlacedEntry {
    id: OrderId,
    side: Side,
    lots: Qty,
    kind: OrderKind,
    role: OrderRole,
    oco: Option<OcoGroupId>,
    plan: Option<ExitPlan>,
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

#[cfg(test)]
mod tests {
    use fefat_core::instants::Ts;
    use fefat_core::instrument::{InstrumentParameters, LotStep};
    use fefat_core::ledger::Ledger;
    use fefat_core::orders::{ExitReason, OrderId, OrderKind, OrderState, Side};
    use fefat_core::units::{Money, Price, Qty};

    use super::{DecisionContext, ScenarioOrder};
    use crate::book::Book;

    #[test]
    fn flatten_leaves_a_stop_triggered_on_tbbo_to_fill_as_the_market_order_it_is() {
        // F-STP-02, S-template-005: no decision cancels a triggered stop.
        let (mut book, mut log) = (Book::default(), Vec::new());
        let es = InstrumentParameters::new(Price(250_000_000), Money(50_000_000), LotStep(1));
        let ledger = Ledger::new(es.unwrap(), Money(0));
        let stop = ScenarioOrder {
            placed_at: Ts(0),
            id: OrderId(1),
            side: Side::Sell,
            lots: Qty(1),
            kind: OrderKind::StopMarket {
                stop: Price(4_999_000_000_000),
            },
            oco: None,
            bracket: None,
        };
        let mut placing = DecisionContext::new(&mut book, &mut log, &ledger, Ts(0), 0, 0);
        placing.place(&stop).unwrap();
        book.activate(OrderId(1)).unwrap();
        book.trigger(OrderId(1)).unwrap();

        let mut later = DecisionContext::new(&mut book, &mut log, &ledger, Ts(1), 1, 0);
        later.flatten(ExitReason::Strategy).unwrap();

        let still = book.live_in(OrderId(1), OrderState::Triggered);
        assert_eq!(still.map(|order| order.order.id), Some(OrderId(1)));
        assert_eq!(log.len(), 1, "{log:?}");
    }
}
