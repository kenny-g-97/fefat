//! Exit plans (`docs/spec/fill-semantics.md` §21 to §24, step 2.8), as `fefat.reference.exit_plan`
//! works them: the stop, the targets, the breakeven, and the trailing stop an entry carries
//! ([`ExitPlan`]), placed when it fills ([`place`]), and what follows from them while its position
//! is open ([`LivePlan`]): the legs share the open lots, and the stop moves only in the position's
//! favour, at each price the loop marks and at each decision. Every distance is worked out exactly
//! before it is rounded to the tick (F-RND-01), and each rule is a function named after its
//! identifier, as in `rules`.

mod live;
mod placing;
#[cfg(test)]
mod tests;

pub(crate) use live::{LegSettlement, LivePlan, Proposal};
pub use live::{Move, MoveRule, PlanRow};
pub(crate) use placing::{FilledAt, place, stop_level};

use std::cmp::Ordering;

use fefat_core::instants::Ts;
use fefat_core::orders::{OrderId, Side, TargetNumber};
use fefat_core::strategy_spec::TrailUpdate;
use fefat_core::units::{Overflow, Price, Qty};
use thiserror::Error;

use crate::book::{Bracket, LegPrice};
use crate::exact_decimal::ExactDecimal;

/// Where an exit plan's stop lies.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopAt {
    /// At this price, wherever the entry fills: the signal frame's `stop_price`, or an order
    /// scenario's.
    Price(Price),
    /// This many ticks below a long's fill price, above a short's.
    TicksFromFill(u32),
    /// This percentage of the fill price below a long's fill, rounded down (F-RND-01).
    PercentOfFill(ExactDecimal),
}

/// Where an exit plan's target lies.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetAt {
    /// At this price, wherever the entry fills: the signal frame's `target_price`, or an order
    /// scenario's.
    Price(Price),
    /// This many ticks above a long's fill price, below a short's.
    TicksFromFill(u32),
    /// This multiple of the plan's initial risk above a long's fill, rounded up (F-RND-02).
    RiskMultiple(ExactDecimal),
}

/// A plan's stop: where it lies, and the id an order scenario gives it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlannedStop {
    /// Where it lies.
    pub at: StopAt,
    /// Its id, as an order scenario names it; a new one otherwise.
    pub id: Option<OrderId>,
}

/// A plan's target: where it lies, the id an order scenario gives it, and the fraction of the
/// lots its earlier targets leave that it closes (F-PLN-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlannedTarget {
    /// Where it lies.
    pub at: TargetAt,
    /// Its id, as an order scenario names it; a new one otherwise.
    pub id: Option<OrderId>,
    /// Its fraction of the lots left, above 0 and at most 1.
    pub fraction: ExactDecimal,
}

/// A point a trade reaches in its favour (F-BRK-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Trigger {
    /// A profit of this many ticks from the fill.
    Ticks(u32),
    /// A profit of this multiple of the initial risk, rounded up (F-RND-01).
    Risk(ExactDecimal),
    /// The fill of this target.
    AfterTarget(TargetNumber),
}

/// Breakeven: when its trigger fires, the stop moves to the fill price plus `offset_ticks`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BreakevenPlan {
    /// What fires it.
    pub trigger: Trigger,
    /// The ticks beyond the fill price in the position's favour; below zero, short of it.
    pub offset_ticks: i64,
}

/// How far behind the best price a trailing stop follows (F-TRL-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrailDistance {
    /// This many ticks.
    Ticks(u32),
    /// `multiple` times the signal rows' feature: `ticks` at the entry row, taken again at each
    /// decision whose row gives the feature.
    Feature {
        /// The multiple of the feature.
        multiple: ExactDecimal,
        /// The distance at the entry row, rounded down (F-RND-01).
        ticks: u32,
    },
    /// At each decision's `trail_ref`.
    Column,
}

/// A trailing stop: its distance, its steps, its activation, and when it moves.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TrailingPlan {
    /// How far behind the best price it follows.
    pub distance: TrailDistance,
    /// The ticks it moves by at a time; without them, any.
    pub step_ticks: Option<u32>,
    /// What activates it; without it, the entry's fill.
    pub activation: Option<Trigger>,
    /// Whether it moves at every price marked or at decisions alone (F-TRL-04).
    pub update: TrailUpdate,
}

/// What an entry carries, placed when it fills (F-PLN-01).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExitPlan {
    /// Its stop.
    pub stop: Option<PlannedStop>,
    /// Its targets, three at most, in order.
    pub targets: Vec<PlannedTarget>,
    /// Its breakeven.
    pub breakeven: Option<BreakevenPlan>,
    /// Its trailing stop.
    pub trailing: Option<TrailingPlan>,
}

impl ExitPlan {
    /// F-ROL-03: the plan with the prices it names, at `stop_price` or `target_price`, moved by a
    /// roll's gap; legs placed from the fill move with it.
    pub(crate) fn shift_by(&mut self, gap: Price) -> Result<(), Overflow> {
        if let Some(PlannedStop {
            at: StopAt::Price(price),
            ..
        }) = &mut self.stop
        {
            *price = price.checked_add(gap)?;
        }
        for target in &mut self.targets {
            if let TargetAt::Price(price) = &mut target.at {
                *price = price.checked_add(gap)?;
            }
        }
        Ok(())
    }
}

impl From<Bracket> for ExitPlan {
    /// A bracket as a plan of one stop and one target for the whole entry, under the bracket's
    /// ids.
    fn from(bracket: Bracket) -> Self {
        let stop = PlannedStop {
            at: match bracket.stop.price {
                LegPrice::At(price) => StopAt::Price(price),
                LegPrice::TicksFromFill(ticks) => StopAt::TicksFromFill(ticks),
            },
            id: bracket.stop.id,
        };
        let target = PlannedTarget {
            at: match bracket.target.price {
                LegPrice::At(price) => TargetAt::Price(price),
                LegPrice::TicksFromFill(ticks) => TargetAt::TicksFromFill(ticks),
            },
            id: bracket.target.id,
            fraction: ExactDecimal::ONE,
        };
        Self {
            stop: Some(stop),
            targets: vec![target],
            breakeven: None,
            trailing: None,
        }
    }
}

/// What an exit plan cannot be worked out from.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum PlanError {
    /// A target in R multiples of a plan without a stop, which the specification refuses.
    #[error("Expected target {target} in R beside a stop (F-RND-02), got a plan without one")]
    RiskWithoutStop {
        /// The target, counted from 1.
        target: u8,
    },
    /// A feature at or below zero, or beyond 64 bits, on the row a rule reads it from.
    #[error(
        "Expected the {rule}'s feature above zero (F-RND-01), got {value} on the signal close of \
         {at}"
    )]
    Feature {
        /// The rule that reads it, such as `trailing stop`.
        rule: &'static str,
        /// The value read.
        value: String,
        /// The row's close.
        at: Ts,
    },
    /// A `trail_ref` off the instrument's tick.
    #[error(
        "Expected trail_ref on the instrument's tick of {tick} (F-RND-01), got {trail_ref} on the \
         signal close of {at}"
    )]
    OffTheTick {
        /// The row's `trail_ref`.
        trail_ref: Price,
        /// The instrument's tick.
        tick: Price,
        /// The row's close.
        at: Ts,
    },
    /// A price or a distance beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
}

/// F-RND-01: `multiple × units ÷ divisor` price units, worked out exactly, as whole ticks of
/// `tick`, at least one: rounded down for a stop and a trailing stop's distance, up for a target
/// and a profit trigger.
pub(crate) fn f_rnd_01(
    multiple: ExactDecimal,
    units: i128,
    divisor: i128,
    tick: Price,
    away_from_entry: bool,
) -> Result<u32, Overflow> {
    let over = divisor.checked_mul(i128::from(tick.0));
    let ticks = over.and_then(|over| match away_from_entry {
        true => multiple.ceil_times(units, over),
        false => multiple.floor_times(units, over),
    });
    let ticks = ticks.and_then(|ticks| u32::try_from(ticks.max(1)).ok());
    ticks.ok_or(Overflow {
        operation: "a distance in whole ticks",
        left: units,
        right: divisor,
    })
}

/// F-RND-02: a plan's initial risk, the ticks from its entry's fill price to its stop's first
/// level, at least one.
pub(crate) fn f_rnd_02(side: Side, fill: Price, stop: Price, tick: Price) -> u32 {
    let distance = i128::from(side.sign()) * (i128::from(fill.0) - i128::from(stop.0));
    let ticks = distance.div_euclid(i128::from(tick.0)).max(1);
    u32::try_from(ticks).unwrap_or(u32::MAX)
}

/// A feature's value, in 1e-9 units of price as one worked out from the bars' prices is, read as
/// the decimal it prints as and cut to whole units (F-RND-01); none at or below zero, or beyond
/// 64 bits.
pub(crate) fn feature_units(value: f64) -> Option<i64> {
    if value.partial_cmp(&0.0) != Some(Ordering::Greater) {
        return None;
    }
    ExactDecimal::of(value)?.truncated()
}

/// `multiple` times a feature of `units` 1e-9 units, in whole ticks (F-RND-01).
pub(crate) fn feature_ticks(
    multiple: ExactDecimal,
    units: i64,
    tick: Price,
    away_from_entry: bool,
) -> Result<u32, Overflow> {
    f_rnd_01(multiple, units.into(), 1, tick, away_from_entry)
}

/// F-PLN-01: each target's lots, its fraction of the lots its earlier targets leave, rounded down
/// to whole lots; a target of no lots is not placed.
pub(crate) fn f_pln_01(lots: Qty, fractions: &[ExactDecimal]) -> Result<Vec<Qty>, Overflow> {
    let mut left = lots.0;
    let mut shares = Vec::with_capacity(fractions.len());
    for fraction in fractions {
        let share = fraction.floor_times(left.into(), 1);
        let share = share.and_then(|share| i64::try_from(share).ok());
        let share = share.ok_or(Overflow {
            operation: "a target's share of the lots",
            left: left.into(),
            right: 1,
        })?;
        shares.push(Qty(share));
        left -= share;
    }
    Ok(shares)
}

/// F-PLN-03: a move of a long's stop, up only and never to or above the market, one tick below
/// it at most; none when it would not raise the stop.
pub(crate) fn f_pln_03(
    side: Side,
    stop: Price,
    proposed: Price,
    market: Price,
    tick: Price,
) -> Result<Option<Price>, Overflow> {
    let ceiling = side.opposite().moved(market, 1, tick)?;
    let level = capped(side, proposed, ceiling);
    Ok((side.better(level, stop) != stop).then_some(level))
}

/// F-BRK-01: breakeven's level, the entry's fill price plus `offset_ticks` ticks in the position's
/// favour, below it for a negative offset.
pub(crate) fn f_brk_01(
    side: Side,
    fill: Price,
    offset_ticks: i64,
    tick: Price,
) -> Result<Price, Overflow> {
    let distance = offset_ticks
        .checked_mul(side.sign())
        .and_then(|ticks| ticks.checked_mul(tick.0));
    let distance = distance.ok_or(Overflow {
        operation: "a breakeven offset",
        left: offset_ticks.into(),
        right: tick.0.into(),
    })?;
    fill.checked_add(Price(distance))
}

/// F-TRL-03: with steps, the stop raised by the whole steps of `step_ticks` ticks that fit between
/// where it stands and `level`; without, `level` itself.
pub(crate) fn f_trl_03(
    side: Side,
    stop: Price,
    level: Price,
    step_ticks: Option<u32>,
    tick: Price,
) -> Result<Price, Overflow> {
    let Some(step_ticks) = step_ticks else {
        return Ok(level);
    };
    let step = i128::from(step_ticks) * i128::from(tick.0);
    let room = i128::from(side.sign()) * (i128::from(level.0) - i128::from(stop.0));
    let steps = u32::try_from(room.div_euclid(step).max(0)).unwrap_or(u32::MAX);
    let step = tick.0.checked_mul(i64::from(step_ticks)).ok_or(Overflow {
        operation: "a trailing stop's step",
        left: tick.0.into(),
        right: step_ticks.into(),
    })?;
    side.moved(stop, steps, Price(step))
}

/// F-TRL-04: whether a trailing stop moves now: `intrabar` at every price marked and at decisions,
/// `bar_close` at decisions alone.
pub(crate) fn f_trl_04(trailing: &TrailingPlan, at_decision: bool) -> bool {
    at_decision || trailing.update == TrailUpdate::Intrabar
}

/// A long's level held to at most `ceiling`, a short's to at least it.
fn capped(side: Side, level: Price, ceiling: Price) -> Price {
    match side {
        Side::Buy => level.min(ceiling),
        Side::Sell => level.max(ceiling),
    }
}
