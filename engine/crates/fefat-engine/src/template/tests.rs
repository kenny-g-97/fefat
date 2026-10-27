//! The template's refusals, as `python/tests/test_reference_template.py` holds the reference's: a
//! specification beyond the basic subset until step 2.8 brings the rest, and signal rows the
//! template cannot act on.

use fefat_core::instants::Ts;
use fefat_core::instrument::{InstrumentParameters, LotStep};
use fefat_core::orders::Side;
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use serde_json::{Value, json};

use super::{SignalRow, TemplateError, TemplateStrategy};
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

/// The basic subset, a market entry with a stop of 4 ticks, a target of 8, and one lot, with
/// the execution's keys that `changes` names set to its values, or removed by a null.
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
        ts_close: Ts(ts_close),
        long_entry: true,
        short_entry: false,
        long_exit: false,
        short_exit: false,
        stop_price: None,
        target_price: None,
        size_mult: None,
        wake: true,
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
    let ticks = |ticks: u32| json!({"kind": "ticks", "ticks": ticks});
    let one_target = |price: Value| json!([{"price": price}]);
    let feature = json!({"kind": "atr", "multiple": 2.0, "feature": "atr_14"});
    let refusals = [
        (
            json!({"entry": {"kind": "limit_offset", "ticks": 2}}),
            "an entry other than market",
        ),
        (
            json!({"on_opposite_signal": "reverse"}),
            "an opposite signal that is not ignored",
        ),
        (json!({"stop": null}), "no stop"),
        (
            json!({"stop": {"kind": "percent", "percent": 0.5}}),
            "a stop other than ticks or the stop_price column",
        ),
        (
            json!({"stop": feature}),
            "a stop other than ticks or the stop_price column",
        ),
        (
            json!({"targets": [{"price": ticks(8), "fraction": 0.5}, {"price": ticks(16), "fraction": 0.5}]}),
            "other than one target",
        ),
        (
            json!({"targets": [{"price": ticks(8), "fraction": 0.5}]}),
            "a target closing part of the position",
        ),
        (
            json!({"targets": one_target(feature.clone())}),
            "a target at a multiple of a feature",
        ),
        (
            json!({"targets": one_target(json!({"kind": "r_multiple", "multiple": 1.3}))}),
            "an R multiple of 1.3 times 4 ticks, off the tick",
        ),
        (
            json!({"stop": {"kind": "column"}, "targets": one_target(json!({"kind": "r_multiple", "multiple": 2.0}))}),
            "an R multiple without a stop in ticks",
        ),
        (json!({"breakeven": {"trigger": ticks(8)}}), "breakeven"),
        (json!({"trailing": {"by": ticks(8)}}), "a trailing stop"),
        (
            json!({"time": {"tz": "UTC", "flat_by": "15:05"}}),
            "time rules",
        ),
        (
            json!({"time": {"tz": "UTC", "windows": [{"start": "08:30", "end": "14:30"}]}}),
            "time rules",
        ),
        (json!({"time": {"tz": "UTC", "max_bars": 12}}), "time rules"),
        (
            json!({"time": {"tz": "UTC", "max_minutes": 60}}),
            "time rules",
        ),
        (
            json!({"time": {"tz": "UTC", "no_overnight": true}}),
            "time rules",
        ),
        (
            json!({"time": {"tz": "UTC", "no_weekend": true}}),
            "time rules",
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
    let at_columns = TemplateStrategy::new(&at_columns, vec![entry_at(0)], &es()).unwrap();
    let with_prices = |stop: i64, target: i64| SignalRow {
        stop_price: Some(price(stop)),
        target_price: Some(price(target)),
        ..entry_at(0)
    };
    assert!(
        at_columns
            .bracket(&with_prices(499_000, 501_000), Side::Buy)
            .is_ok()
    );
    let off_the_tick = refused_row(at_columns.bracket(&with_prices(499_710, 501_000), Side::Buy));
    assert!(
        off_the_tick.starts_with("stop_price on the instrument's tick"),
        "{off_the_tick}"
    );
    let swapped = refused_row(at_columns.bracket(&with_prices(501_000, 499_000), Side::Buy));
    assert!(
        swapped.starts_with("the stop_price below the target_price"),
        "{swapped}"
    );
    let missing = refused_row(at_columns.bracket(&entry_at(0), Side::Buy));
    assert!(
        missing.starts_with("the signal frame's stop_price"),
        "{missing}"
    );
}
