//! The template's refusals, as `python/tests/test_reference_template.py` holds the reference's: a
//! specification beyond what the template runs so far, until the rest of step 2.8 brings it, and
//! signal rows the template cannot act on; and the exit plans it builds from the entry row.

use fefat_core::instants::Ts;
use fefat_core::instrument::{InstrumentParameters, LotStep};
use fefat_core::orders::Side;
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use serde_json::{Value, json};

use super::exits::exit_plan_of;
use super::{RowFeatures, SignalRow, TemplateError, TemplateStrategy};
use crate::exit_plan::{StopAt, TargetAt, TrailDistance};
use crate::strategy::DecisionError;

fn es() -> InstrumentParameters {
    InstrumentParameters::new(
        Price(250_000_000),
        Money(50 * MONEY_UNITS),
        LotStep(PRICE_UNITS),
    )
    .unwrap()
}

fn price(hundredths: i64) -> Price {
    Price(hundredths * 10_000_000)
}

/// A market entry with a stop of 4 ticks, a target of 8, and one lot, with the execution's keys
/// that `changes` names set to its values, or removed by a null.
fn spec_with(changes: &Value) -> StrategySpec {
    let mut execution = json!({
        "entry": {"kind": "market"},
        "stop": {"kind": "ticks", "ticks": 4},
        "targets": [{"price": {"kind": "ticks", "ticks": 8}}],
        "sizing": {"kind": "fixed", "units": 1}
    });
    for (key, value) in changes.as_object().unwrap() {
        if value.is_null() {
            execution.as_object_mut().unwrap().remove(key);
        } else {
            execution[key] = value.clone();
        }
    }
    let spec =
        json!({"spec_version": 1, "instrument": "ES", "timeframe": "5m", "execution": execution});
    serde_json::from_value(spec).unwrap()
}

/// A long entry at the close `ts_close`.
const fn entry_at(ts_close: i64) -> SignalRow {
    SignalRow {
        long_entry: true,
        ..SignalRow::at(Ts(ts_close))
    }
}

fn refused_row<T: std::fmt::Debug>(decided: Result<T, DecisionError>) -> String {
    match decided {
        Err(DecisionError::Signal { expected, .. }) => expected,
        other => panic!("Expected a refused signal row, got {other:?}"),
    }
}

#[test]
fn a_specification_beyond_the_basic_subset_is_refused_until_step_2_8() {
    let refusals = [
        (
            json!({"entry": {"kind": "limit_offset", "ticks": 2}}),
            "an entry other than market",
        ),
        (
            json!({"on_opposite_signal": "reverse"}),
            "an opposite signal that is not ignored",
        ),
        (
            json!({"limits": {"cooldown_after_loss": {"kind": "bars", "bars": 3}}}),
            "entry limits",
        ),
        (json!({"limits": {"fresh_signal": true}}), "entry limits"),
        (
            json!({"sizing": {"kind": "notional", "amount": 25_000.0}}),
            "a size other than fixed",
        ),
    ];
    for (changes, refused) in refusals {
        let template = TemplateStrategy::new(&spec_with(&changes), vec![entry_at(0)], &es());
        let expected = TemplateError::BeyondTheSubset {
            refused: refused.to_owned(),
        };
        assert_eq!(template.err(), Some(expected), "{changes}");
    }
    assert!(TemplateStrategy::new(&spec_with(&json!({})), vec![entry_at(0)], &es()).is_ok());
}

#[test]
fn every_rule_of_the_exit_plan_runs() {
    // Step 2.3 refused these until step 2.8; S-template-008 to S-template-033 pin their fills.
    let ticks = |ticks: u32| json!({"kind": "ticks", "ticks": ticks});
    let feature = json!({"kind": "atr", "multiple": 2.0, "feature": "atr_14"});
    let exit_plans = [
        json!({"stop": null}),
        json!({"stop": {"kind": "percent", "percent": 0.5}}),
        json!({"stop": feature}),
        json!({"targets": [{"price": ticks(8), "fraction": 0.5}, {"price": ticks(16)}]}),
        json!({"targets": [{"price": ticks(8), "fraction": 0.5}]}),
        json!({"targets": [{"price": feature}]}),
        json!({"targets": [{"price": {"kind": "r_multiple", "multiple": 1.3}}]}),
        json!({"stop": {"kind": "column"}, "targets": [{"price": {"kind": "r_multiple", "multiple": 2.0}}]}),
        json!({"breakeven": {"trigger": ticks(8)}}),
        json!({"trailing": {"by": ticks(8)}}),
        json!({"trailing": {"by": {"kind": "column"}, "update": "bar_close"}}),
    ];
    for changes in exit_plans {
        let template = TemplateStrategy::new(&spec_with(&changes), vec![entry_at(0)], &es());
        assert!(template.is_ok(), "{changes}: {template:?}");
    }
}

#[test]
fn flat_by_takes_its_instant_from_every_signal_row_and_only_with_a_flat_by_time() {
    let flat_by = spec_with(&json!({"time": {"tz": "America/Chicago", "flat_by": "15:05"}}));
    let at_flat_by = SignalRow {
        flat_by: Some(Ts(9)),
        ..entry_at(0)
    };
    let refused =
        |spec: &StrategySpec, row: SignalRow| match TemplateStrategy::new(spec, vec![row], &es()) {
            Err(TemplateError::Refused { expected, .. }) => expected,
            other => panic!("Expected refused signal rows, got {other:?}"),
        };
    assert!(TemplateStrategy::new(&flat_by, vec![at_flat_by], &es()).is_ok());
    assert_eq!(
        refused(&flat_by, entry_at(0)),
        "the instant of the flat-by time 15:05 on every signal row"
    );
    assert_eq!(
        refused(&spec_with(&json!({})), at_flat_by),
        "no flat-by instant on the rows of a specification without flat_by"
    );
}

#[test]
fn signal_rows_out_of_order_or_with_both_entries_on_a_bar_are_refused() {
    let spec = spec_with(&json!({}));
    let both = SignalRow {
        short_entry: true,
        ..entry_at(0)
    };
    let refused = |rows: Vec<SignalRow>| match TemplateStrategy::new(&spec, rows, &es()) {
        Err(TemplateError::Refused { expected, .. }) => expected,
        other => panic!("Expected refused signal rows, got {other:?}"),
    };
    assert!(refused(vec![both]).starts_with("one of long_entry and short_entry per bar"));
    assert!(refused(vec![entry_at(5), entry_at(5)]).starts_with("signal rows in ascending order"));
}

#[test]
fn a_row_whose_size_or_column_prices_the_template_cannot_act_on_is_refused() {
    let fixed = TemplateStrategy::new(&spec_with(&json!({})), vec![entry_at(0)], &es()).unwrap();
    let doubled = SignalRow {
        size_mult: Some(2.0),
        ..entry_at(0)
    };
    assert_eq!(fixed.lots_at(&doubled), Ok(Qty(2)));
    let a_lot_and_a_half = SignalRow {
        size_mult: Some(1.5),
        ..entry_at(0)
    };
    let refused = refused_row(fixed.lots_at(&a_lot_and_a_half));
    assert!(
        refused.starts_with("a size_mult that makes whole lots"),
        "{refused}"
    );

    let column = json!({"kind": "column"});
    let at_columns = spec_with(&json!({"stop": column, "targets": [{"price": column}]}));
    let execution = &at_columns.execution;
    let tick = es().tick_size();
    let with_prices = |stop: i64, target: i64| SignalRow {
        stop_price: Some(price(stop)),
        target_price: Some(price(target)),
        ..entry_at(0)
    };
    let plan = |row: &SignalRow| exit_plan_of(execution, row, Side::Buy, tick);
    assert!(plan(&with_prices(499_000, 501_000)).is_ok());
    let off_the_tick = refused_row(plan(&with_prices(499_710, 501_000)));
    assert!(
        off_the_tick.starts_with("stop_price on the instrument's tick"),
        "{off_the_tick}"
    );
    let swapped = refused_row(plan(&with_prices(501_000, 499_000)));
    assert!(
        swapped.starts_with("the stop_price below the target_price"),
        "{swapped}"
    );
    let missing = refused_row(plan(&entry_at(0)));
    assert!(
        missing.starts_with("the signal frame's stop_price"),
        "{missing}"
    );
}

#[test]
fn an_entry_rows_features_become_whole_ticks_rounded_toward_the_entry_for_stops() {
    // F-RND-01, S-template-014: 1.3 points is 5.2 ticks; a stop of 2 ATR rounds 10.4 down to
    // 10 ticks, a target of 2 ATR up to 11, and a trailing stop of 2 ATR down to 10.
    let feature = json!({"kind": "atr", "multiple": 2.0, "feature": "atr"});
    let spec = spec_with(&json!({
        "stop": feature,
        "targets": [{"price": feature}],
        "trailing": {"by": feature},
    }));
    let atr = Some(1.3);
    let row = SignalRow {
        features: RowFeatures {
            stop: atr,
            targets: [atr, None, None],
            trailing: atr,
        },
        ..entry_at(0)
    };
    let tick = es().tick_size();
    let plan = exit_plan_of(&spec.execution, &row, Side::Buy, tick).unwrap();
    assert_eq!(
        plan.stop.map(|stop| stop.at),
        Some(StopAt::TicksFromFill(10))
    );
    let targets: Vec<TargetAt> = plan.targets.iter().map(|target| target.at).collect();
    assert_eq!(targets, [TargetAt::TicksFromFill(11)]);
    let trailing = plan.trailing.map(|trailing| trailing.distance);
    assert!(matches!(
        trailing,
        Some(TrailDistance::Feature { ticks: 10, .. })
    ));

    let at_zero = SignalRow {
        features: RowFeatures {
            stop: Some(0.0),
            ..row.features
        },
        ..row
    };
    let refused = refused_row(exit_plan_of(&spec.execution, &at_zero, Side::Buy, tick));
    assert_eq!(refused, "the feature atr above zero");
}

#[test]
fn a_time_rule_needs_its_column_on_every_signal_row() {
    // F-TIM-03, F-TIM-04: the flags come from `fefat.reference.time_rules`, which writes them on
    // every row; a batch without them would run as if no stop of trading came.
    let refused = |time: Value, row: SignalRow| {
        let spec = spec_with(&json!({ "time": time }));
        match TemplateStrategy::new(&spec, vec![row], &es()) {
            Err(TemplateError::Refused { expected, .. }) => expected,
            other => panic!("Expected refused signal rows, got {other:?}"),
        }
    };
    let overnight = json!({"tz": "America/Chicago", "no_overnight": true});
    assert_eq!(
        refused(overnight.clone(), entry_at(0)),
        "the session_end of every signal row for its time rule"
    );
    let windows = json!({"tz": "UTC", "windows": [{"start": "08:30", "end": "09:00"}]});
    assert_eq!(
        refused(windows, entry_at(0)),
        "the in_window of every signal row for its time rule"
    );
    let flagged = SignalRow {
        session_end: Some(false),
        ..entry_at(0)
    };
    let spec = spec_with(&json!({ "time": overnight }));
    assert!(TemplateStrategy::new(&spec, vec![flagged], &es()).is_ok());
}
