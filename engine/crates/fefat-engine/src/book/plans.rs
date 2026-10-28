//! The book's exit plans, by their entries' ids, while a leg of theirs lives: each follows
//! the prices marked and the decisions, moving its stop (F-PLN-03, F-PLN-04), and settles its
//! open lots when a leg fills (F-PLN-02), as `fefat.reference.exit_plan` has the reference's
//! book do.

use fefat_core::orders::{OrderId, OrderKind, OrderState};
use fefat_core::units::{Overflow, Price, Qty};

use super::{Book, Closing, WorkingOrder};
use crate::exit_plan::{LegSettlement, LivePlan, Move, PlanError, PlanRow, Proposal};

/// What a leg's fill did to its plan (F-PLN-02): the legs it cancelled, and the stop it reduced
/// with the lots left.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct Settled {
    pub(crate) cancelled: Vec<OrderId>,
    pub(crate) reduced: Option<(OrderId, Qty)>,
}

impl Book {
    /// Follows the plan of `entry`, whose legs the book holds, until its last leg closes.
    pub(crate) fn follow(&mut self, entry: OrderId, plan: LivePlan) {
        self.plans.insert(entry, plan);
    }

    /// The live plans, by their entries' ids.
    pub(crate) fn plans(&self) -> impl Iterator<Item = &LivePlan> {
        self.plans.values()
    }

    /// F-PLN-04: the price marked at `price`, once its fills are done: each plan, by its entry's
    /// id, follows it and may move its stop.
    pub(crate) fn marked(&mut self, price: Price, tick: Price) -> Result<Vec<Move>, Overflow> {
        let mut moves = Vec::new();
        for plan in self.plans.values_mut() {
            let proposed = plan.at_price(price, tick)?;
            moves.extend(move_stop(&mut self.live, plan, &proposed, price, tick)?);
        }
        Ok(moves)
    }

    /// F-PLN-04 at a decision on `row`, the position marked at `mark`: each plan's fired
    /// breakeven and trailing stop that moves at decisions may move its stop (F-BRK-01, F-TRL-02,
    /// F-TRL-04).
    pub(crate) fn at_decision(
        &mut self,
        row: &PlanRow,
        mark: Price,
        tick: Price,
    ) -> Result<Vec<Move>, PlanError> {
        let mut moves = Vec::new();
        for plan in self.plans.values_mut() {
            let proposed = plan.at_decision(row, tick)?;
            moves.extend(move_stop(&mut self.live, plan, &proposed, mark, tick)?);
        }
        Ok(moves)
    }

    /// F-PLN-02: what the fill of `filled`, closed already, does to its plan: a target's lots
    /// leave its open lots, and its stop is reduced to the lots left, or its other legs are
    /// cancelled when the stop filled or no lots stay open.
    pub(crate) fn settle(&mut self, filled: &WorkingOrder) -> Settled {
        let Some(entry) = filled.link.leg_of() else {
            return Settled::default();
        };
        let Some(plan) = self.plans.get_mut(&entry) else {
            return Settled::default();
        };
        match plan.settled(filled.order.id, filled.order.lots) {
            LegSettlement::ReduceTheStop(lots) => {
                let stop = plan.stop();
                let stop = self
                    .live
                    .iter_mut()
                    .find(|order| Some(order.order.id) == stop);
                let Some(stop) = stop else {
                    return Settled::default();
                };
                stop.order.lots = lots;
                Settled {
                    cancelled: Vec::new(),
                    reduced: Some((stop.order.id, lots)),
                }
            }
            LegSettlement::CancelTheRest => {
                let mut legs: Vec<OrderId> = self
                    .live
                    .iter()
                    .filter(|leg| leg.link.leg_of() == Some(entry))
                    .map(|leg| leg.order.id)
                    .collect();
                legs.sort_unstable();
                for &leg in &legs {
                    self.close(leg, Closing::Cancelled);
                }
                Settled {
                    cancelled: legs,
                    reduced: None,
                }
            }
        }
    }
}

/// Moves `plan`'s stop among `live` to the level it chooses of `proposed`, with the market at
/// `market` (F-PLN-03); a stop triggered on TBBO, a market order already sent, stays (F-STP-02).
fn move_stop(
    live: &mut [WorkingOrder],
    plan: &LivePlan,
    proposed: &[Proposal],
    market: Price,
    tick: Price,
) -> Result<Option<Move>, Overflow> {
    if proposed.is_empty() {
        return Ok(None);
    }
    let stop = live
        .iter_mut()
        .find(|order| Some(order.order.id) == plan.stop());
    let Some(stop) = stop.filter(|stop| stop.state != OrderState::Triggered) else {
        return Ok(None);
    };
    let Some(current) = stop.level() else {
        return Ok(None);
    };
    let Some(chosen) = plan.chosen(current, proposed, market, tick)? else {
        return Ok(None);
    };
    stop.order.kind = OrderKind::StopMarket { stop: chosen.level };
    Ok(Some(Move {
        order: stop.order.id,
        before: current,
        after: chosen.level,
        rule: chosen.rule,
    }))
}
