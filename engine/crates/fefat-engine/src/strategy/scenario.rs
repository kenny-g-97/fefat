//! An order scenario's orders as a strategy: each placed at its decision instant, under its own
//! id, as `fefat.reference.scenario_runner` places them.

use fefat_core::instants::Ts;
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, Side};
use fefat_core::units::Qty;

use super::{DecisionContext, DecisionError, Strategy};
use crate::book::Bracket;

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
