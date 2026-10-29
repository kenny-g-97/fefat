//! The table hash's invariances, the signal rows' two forms of a trade date, and the config's
//! JSON read and written alike.

use std::sync::Arc;

use arrow_array::{
    ArrayRef, BooleanArray, Date32Array, Float64Array, Int32Array, Int64Array, LargeStringArray,
    RecordBatch, StringArray, StringViewArray, StructArray,
};
use arrow_schema::{DataType, Field, Fields, Schema};
use fefat_core::instants::{TradeDate, Ts};

use crate::config::RunConfig;
use crate::signal_rows::signal_rows_of;
use crate::table_hash::{TableHashError, table_hash};

fn table(columns: Vec<(&str, ArrayRef)>) -> RecordBatch {
    let fields: Vec<Field> = columns
        .iter()
        .map(|(name, column)| Field::new(*name, column.data_type().clone(), true))
        .collect();
    let arrays = columns.into_iter().map(|(_, column)| column).collect();
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays).unwrap()
}

fn hashed(batches: &[RecordBatch]) -> String {
    table_hash(&batches[0].schema(), batches).unwrap()
}

fn closes() -> RecordBatch {
    table(vec![
        ("ts_close", Arc::new(Int64Array::from(vec![1, 2, 3]))),
        ("contract", Arc::new(StringArray::from(vec!["ESH2026"; 3]))),
        (
            "atr",
            Arc::new(Float64Array::from(vec![Some(1.5), None, Some(2.0)])),
        ),
    ])
}

#[test]
fn a_table_hashes_alike_however_its_rows_are_split_into_batches() {
    let whole = closes();
    let split = [whole.slice(0, 1), whole.slice(1, 2)];

    assert_eq!(hashed(&split), hashed(std::slice::from_ref(&whole)));
    assert_eq!(hashed(&[whole]).len(), 64);
}

#[test]
fn a_value_a_null_a_column_order_or_a_type_changes_the_hash() {
    let one = hashed(&[closes()]);
    let same_rows = closes().slice(0, 3);
    let other_value = table(vec![
        ("ts_close", Arc::new(Int64Array::from(vec![1, 2, 4]))),
        ("contract", Arc::new(StringArray::from(vec!["ESH2026"; 3]))),
        (
            "atr",
            Arc::new(Float64Array::from(vec![Some(1.5), None, Some(2.0)])),
        ),
    ]);
    let null_for_a_value = table(vec![
        ("ts_close", Arc::new(Int64Array::from(vec![1, 2, 3]))),
        ("contract", Arc::new(StringArray::from(vec!["ESH2026"; 3]))),
        (
            "atr",
            Arc::new(Float64Array::from(vec![Some(1.5), Some(0.0), Some(2.0)])),
        ),
    ]);
    let reordered = table(vec![
        ("contract", Arc::new(StringArray::from(vec!["ESH2026"; 3]))),
        ("ts_close", Arc::new(Int64Array::from(vec![1, 2, 3]))),
        (
            "atr",
            Arc::new(Float64Array::from(vec![Some(1.5), None, Some(2.0)])),
        ),
    ]);
    let narrower = table(vec![
        ("ts_close", Arc::new(Int32Array::from(vec![1, 2, 3]))),
        ("contract", Arc::new(StringArray::from(vec!["ESH2026"; 3]))),
        (
            "atr",
            Arc::new(Float64Array::from(vec![Some(1.5), None, Some(2.0)])),
        ),
    ]);

    assert_eq!(hashed(&[same_rows]), one);
    for other in [other_value, null_for_a_value, reordered, narrower] {
        assert_ne!(hashed(&[other]), one);
    }
}

#[test]
fn text_hashes_alike_in_each_of_arrows_layouts() {
    let words = ["ESH2026", "ESM2026"];
    let layouts: [ArrayRef; 3] = [
        Arc::new(StringArray::from(words.to_vec())),
        Arc::new(LargeStringArray::from(words.to_vec())),
        Arc::new(StringViewArray::from(words.to_vec())),
    ];
    let hashes: Vec<String> = layouts
        .into_iter()
        .map(|column| hashed(&[table(vec![("contract", column)])]))
        .collect();

    assert_eq!(hashes[0], hashes[1]);
    assert_eq!(hashes[0], hashes[2]);
}

#[test]
fn a_column_the_hash_does_not_read_is_refused_by_name() {
    let fields = Fields::from(vec![Field::new("ts", DataType::Int64, true)]);
    let nested: ArrayRef = Arc::new(StructArray::new(
        fields,
        vec![Arc::new(Int64Array::from(vec![1])) as ArrayRef],
        None,
    ));
    let batch = table(vec![("nested", nested)]);

    let refused = table_hash(&batch.schema(), &[batch]).unwrap_err();

    assert!(matches!(refused, TableHashError::Unsupported { column, .. } if column == "nested"));
}

#[test]
fn a_batch_with_other_columns_is_refused() {
    let other = table(vec![("ts_close", Arc::new(Int64Array::from(vec![1])))]);

    let refused = table_hash(&closes().schema(), &[closes(), other]).unwrap_err();

    assert!(
        matches!(refused, TableHashError::Columns { .. }),
        "{refused}"
    );
}

fn signals(trade_date: ArrayRef) -> RecordBatch {
    let flags = |values: [bool; 2]| -> ArrayRef { Arc::new(BooleanArray::from(values.to_vec())) };
    table(vec![
        ("ts_close", Arc::new(Int64Array::from(vec![10, 20]))),
        ("trade_date", trade_date),
        ("long_entry", flags([true, false])),
        ("short_entry", flags([false, false])),
        ("long_exit", flags([false, true])),
        ("short_exit", flags([false, false])),
    ])
}

#[test]
fn a_trade_date_reads_alike_as_days_or_as_a_date() {
    let days = signal_rows_of(&signals(Arc::new(Int64Array::from(vec![20_518, 20_519]))));
    let dates = signal_rows_of(&signals(Arc::new(Date32Array::from(vec![20_518, 20_519]))));

    let days = days.unwrap();
    assert_eq!(days, dates.unwrap());
    assert_eq!(days[1].trade_date, Some(TradeDate(20_519)));
    assert_eq!((days[0].ts_close, days[0].long_entry), (Ts(10), true));
}

#[test]
fn a_trade_date_of_another_type_is_refused() {
    let words: ArrayRef = Arc::new(StringArray::from(vec!["2026-03-06", "2026-03-07"]));

    let refused = signal_rows_of(&signals(words)).unwrap_err().to_string();

    assert_eq!(
        refused,
        "Expected trade_date as int64 days or date32 in the signal rows, got Utf8"
    );
}

const CONFIG: &str = r#"{"fidelity": "1m",
    "instrument": {"tick_size": 250000000, "money_per_point": 50000000, "lot_step": 1000000000},
    "settings": {"latency_ms": 100, "slippage_ticks": {"market": 1, "stop": 1},
        "limit_fill": "through", "roll_handling": "transfer"},
    "hours": {"kind": "sessions", "sessions": [{"open": 1, "close": 9, "halts": []}]},
    "capital": 50000000000, "position": null,
    "fees": {"kind": "futures", "schedules": [{"effective_from": 20654, "per_contract_side": 1870000}]},
    "funding": [],
    "rolls": [{"trade_date": 20521, "session_open": 5, "rolled_from": "ESH2026",
        "contract": "ESM2026", "gap": 1250000000, "reason": "volume"}]}"#;

#[test]
fn a_config_writes_the_json_it_reads() {
    let config: RunConfig = serde_json::from_str(CONFIG).unwrap();

    let written = serde_json::to_string(&config).unwrap();

    assert_eq!(serde_json::from_str::<RunConfig>(&written).unwrap(), config);
    let fronts = config.fronts_from();
    assert_eq!(fronts.len(), 1);
    assert_eq!(fronts[0].0, TradeDate(20_521));
    assert_eq!(fronts[0].1.0, "ESM2026");
}
