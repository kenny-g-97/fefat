//! The exit plan an execution template's entry carries, as `fefat.reference.template.exits`
//! builds it (`docs/spec/fill-semantics.md` §22 to §24): its stop, targets, breakeven, and
//! trailing stop from the specification, with the entry row's features and prices worked into
//! whole ticks where the fill does not change them (F-RND-01), and the rest left to the fill
//! (`crate::exit_plan`).

use fefat_core::instants::Ts;
use fefat_core::orders::{Side, TargetNumber};
use fefat_core::strategy_spec::{
    Breakeven, Execution, ProfitTrigger, StopRule, Target, TargetPrice, TrailBy, Trailing,
};
use fefat_core::units::Price;

use super::SignalRow;
use crate::exact_decimal::ExactDecimal;
use crate::exit_plan::{
    BreakevenPlan, ExitPlan, PlannedStop, PlannedTarget, StopAt, TargetAt, TrailDistance,
    TrailingPlan, Trigger, feature_ticks, feature_units,
};
use crate::strategy::DecisionError;

/// The exit plan of an entry on `side` that `row`, the entry row, places (F-PLN-01).
pub(super) fn exit_plan_of(
    execution: &Execution,
    row: &SignalRow,
    side: Side,
    tick: Price,
) -> Result<ExitPlan, DecisionError> {
    let stop = execution.stop.as_ref().map(|stop| stop_of(stop, row, tick));
    let stop = stop.transpose()?;
    let targets = execution.targets.iter().enumerate();
    let targets = targets.map(|(index, target)| target_of(target, index, row, tick));
    let targets = targets.collect::<Result<Vec<_>, _>>()?;
    require_the_stop_below_the_targets(stop, &targets, row, side)?;
    let breakeven = execution
        .breakeven
        .as_ref()
        .map(|rule| breakeven_of(rule, row));
    let trailing = execution.trailing.as_ref();
    let trailing = trailing.map(|trailing| trailing_of(trailing, row, tick));
    Ok(ExitPlan {
        stop,
        targets,
        breakeven: breakeven.transpose()?,
        trailing: trailing.transpose()?,
    })
}

fn stop_of(stop: &StopRule, row: &SignalRow, tick: Price) -> Result<PlannedStop, DecisionError> {
    let at = match stop {
        StopRule::Ticks { ticks } => StopAt::TicksFromFill(*ticks),
        StopRule::Percent { percent } => StopAt::PercentOfFill(exact(*percent, row.ts_close)?),
        StopRule::Atr { multiple, feature } => {
            let units = units_of(row.features.stop, feature, row.ts_close)?;
            let multiple = exact(*multiple, row.ts_close)?;
            StopAt::TicksFromFill(feature_ticks(multiple, units, tick, false)?)
        }
        StopRule::Column {} => {
            StopAt::Price(column_price(row.stop_price, "stop_price", row, tick)?)
        }
    };
    Ok(PlannedStop { at, id: None })
}

fn target_of(
    target: &Target,
    index: usize,
    row: &SignalRow,
    tick: Price,
) -> Result<PlannedTarget, DecisionError> {
    let at = match &target.price {
        TargetPrice::Ticks { ticks } => TargetAt::TicksFromFill(*ticks),
        TargetPrice::Atr { multiple, feature } => {
            let value = row.features.targets.get(index).copied().flatten();
            let units = units_of(value, feature, row.ts_close)?;
            let multiple = exact(*multiple, row.ts_close)?;
            TargetAt::TicksFromFill(feature_ticks(multiple, units, tick, true)?)
        }
        TargetPrice::RMultiple { multiple } => {
            TargetAt::RiskMultiple(exact(*multiple, row.ts_close)?)
        }
        TargetPrice::Column {} => {
            TargetAt::Price(column_price(row.target_price, "target_price", row, tick)?)
        }
    };
    Ok(PlannedTarget {
        at,
        id: None,
        fraction: exact(target.fraction, row.ts_close)?,
    })
}

fn trigger_of(trigger: &ProfitTrigger, at: Ts) -> Result<Trigger, DecisionError> {
    match trigger {
        ProfitTrigger::Ticks { ticks } => Ok(Trigger::Ticks(*ticks)),
        ProfitTrigger::RMultiple { multiple } => Ok(Trigger::Risk(exact(*multiple, at)?)),
        ProfitTrigger::AfterTarget { target } => {
            let number = usize::from(*target).checked_sub(1);
            let number = number.and_then(|index| TargetNumber::ALL.get(index).copied());
            number
                .map(Trigger::AfterTarget)
                .ok_or_else(|| DecisionError::Signal {
                    expected: "an after_target trigger of target 1, 2, or 3".to_owned(),
                    actual: format!("target {target}"),
                    at,
                })
        }
    }
}

fn breakeven_of(breakeven: &Breakeven, row: &SignalRow) -> Result<BreakevenPlan, DecisionError> {
    Ok(BreakevenPlan {
        trigger: trigger_of(&breakeven.trigger, row.ts_close)?,
        offset_ticks: breakeven.offset_ticks,
    })
}

/// The trailing stop's distance at the entry row: its ticks, or its multiple of the row's feature
/// rounded down (F-TRL-02); at each decision's `trail_ref` by the column.
fn trailing_of(
    trailing: &Trailing,
    row: &SignalRow,
    tick: Price,
) -> Result<TrailingPlan, DecisionError> {
    let distance = match &trailing.by {
        TrailBy::Ticks { ticks } => TrailDistance::Ticks(*ticks),
        TrailBy::Atr { multiple, feature } => {
            let multiple = exact(*multiple, row.ts_close)?;
            let units = units_of(row.features.trailing, feature, row.ts_close)?;
            let ticks = feature_ticks(multiple, units, tick, false)?;
            TrailDistance::Feature { multiple, ticks }
        }
        TrailBy::Column {} => TrailDistance::Column,
    };
    let activation = trailing.activation.as_ref();
    let activation = activation.map(|trigger| trigger_of(trigger, row.ts_close));
    Ok(TrailingPlan {
        distance,
        step_ticks: trailing.step_ticks,
        activation: activation.transpose()?,
        update: trailing.update,
    })
}

/// A price the signal frame gives on `row` in `column`, which must be there and on the tick
/// (F-RND-01).
fn column_price(
    price: Option<Price>,
    column: &str,
    row: &SignalRow,
    tick: Price,
) -> Result<Price, DecisionError> {
    let Some(price) = price else {
        return Err(DecisionError::Signal {
            expected: format!("the signal frame's {column} on the entry's bar"),
            actual: "null".to_owned(),
            at: row.ts_close,
        });
    };
    if price.0.rem_euclid(tick.0) != 0 {
        return Err(DecisionError::Signal {
            expected: format!("{column} on the instrument's tick of {tick}"),
            actual: price.to_string(),
            at: row.ts_close,
        });
    }
    Ok(price)
}

/// A stop at `stop_price` lies on the losing side of a target at `target_price`.
fn require_the_stop_below_the_targets(
    stop: Option<PlannedStop>,
    targets: &[PlannedTarget],
    row: &SignalRow,
    side: Side,
) -> Result<(), DecisionError> {
    let Some(PlannedStop {
        at: StopAt::Price(stop),
        ..
    }) = stop
    else {
        return Ok(());
    };
    for target in targets {
        let TargetAt::Price(target) = target.at else {
            continue;
        };
        if side.better(target, stop) == stop {
            let below = if side == Side::Buy { "below" } else { "above" };
            return Err(DecisionError::Signal {
                expected: format!("the stop_price {below} the target_price of a {side} entry"),
                actual: format!("{stop} and {target}"),
                at: row.ts_close,
            });
        }
    }
    Ok(())
}

/// A feature's value on the entry row as whole 1e-9 units (F-RND-01); a feature missing, or at
/// or below zero, is refused.
fn units_of(value: Option<f64>, feature: &str, at: Ts) -> Result<i64, DecisionError> {
    value
        .and_then(feature_units)
        .ok_or_else(|| DecisionError::Signal {
            expected: format!("the feature {feature} above zero"),
            actual: value.map_or_else(|| "null".to_owned(), |value| value.to_string()),
            at,
        })
}

/// A number of the specification as the decimal it prints as (F-RND-01).
fn exact(number: f64, at: Ts) -> Result<ExactDecimal, DecisionError> {
    ExactDecimal::of(number).ok_or_else(|| DecisionError::Signal {
        expected: "a number of the specification that reads as a decimal".to_owned(),
        actual: number.to_string(),
        at,
    })
}
