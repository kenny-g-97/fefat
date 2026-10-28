//! An exit plan once its entry has filled, as `fefat.reference.exit_plan.LivePlan` follows it: the
//! entry's side, fill price, and lots still open; its initial risk; its stop's id and its targets'
//! numbers by id; the best price marked since the fill; the targets filled; whether its breakeven
//! has fired and its trailing stop works; and the trailing stop's distance. The book holds each
//! live plan beside its legs and applies what the plan works out here: the moves of its stop
//! (F-PLN-03, F-PLN-04) and what a leg's fill leaves (F-PLN-02).

use fefat_core::instants::Ts;
use fefat_core::orders::{OrderId, Side, TargetNumber};
use fefat_core::units::{Overflow, Price, Qty};

use super::{
    ExitPlan, PlanError, TrailDistance, Trigger, capped, f_brk_01, f_pln_03, f_rnd_01, f_trl_03,
    f_trl_04, feature_ticks, feature_units,
};

/// What moved a stop.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MoveRule {
    /// Its breakeven (F-BRK-01).
    Breakeven,
    /// Its trailing stop (F-TRL-01).
    Trailing,
}

impl MoveRule {
    /// The rule's identifier, which the log records.
    pub const fn id(self) -> &'static str {
        match self {
            Self::Breakeven => "F-BRK-01",
            Self::Trailing => "F-TRL-01",
        }
    }
}

/// A stop its plan moved, from `before` to `after`, under `rule`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Move {
    /// The stop.
    pub order: OrderId,
    /// Its level before.
    pub before: Price,
    /// Its level after.
    pub after: Price,
    /// What moved it.
    pub rule: MoveRule,
}

/// A decision's signal row as an exit plan reads it (F-TRL-02): its close, the feature of a
/// trailing stop by a feature, and `trail_ref`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlanRow {
    /// The row's close, the decision's instant.
    pub at: Ts,
    /// The trailing stop's feature on the row, where it gives one.
    pub trail_feature: Option<f64>,
    /// The row's `trail_ref`, where it gives one.
    pub trail_ref: Option<Price>,
}

/// What a leg's fill leaves its plan to do (F-PLN-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegSettlement {
    /// Cancel the plan's other legs: its stop filled, or no lots stay open.
    CancelTheRest,
    /// Reduce the plan's stop, where it has one, to these lots, still open.
    ReduceTheStop(Qty),
}

/// A level a plan proposes for its stop, and what proposes it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Proposal {
    pub(crate) level: Price,
    pub(crate) rule: MoveRule,
}

/// What an entry's fill gives its plan: the entry's side, fill price, and lots; the initial risk
/// (F-RND-02); the stop's id and the targets' ids with their numbers; and the market at the fill,
/// where the best price starts (F-PLN-04).
pub(super) struct Placement {
    pub(super) side: Side,
    pub(super) fill: Price,
    pub(super) lots: Qty,
    pub(super) risk: Option<u32>,
    pub(super) stop: Option<OrderId>,
    pub(super) targets: Vec<(OrderId, TargetNumber)>,
    pub(super) market: Price,
}

/// An entry's plan once it has filled (module documentation).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LivePlan {
    plan: ExitPlan,
    side: Side,
    fill: Price,
    open_lots: Qty,
    risk: Option<u32>,
    stop: Option<OrderId>,
    targets: Vec<(OrderId, TargetNumber)>,
    filled_targets: Vec<TargetNumber>,
    best: Price,
    distance: Option<u32>,
    breakeven_fired: bool,
    trailing_works: bool,
}

impl LivePlan {
    /// The plan as its entry's fill leaves it: all its lots open, its best price the market, and
    /// a trailing stop without an activation working from the fill.
    pub(super) fn placed(plan: ExitPlan, placement: Placement) -> Self {
        let distance = plan.trailing.and_then(|trailing| match trailing.distance {
            TrailDistance::Ticks(ticks) | TrailDistance::Feature { ticks, .. } => Some(ticks),
            TrailDistance::Column => None,
        });
        let trailing_works = plan
            .trailing
            .is_some_and(|trailing| trailing.activation.is_none());
        Self {
            plan,
            side: placement.side,
            fill: placement.fill,
            open_lots: placement.lots,
            risk: placement.risk,
            stop: placement.stop,
            targets: placement.targets,
            filled_targets: Vec::new(),
            best: placement.market,
            distance,
            breakeven_fired: false,
            trailing_works,
        }
    }

    /// The plan's stop, where it has one.
    pub(crate) const fn stop(&self) -> Option<OrderId> {
        self.stop
    }

    /// Whether the plan has a trailing stop, which follows its best price (F-PLN-05).
    #[cfg(test)]
    pub(crate) const fn trails(&self) -> bool {
        self.plan.trailing.is_some()
    }

    /// F-PLN-02: the plan's leg `leg` filled `lots`. A target's lots leave the open lots, and what
    /// follows is to cancel the other legs, when the stop filled or no lots stay open, or to
    /// reduce the stop to the lots still open.
    pub(crate) fn settled(&mut self, leg: OrderId, lots: Qty) -> LegSettlement {
        if Some(leg) == self.stop {
            return LegSettlement::CancelTheRest;
        }
        self.open_lots = Qty(self.open_lots.0 - lots.0);
        let filled = self.targets.iter().find(|(id, _)| *id == leg);
        self.filled_targets
            .extend(filled.map(|&(_, number)| number));
        if self.open_lots.0 > 0 {
            LegSettlement::ReduceTheStop(self.open_lots)
        } else {
            LegSettlement::CancelTheRest
        }
    }

    /// F-PLN-04: a price marked once the fills at it are done. The best price follows it, a
    /// waiting trigger may fire (F-BRK-02), and the breakeven (F-BRK-01) and an intrabar trailing
    /// stop (F-TRL-01, F-TRL-04) propose their levels for the stop, the breakeven's first.
    pub(crate) fn at_price(
        &mut self,
        price: Price,
        tick: Price,
    ) -> Result<Vec<Proposal>, Overflow> {
        self.best = self.side.better(self.best, price);
        let mut proposed = Vec::new();
        if let Some(breakeven) = self.plan.breakeven
            && !self.breakeven_fired
            && self.f_brk_02(breakeven.trigger, tick)?
        {
            self.breakeven_fired = true;
            let level = f_brk_01(self.side, self.fill, breakeven.offset_ticks, tick)?;
            proposed.push(Proposal {
                level,
                rule: MoveRule::Breakeven,
            });
        }
        let Some(trailing) = self.plan.trailing else {
            return Ok(proposed);
        };
        if let Some(activation) = trailing.activation
            && !self.trailing_works
        {
            self.trailing_works = self.f_brk_02(activation, tick)?;
        }
        if self.trailing_works
            && f_trl_04(&trailing, false)
            && let Some(level) = self.f_trl_01(tick)?
        {
            proposed.push(Proposal {
                level,
                rule: MoveRule::Trailing,
            });
        }
        Ok(proposed)
    }

    /// F-PLN-04 at a decision on `row`: a trailing stop by a feature takes the row's distance
    /// (F-TRL-02), and a working trailing stop proposes the best price less its distance, or the
    /// row's `trail_ref` for one by the column, which must lie on the tick (F-RND-01).
    pub(crate) fn at_decision(
        &mut self,
        row: &PlanRow,
        tick: Price,
    ) -> Result<Option<Proposal>, PlanError> {
        let Some(trailing) = self.plan.trailing else {
            return Ok(None);
        };
        if let TrailDistance::Feature { multiple, .. } = trailing.distance
            && let Some(value) = row.trail_feature
        {
            let units = feature_units(value).ok_or_else(|| PlanError::Feature {
                rule: "trailing stop",
                value: value.to_string(),
                at: row.at,
            })?;
            self.distance = Some(feature_ticks(multiple, units, tick, false)?);
        }
        if !(self.trailing_works && f_trl_04(&trailing, true)) {
            return Ok(None);
        }
        let by_column = matches!(trailing.distance, TrailDistance::Column);
        let level = match by_column {
            true => row.trail_ref,
            false => self.f_trl_01(tick)?,
        };
        let Some(level) = level else {
            return Ok(None);
        };
        if by_column && level.0.rem_euclid(tick.0) != 0 {
            return Err(PlanError::OffTheTick {
                trail_ref: level,
                tick,
                at: row.at,
            });
        }
        Ok(Some(Proposal {
            level,
            rule: MoveRule::Trailing,
        }))
    }

    /// The level the stop at `current` moves to, of the levels `proposed`, with the market at
    /// `market` (F-PLN-03): a trailing level held one tick short of the market and taken in whole
    /// steps (F-TRL-03); the highest level, the first among equals; none when it would not raise
    /// the stop.
    pub(crate) fn chosen(
        &self,
        current: Price,
        proposed: &[Proposal],
        market: Price,
        tick: Price,
    ) -> Result<Option<Proposal>, Overflow> {
        let ceiling = self.side.opposite().moved(market, 1, tick)?;
        let steps = self.plan.trailing.and_then(|trailing| trailing.step_ticks);
        let mut highest: Option<Proposal> = None;
        for proposal in proposed {
            let level = match proposal.rule {
                MoveRule::Breakeven => proposal.level,
                MoveRule::Trailing => {
                    let held = capped(self.side, proposal.level, ceiling);
                    f_trl_03(self.side, current, held, steps, tick)?
                }
            };
            if highest.is_none_or(|kept| self.side.better(level, kept.level) != kept.level) {
                highest = Some(Proposal {
                    level,
                    rule: proposal.rule,
                });
            }
        }
        let Some(highest) = highest else {
            return Ok(None);
        };
        let moved = f_pln_03(self.side, current, highest.level, market, tick)?;
        Ok(moved.map(|level| Proposal {
            level,
            rule: highest.rule,
        }))
    }

    /// F-PLN-05: whether a bar from `low` to `high` leaves the plan as a replay of it would: it
    /// rises no higher than the best price of a plan with a trailing stop, and reaches no profit
    /// trigger still waiting.
    pub(crate) fn untouched_by(
        &self,
        low: Price,
        high: Price,
        tick: Price,
    ) -> Result<bool, Overflow> {
        let beyond = match self.side {
            Side::Buy => high,
            Side::Sell => low,
        };
        let past_the_best = self.side.better(beyond, self.best) != self.best;
        if self.plan.trailing.is_some() && past_the_best {
            return Ok(false);
        }
        for trigger in self.waiting_triggers() {
            if let Some(level) = self.trigger_level(trigger, tick)?
                && self.side.better(beyond, level) == beyond
            {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// F-BRK-02: whether `trigger` has fired: a profit trigger once the best price reaches its
    /// level, an `after_target` trigger once that target has filled.
    fn f_brk_02(&self, trigger: Trigger, tick: Price) -> Result<bool, Overflow> {
        if let Trigger::AfterTarget(number) = trigger {
            return Ok(self.filled_targets.contains(&number));
        }
        let level = self.trigger_level(trigger, tick)?;
        Ok(level.is_some_and(|level| self.side.better(self.best, level) == self.best))
    }

    /// F-TRL-01: a working trailing stop's level, the best price less its distance; none for one
    /// by the column.
    fn f_trl_01(&self, tick: Price) -> Result<Option<Price>, Overflow> {
        let level = self
            .distance
            .map(|distance| self.side.opposite().moved(self.best, distance, tick));
        level.transpose()
    }

    /// The price a profit trigger fires at, rounded away from the fill (F-RND-01); none for one
    /// after a target, or in R without an initial risk.
    fn trigger_level(&self, trigger: Trigger, tick: Price) -> Result<Option<Price>, Overflow> {
        let ticks = match (trigger, self.risk) {
            (Trigger::Ticks(ticks), _) => ticks,
            (Trigger::Risk(multiple), Some(risk)) => {
                let units = i128::from(risk) * i128::from(tick.0);
                f_rnd_01(multiple, units, 1, tick, true)?
            }
            (Trigger::Risk(_), None) | (Trigger::AfterTarget(_), _) => return Ok(None),
        };
        self.side.moved(self.fill, ticks, tick).map(Some)
    }

    /// The profit triggers that have not fired yet: the breakeven's, then the trailing stop's
    /// activation.
    fn waiting_triggers(&self) -> impl Iterator<Item = Trigger> {
        let breakeven = self
            .plan
            .breakeven
            .filter(|_| !self.breakeven_fired)
            .map(|breakeven| breakeven.trigger);
        let activation = self
            .plan
            .trailing
            .and_then(|trailing| trailing.activation)
            .filter(|_| !self.trailing_works);
        breakeven.into_iter().chain(activation)
    }
}
