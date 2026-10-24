//! The strategy specification reads and writes back every rule, refuses unknown fields and kinds,
//! fills in its defaults, and its committed JSON schema is the one its types generate (step 2.3,
//! Done means 1).

use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

use super::{
    Breakeven, Cooldown, EntryOrder, Limits, OppositeSignal, Sizing, StopRule, StrategySpec,
    Target, TimeRules, Trailing, schema, schema_text,
};

const COMMITTED_SCHEMA: &str =
    include_str!("../../../../../python/fefat/src/fefat/strategy/strategy_spec.schema.json");

/// The strategy of `02-engine-and-data.md` §5 as the SDK writes it, every default spelled out.
fn documented_example() -> Value {
    json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "on_opposite_signal": "ignore",
            "stop": {"kind": "atr", "multiple": 1.5, "feature": "atr"},
            "targets": [
                {"price": {"kind": "r_multiple", "multiple": 1.0}, "fraction": 0.5},
                {"price": {"kind": "r_multiple", "multiple": 2.0}, "fraction": 1.0}
            ],
            "breakeven": {"trigger": {"kind": "after_target", "target": 1}, "offset_ticks": 0},
            "time": {
                "tz": "America/Chicago",
                "windows": [{"start": "08:30", "end": "14:30"}],
                "flat_by": "15:05",
                "no_overnight": false,
                "no_weekend": false
            },
            "limits": {"max_trades_per_day": 3, "fresh_signal": false},
            "sizing": {"kind": "fixed", "units": 1.0},
            "signal_exit": true
        }
    })
}

fn reads_and_writes_back<T: Serialize + DeserializeOwned>(documents: &[Value]) {
    for document in documents {
        let read: T = serde_json::from_value(document.clone()).unwrap();
        assert_eq!(serde_json::to_value(&read).unwrap(), *document);
    }
}

fn refused<T: DeserializeOwned>(document: &Value) -> bool {
    serde_json::from_value::<T>(document.clone()).is_err()
}

#[test]
fn the_committed_schema_is_the_one_the_types_generate() {
    assert!(
        schema_text() == COMMITTED_SCHEMA,
        "python/fefat/src/fefat/strategy/strategy_spec.schema.json differs from the schema of \
         the Rust types: run `just gen-schema` and commit the file"
    );
}

#[test]
fn the_schema_is_draft_2020_12_and_never_offers_null() {
    let generated = schema();

    assert_eq!(
        generated.get("$schema"),
        Some(&json!("https://json-schema.org/draft/2020-12/schema"))
    );
    assert_eq!(generated.get("title"), Some(&json!("StrategySpec")));
    assert!(!schema_text().contains("\"null\""));
}

#[test]
fn the_documented_example_reads_and_writes_back() {
    reads_and_writes_back::<StrategySpec>(&[documented_example()]);
}

#[test]
fn every_rule_reads_and_writes_back() {
    reads_and_writes_back::<EntryOrder>(&[
        json!({"kind": "market"}),
        json!({"kind": "limit_at_column", "time_to_live_bars": 3}),
        json!({"kind": "limit_offset", "ticks": 2}),
        json!({"kind": "stop_at_column"}),
        json!({"kind": "stop_offset", "ticks": 4, "time_to_live_bars": 1}),
    ]);
    reads_and_writes_back::<StopRule>(&[
        json!({"kind": "ticks", "ticks": 12}),
        json!({"kind": "percent", "percent": 0.5}),
        json!({"kind": "atr", "multiple": 1.5, "feature": "atr"}),
        json!({"kind": "column"}),
    ]);
    reads_and_writes_back::<Target>(&[
        json!({"price": {"kind": "ticks", "ticks": 24}, "fraction": 1.0}),
        json!({"price": {"kind": "atr", "multiple": 2.0, "feature": "atr"}, "fraction": 0.5}),
        json!({"price": {"kind": "r_multiple", "multiple": 1.5}, "fraction": 0.25}),
        json!({"price": {"kind": "column"}, "fraction": 1.0}),
    ]);
    reads_and_writes_back::<Breakeven>(&[
        json!({"trigger": {"kind": "ticks", "ticks": 8}, "offset_ticks": 1}),
        json!({"trigger": {"kind": "r_multiple", "multiple": 1.0}, "offset_ticks": -1}),
    ]);
    reads_and_writes_back::<Trailing>(&[
        json!({"by": {"kind": "ticks", "ticks": 8}, "update": "intrabar"}),
        json!({
            "by": {"kind": "atr", "multiple": 3.0, "feature": "atr"},
            "step_ticks": 4,
            "activation": {"kind": "ticks", "ticks": 10},
            "update": "bar_close"
        }),
        json!({"by": {"kind": "column"}, "update": "bar_close"}),
    ]);
    reads_and_writes_back::<TimeRules>(&[json!({
        "tz": "UTC",
        "windows": [{"start": "22:00", "end": "02:00", "weekdays": ["monday", "sunday"]}],
        "max_bars": 12,
        "max_minutes": 90,
        "no_overnight": true,
        "no_weekend": true
    })]);
    reads_and_writes_back::<Limits>(&[json!({
        "blackout": "news",
        "max_trades_per_day": 3,
        "max_losses_per_day": 2,
        "daily_loss_stop": 500.0,
        "profit_lock": 1000.0,
        "cooldown_after_loss": {"kind": "bars", "bars": 6},
        "fresh_signal": true
    })]);
    reads_and_writes_back::<Cooldown>(&[json!({"kind": "minutes", "minutes": 30})]);
    reads_and_writes_back::<Sizing>(&[
        json!({"kind": "fixed", "units": 2.0}),
        json!({"kind": "notional", "amount": 25000.0}),
        json!({"kind": "risk_amount", "amount": 250.0}),
        json!({"kind": "risk_percent", "percent": 1.0}),
    ]);
}

#[test]
fn a_minimal_document_takes_the_defaults() {
    let minimal = json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {"entry": {"kind": "market"}, "sizing": {"kind": "fixed", "units": 1.0}}
    });

    let spec: StrategySpec = serde_json::from_value(minimal).unwrap();

    let execution = spec.execution;
    assert_eq!(execution.on_opposite_signal, OppositeSignal::Ignore);
    assert_eq!(
        (execution.stop, execution.breakeven, execution.trailing),
        (None, None, None)
    );
    assert!(execution.targets.is_empty() && execution.time.is_none());
    assert_eq!(execution.limits, Limits::default());
    assert!(execution.signal_exit);
}

#[test]
fn unknown_fields_and_kinds_are_refused() {
    let mut commented = documented_example();
    commented["comment"] = json!("a field no reader knows");

    assert!(refused::<StrategySpec>(&commented));
    assert!(refused::<Target>(
        &json!({"price": {"kind": "column"}, "lots": 2})
    ));
    assert!(refused::<StopRule>(
        &json!({"kind": "ticks", "ticks": 12, "price": 1})
    ));
    assert!(refused::<EntryOrder>(
        &json!({"kind": "market", "price": 1})
    ));
    assert!(refused::<StopRule>(&json!({"kind": "chandelier"})));
    assert!(refused::<OppositeSignal>(&json!("flip")));
}

#[test]
fn time_rules_need_their_time_zone() {
    assert!(refused::<TimeRules>(&json!({"flat_by": "15:05"})));
}
