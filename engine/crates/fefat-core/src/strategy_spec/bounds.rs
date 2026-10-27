//! The bounds a strategy specification's JSON schema states and serde does not check: the counts,
//! distances, multiples, fractions, sizes, and names of its execution template; and the rules
//! that need another, which no schema states (`docs/spec/fill-semantics.md` F-RND-02, F-TRL-04).
//! The version, the root, the timeframe, the time zone, and the local times are types of their
//! own (`values`), which refuse what the schema refuses when a document is read. The engine holds
//! a document to the rest where it first reads specs (BACKLOG.md, step 2.6), so that Rust refuses
//! what the SDK's models refuse.

use std::fmt::Display;

use thiserror::Error;

use super::{
    Cooldown, EntryOrder, Execution, Limits, ProfitTrigger, Sizing, StopRule, StrategySpec, Target,
    TargetPrice, TimeRules, TrailBy, TrailUpdate, Trailing,
};

/// A value of a strategy specification outside the bounds its schema states.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("Expected {field} {expected}, got {actual}")]
pub struct OutOfBounds {
    /// Where in the document, such as `execution.stop.ticks`.
    pub field: String,
    /// The bound, such as `of 1 or more`.
    pub expected: &'static str,
    /// The value given.
    pub actual: String,
}

impl OutOfBounds {
    pub(super) fn new(
        field: impl Into<String>,
        expected: &'static str,
        actual: impl Display,
    ) -> Self {
        Self {
            field: field.into(),
            expected,
            actual: actual.to_string(),
        }
    }
}

impl StrategySpec {
    /// Refuses a document outside the bounds its JSON schema states, or with a rule that needs
    /// another it lacks.
    pub fn validate(&self) -> Result<(), OutOfBounds> {
        execution_bounds(&self.execution)?;
        require_what_each_rule_needs(&self.execution)
    }
}

/// Breakeven and a trailing stop move a stop, so they need one; R multiples and a risk size
/// count in the stop's distance (F-RND-02); `after_target` names a target the specification has;
/// and a trailing stop by the column moves at decisions alone (F-TRL-04).
fn require_what_each_rule_needs(execution: &Execution) -> Result<(), OutOfBounds> {
    let no_stop = execution.stop.is_none();
    let needs_a_stop = [
        ("execution.breakeven", execution.breakeven.is_some()),
        ("execution.trailing", execution.trailing.is_some()),
        ("execution.targets", execution.targets.iter().any(in_r)),
        (
            "execution.breakeven.trigger",
            breakeven_trigger(execution).is_some_and(counts_in_r),
        ),
        (
            "execution.trailing.activation",
            activation(execution).is_some_and(counts_in_r),
        ),
        ("execution.sizing", is_risk(&execution.sizing)),
    ];
    if let Some((field, _)) = needs_a_stop.iter().find(|(_, needs)| no_stop && *needs) {
        return Err(out(*field, "beside a stop", "none"));
    }
    let triggers = [
        (
            "execution.breakeven.trigger.target",
            breakeven_trigger(execution),
        ),
        (
            "execution.trailing.activation.target",
            activation(execution),
        ),
    ];
    for (field, trigger) in triggers {
        if let Some(ProfitTrigger::AfterTarget { target }) = trigger
            && usize::from(*target) > execution.targets.len()
        {
            let actual = format!("target {target} of {}", execution.targets.len());
            return Err(out(field, "a target the specification has", actual));
        }
    }
    match &execution.trailing {
        Some(trailing)
            if matches!(trailing.by, TrailBy::Column {})
                && trailing.update != TrailUpdate::BarClose =>
        {
            Err(out(
                "execution.trailing.update",
                "bar_close for a trailing stop by the column",
                "intrabar",
            ))
        }
        _ => Ok(()),
    }
}

fn breakeven_trigger(execution: &Execution) -> Option<&ProfitTrigger> {
    execution
        .breakeven
        .as_ref()
        .map(|breakeven| &breakeven.trigger)
}

fn activation(execution: &Execution) -> Option<&ProfitTrigger> {
    execution.trailing.as_ref()?.activation.as_ref()
}

fn in_r(target: &Target) -> bool {
    matches!(target.price, TargetPrice::RMultiple { .. })
}

fn counts_in_r(trigger: &ProfitTrigger) -> bool {
    matches!(trigger, ProfitTrigger::RMultiple { .. })
}

const fn is_risk(sizing: &Sizing) -> bool {
    matches!(
        sizing,
        Sizing::RiskAmount { .. } | Sizing::RiskPercent { .. }
    )
}

fn execution_bounds(execution: &Execution) -> Result<(), OutOfBounds> {
    entry_bounds(&execution.entry)?;
    if let Some(stop) = &execution.stop {
        stop_bounds(stop)?;
    }
    if execution.targets.len() > 3 {
        let targets = execution.targets.len();
        return Err(out("execution.targets", "of 3 targets at most", targets));
    }
    for (index, target) in execution.targets.iter().enumerate() {
        target_bounds(&format!("execution.targets[{index}]"), target)?;
    }
    if let Some(breakeven) = &execution.breakeven {
        trigger_bounds("execution.breakeven.trigger", &breakeven.trigger)?;
    }
    if let Some(trailing) = &execution.trailing {
        trailing_bounds(trailing)?;
    }
    if let Some(time) = &execution.time {
        time_bounds(time)?;
    }
    limits_bounds(&execution.limits)?;
    sizing_bounds(&execution.sizing)
}

fn entry_bounds(entry: &EntryOrder) -> Result<(), OutOfBounds> {
    let time_to_live = match entry {
        EntryOrder::Market {} => None,
        EntryOrder::LimitAtColumn { time_to_live_bars }
        | EntryOrder::StopAtColumn { time_to_live_bars }
        | EntryOrder::LimitOffset {
            time_to_live_bars, ..
        }
        | EntryOrder::StopOffset {
            time_to_live_bars, ..
        } => *time_to_live_bars,
    };
    optional_count("execution.entry.time_to_live_bars", time_to_live)
}

fn stop_bounds(stop: &StopRule) -> Result<(), OutOfBounds> {
    match stop {
        StopRule::Ticks { ticks } => at_least_one("execution.stop.ticks", *ticks),
        StopRule::Percent { percent } => above_zero("execution.stop.percent", *percent),
        StopRule::Atr { multiple, feature } => feature_bounds("execution.stop", *multiple, feature),
        StopRule::Column {} => Ok(()),
    }
}

fn target_bounds(field: &str, target: &Target) -> Result<(), OutOfBounds> {
    if !(target.fraction > 0.0 && target.fraction <= 1.0) {
        let field = format!("{field}.fraction");
        return Err(out(field, "above 0 and at most 1", target.fraction));
    }
    match &target.price {
        TargetPrice::Ticks { ticks } => at_least_one(&format!("{field}.price.ticks"), *ticks),
        TargetPrice::Atr { multiple, feature } => {
            feature_bounds(&format!("{field}.price"), *multiple, feature)
        }
        TargetPrice::RMultiple { multiple } => {
            above_zero(&format!("{field}.price.multiple"), *multiple)
        }
        TargetPrice::Column {} => Ok(()),
    }
}

fn trigger_bounds(field: &str, trigger: &ProfitTrigger) -> Result<(), OutOfBounds> {
    match trigger {
        ProfitTrigger::Ticks { ticks } => at_least_one(&format!("{field}.ticks"), *ticks),
        ProfitTrigger::RMultiple { multiple } => {
            above_zero(&format!("{field}.multiple"), *multiple)
        }
        ProfitTrigger::AfterTarget { target } if (1..=3).contains(target) => Ok(()),
        ProfitTrigger::AfterTarget { target } => {
            Err(out(format!("{field}.target"), "from 1 to 3", target))
        }
    }
}

fn trailing_bounds(trailing: &Trailing) -> Result<(), OutOfBounds> {
    match &trailing.by {
        TrailBy::Ticks { ticks } => at_least_one("execution.trailing.by.ticks", *ticks)?,
        TrailBy::Atr { multiple, feature } => {
            feature_bounds("execution.trailing.by", *multiple, feature)?;
        }
        TrailBy::Column {} => {}
    }
    optional_count("execution.trailing.step_ticks", trailing.step_ticks)?;
    match &trailing.activation {
        Some(activation) => trigger_bounds("execution.trailing.activation", activation),
        None => Ok(()),
    }
}

fn time_bounds(time: &TimeRules) -> Result<(), OutOfBounds> {
    for (index, window) in time.windows.iter().enumerate() {
        if window.weekdays.as_ref().is_some_and(Vec::is_empty) {
            return Err(out(
                format!("execution.time.windows[{index}].weekdays"),
                "of one day or more",
                "none",
            ));
        }
    }
    optional_count("execution.time.max_bars", time.max_bars)?;
    optional_count("execution.time.max_minutes", time.max_minutes)
}

fn limits_bounds(limits: &Limits) -> Result<(), OutOfBounds> {
    if let Some(blackout) = &limits.blackout {
        not_empty("execution.limits.blackout", blackout)?;
    }
    let per_day = [
        ("max_trades_per_day", limits.max_trades_per_day),
        ("max_losses_per_day", limits.max_losses_per_day),
    ];
    for (name, count) in per_day {
        optional_count(&format!("execution.limits.{name}"), count)?;
    }
    let amounts = [
        ("daily_loss_stop", limits.daily_loss_stop),
        ("profit_lock", limits.profit_lock),
    ];
    for (name, amount) in amounts {
        if let Some(amount) = amount {
            above_zero(&format!("execution.limits.{name}"), amount)?;
        }
    }
    match limits.cooldown_after_loss {
        Some(Cooldown::Bars { bars }) => {
            at_least_one("execution.limits.cooldown_after_loss.bars", bars)
        }
        Some(Cooldown::Minutes { minutes }) => {
            at_least_one("execution.limits.cooldown_after_loss.minutes", minutes)
        }
        None => Ok(()),
    }
}

fn sizing_bounds(sizing: &Sizing) -> Result<(), OutOfBounds> {
    let (field, value) = match *sizing {
        Sizing::Fixed { units } => ("execution.sizing.units", units),
        Sizing::Notional { amount } | Sizing::RiskAmount { amount } => {
            ("execution.sizing.amount", amount)
        }
        Sizing::RiskPercent { percent } => ("execution.sizing.percent", percent),
    };
    above_zero(field, value)
}

fn feature_bounds(field: &str, multiple: f64, feature: &str) -> Result<(), OutOfBounds> {
    above_zero(&format!("{field}.multiple"), multiple)?;
    not_empty(&format!("{field}.feature"), feature)
}

fn optional_count(field: &str, count: Option<u32>) -> Result<(), OutOfBounds> {
    count.map_or(Ok(()), |count| at_least_one(field, count))
}

fn at_least_one(field: &str, count: u32) -> Result<(), OutOfBounds> {
    if count >= 1 {
        return Ok(());
    }
    Err(out(field, "of 1 or more", count))
}

/// Above zero, which NaN is not.
fn above_zero(field: &str, value: f64) -> Result<(), OutOfBounds> {
    if value > 0.0 {
        return Ok(());
    }
    Err(out(field, "above 0", value))
}

fn not_empty(field: &str, text: &str) -> Result<(), OutOfBounds> {
    if !text.is_empty() {
        return Ok(());
    }
    Err(out(field, "of one character or more", "an empty text"))
}

fn out(field: impl Into<String>, expected: &'static str, actual: impl Display) -> OutOfBounds {
    OutOfBounds::new(field, expected, actual)
}

#[cfg(test)]
mod tests {
    use serde_json::{Value, json};

    use super::*;

    /// A document that uses every bounded field, each within its bounds.
    fn within_bounds() -> Value {
        json!({
            "spec_version": 1,
            "instrument": "ES",
            "timeframe": "5m",
            "execution": {
                "entry": {"kind": "limit_offset", "ticks": 2, "time_to_live_bars": 3},
                "stop": {"kind": "ticks", "ticks": 12},
                "targets": [
                    {"price": {"kind": "ticks", "ticks": 8}, "fraction": 0.5},
                    {"price": {"kind": "r_multiple", "multiple": 2.0}, "fraction": 0.5},
                    {"price": {"kind": "atr", "multiple": 3.0, "feature": "atr"}}
                ],
                "breakeven": {"trigger": {"kind": "after_target", "target": 1}},
                "trailing": {
                    "by": {"kind": "ticks", "ticks": 4},
                    "step_ticks": 1,
                    "activation": {"kind": "r_multiple", "multiple": 1.0}
                },
                "time": {
                    "tz": "America/Chicago",
                    "windows": [{"start": "08:30", "end": "23:59", "weekdays": ["monday"]}],
                    "flat_by": "15:05",
                    "max_bars": 10,
                    "max_minutes": 60
                },
                "limits": {
                    "blackout": "news",
                    "max_trades_per_day": 3,
                    "max_losses_per_day": 2,
                    "daily_loss_stop": 500.0,
                    "profit_lock": 1000.0,
                    "cooldown_after_loss": {"kind": "bars", "bars": 2}
                },
                "sizing": {"kind": "fixed", "units": 1.0}
            }
        })
    }

    fn refused_field(pointer: &str, value: Value) -> String {
        let mut document = within_bounds();
        *document.pointer_mut(pointer).unwrap() = value;
        let spec: StrategySpec = serde_json::from_value(document).unwrap();
        spec.validate().unwrap_err().field
    }

    #[test]
    fn a_document_within_its_bounds_passes() {
        let spec: StrategySpec = serde_json::from_value(within_bounds()).unwrap();
        assert_eq!(spec.validate(), Ok(()));
    }

    #[test]
    fn each_value_outside_its_schemas_bound_is_refused_by_name() {
        let four_targets = Value::Array(vec![json!({"price": {"kind": "column"}}); 4]);
        #[rustfmt::skip]
        let refusals = [
            ("/execution/entry/time_to_live_bars", json!(0), "execution.entry.time_to_live_bars"),
            ("/execution/stop", json!({"kind": "ticks", "ticks": 0}), "execution.stop.ticks"),
            ("/execution/stop", json!({"kind": "percent", "percent": 0.0}), "execution.stop.percent"),
            ("/execution/stop", json!({"kind": "atr", "multiple": -1.0, "feature": "atr"}), "execution.stop.multiple"),
            ("/execution/stop", json!({"kind": "atr", "multiple": 1.0, "feature": ""}), "execution.stop.feature"),
            ("/execution/targets", four_targets, "execution.targets"),
            ("/execution/targets/0/fraction", json!(0.0), "execution.targets[0].fraction"),
            ("/execution/targets/0/fraction", json!(1.5), "execution.targets[0].fraction"),
            ("/execution/targets/0/price", json!({"kind": "ticks", "ticks": 0}), "execution.targets[0].price.ticks"),
            ("/execution/targets/1/price/multiple", json!(0.0), "execution.targets[1].price.multiple"),
            ("/execution/targets/2/price/feature", json!(""), "execution.targets[2].price.feature"),
            ("/execution/breakeven/trigger/target", json!(4), "execution.breakeven.trigger.target"),
            ("/execution/breakeven/trigger", json!({"kind": "ticks", "ticks": 0}), "execution.breakeven.trigger.ticks"),
            ("/execution/trailing/by/ticks", json!(0), "execution.trailing.by.ticks"),
            ("/execution/trailing/step_ticks", json!(0), "execution.trailing.step_ticks"),
            ("/execution/trailing/activation/multiple", json!(-2.0), "execution.trailing.activation.multiple"),
            ("/execution/time/windows/0/weekdays", json!([]), "execution.time.windows[0].weekdays"),
            ("/execution/time/max_bars", json!(0), "execution.time.max_bars"),
            ("/execution/time/max_minutes", json!(0), "execution.time.max_minutes"),
            ("/execution/limits/blackout", json!(""), "execution.limits.blackout"),
            ("/execution/limits/max_trades_per_day", json!(0), "execution.limits.max_trades_per_day"),
            ("/execution/limits/max_losses_per_day", json!(0), "execution.limits.max_losses_per_day"),
            ("/execution/limits/daily_loss_stop", json!(0.0), "execution.limits.daily_loss_stop"),
            ("/execution/limits/profit_lock", json!(-5.0), "execution.limits.profit_lock"),
            ("/execution/limits/cooldown_after_loss/bars", json!(0), "execution.limits.cooldown_after_loss.bars"),
            ("/execution/limits/cooldown_after_loss", json!({"kind": "minutes", "minutes": 0}), "execution.limits.cooldown_after_loss.minutes"),
            ("/execution/sizing/units", json!(0.0), "execution.sizing.units"),
            ("/execution/sizing", json!({"kind": "notional", "amount": -1.0}), "execution.sizing.amount"),
            ("/execution/sizing", json!({"kind": "risk_percent", "percent": 0.0}), "execution.sizing.percent"),
        ];
        for (pointer, value, field) in refusals {
            assert_eq!(refused_field(pointer, value), field, "{pointer}");
        }
    }

    #[test]
    fn a_refusal_names_the_field_the_bound_and_the_value() {
        let mut document = within_bounds();
        *document.pointer_mut("/execution/stop/ticks").unwrap() = json!(0);
        let spec: StrategySpec = serde_json::from_value(document).unwrap();
        assert_eq!(
            spec.validate().unwrap_err().to_string(),
            "Expected execution.stop.ticks of 1 or more, got 0"
        );
    }

    #[test]
    fn a_value_its_type_refuses_is_refused_when_the_document_is_read() {
        #[rustfmt::skip]
        let refusals = [
            ("/spec_version", json!(2), "Expected spec_version 1, got 2"),
            ("/instrument", json!(""), "Expected instrument of one character or more, got an empty text"),
            ("/timeframe", json!("05m"), "Expected a bar timeframe such as 1s, 5m, 1h, or 1d, got \"05m\""),
            ("/timeframe", json!("5w"), "got \"5w\""),
            ("/execution/time/tz", json!(""), "Expected execution.time.tz of one character or more"),
            ("/execution/time/windows/0/start", json!("24:00"), "Expected a local time HH:MM from 00:00 to 23:59, got 24:00"),
            ("/execution/time/windows/0/end", json!("8:30"), "got 8:30"),
            ("/execution/time/flat_by", json!("15:60"), "got 15:60"),
        ];
        for (pointer, value, message) in refusals {
            let mut document = within_bounds();
            *document.pointer_mut(pointer).unwrap() = value;
            let refused = serde_json::from_value::<StrategySpec>(document).unwrap_err();
            assert!(
                refused.to_string().contains(message),
                "{pointer}: {refused}"
            );
        }
    }

    #[test]
    fn a_rule_without_the_rule_it_needs_is_refused_by_name() {
        let without_stop = |change: Value| {
            let mut document = within_bounds();
            let execution = document["execution"].as_object_mut().unwrap();
            execution.remove("stop");
            execution.remove("breakeven");
            execution.remove("trailing");
            execution.insert("targets".to_owned(), json!([]));
            for (key, value) in change.as_object().unwrap() {
                execution.insert(key.clone(), value.clone());
            }
            let spec: StrategySpec = serde_json::from_value(document).unwrap();
            spec.validate().map_err(|refused| refused.to_string())
        };
        #[rustfmt::skip]
        let refusals = [
            (json!({"breakeven": {"trigger": {"kind": "ticks", "ticks": 4}}}), "Expected execution.breakeven beside a stop, got none"),
            (json!({"trailing": {"by": {"kind": "ticks", "ticks": 4}}}), "Expected execution.trailing beside a stop, got none"),
            (json!({"targets": [{"price": {"kind": "r_multiple", "multiple": 2.0}}]}), "Expected execution.targets beside a stop, got none"),
            (json!({"sizing": {"kind": "risk_amount", "amount": 250.0}}), "Expected execution.sizing beside a stop, got none"),
            (json!({"sizing": {"kind": "risk_percent", "percent": 1.0}}), "Expected execution.sizing beside a stop, got none"),
        ];
        for (change, message) in refusals {
            assert_eq!(
                without_stop(change.clone()),
                Err(message.to_owned()),
                "{change}"
            );
        }
        assert_eq!(
            without_stop(json!({"targets": [{"price": {"kind": "ticks", "ticks": 4}}]})),
            Ok(())
        );

        let mut document = within_bounds();
        document["execution"]["targets"] = json!([{"price": {"kind": "ticks", "ticks": 8}}]);
        document["execution"]["breakeven"]["trigger"]["target"] = json!(2);
        let spec: StrategySpec = serde_json::from_value(document).unwrap();
        assert_eq!(
            spec.validate().unwrap_err().to_string(),
            "Expected execution.breakeven.trigger.target a target the specification has, got \
             target 2 of 1"
        );

        let mut document = within_bounds();
        document["execution"]["trailing"]["by"] = json!({"kind": "column"});
        let spec: StrategySpec = serde_json::from_value(document.clone()).unwrap();
        assert_eq!(
            spec.validate().unwrap_err().field,
            "execution.trailing.update"
        );
        document["execution"]["trailing"]["update"] = json!("bar_close");
        let spec: StrategySpec = serde_json::from_value(document).unwrap();
        assert_eq!(spec.validate(), Ok(()));
    }
}
