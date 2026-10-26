//! A trade date read from the Arrow batches that the Python builder hands over ([`tape_day`]).

use std::sync::Arc;

use arrow_array::{ArrayRef, Int64Array, RecordBatch, UInt32Array};
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::market_data::conformance::{FIRST_DAY, sample_tape};
use fefat_core::market_data::{BarRow, TapeDay, TbboRow, TradeRow};

use crate::tape_day;

fn int64(values: impl IntoIterator<Item = i64>) -> ArrayRef {
    Arc::new(Int64Array::from_iter_values(values))
}

fn trade_batch(rows: &[TradeRow]) -> RecordBatch {
    RecordBatch::try_from_iter([
        ("ts_recv", int64(rows.iter().map(|row| row.ts_recv.0))),
        ("price", int64(rows.iter().map(|row| row.price.0))),
        ("size", int64(rows.iter().map(|row| row.size.0))),
    ])
    .unwrap()
}

fn tbbo_batch(rows: &[TbboRow]) -> RecordBatch {
    RecordBatch::try_from_iter([
        ("ts_recv", int64(rows.iter().map(|row| row.ts_recv.0))),
        ("price", int64(rows.iter().map(|row| row.price.0))),
        ("size", int64(rows.iter().map(|row| row.size.0))),
        ("bid", int64(rows.iter().map(|row| row.bid.0))),
        ("ask", int64(rows.iter().map(|row| row.ask.0))),
        ("bid_size", int64(rows.iter().map(|row| row.bid_size.0))),
        ("ask_size", int64(rows.iter().map(|row| row.ask_size.0))),
    ])
    .unwrap()
}

fn bar_batch(rows: &[BarRow]) -> RecordBatch {
    RecordBatch::try_from_iter([
        ("ts_open", int64(rows.iter().map(|row| row.ts_open.0))),
        ("ts_close", int64(rows.iter().map(|row| row.ts_close.0))),
        ("open", int64(rows.iter().map(|row| row.open.0))),
        ("high", int64(rows.iter().map(|row| row.high.0))),
        ("low", int64(rows.iter().map(|row| row.low.0))),
        ("close", int64(rows.iter().map(|row| row.close.0))),
        ("volume", int64(rows.iter().map(|row| row.volume.0))),
    ])
    .unwrap()
}

/// The day's levels as batches, each level's split in two, as a frame of two chunks arrives.
fn batches_of(day: &TapeDay) -> Vec<(Fidelity, Vec<RecordBatch>)> {
    let halves = |batch: RecordBatch| {
        let half = batch.num_rows() / 2;
        vec![
            batch.slice(0, half),
            batch.slice(half, batch.num_rows() - half),
        ]
    };
    let mut levels = vec![
        (Fidelity::Tbbo, halves(tbbo_batch(&day.tbbo))),
        (Fidelity::Trades, halves(trade_batch(&day.trades))),
    ];
    for (timeframe, bars) in &day.bars {
        levels.push((Fidelity::Bars(*timeframe), halves(bar_batch(bars))));
    }
    levels
}

#[test]
fn a_tape_day_reads_back_from_its_arrow_batches() {
    let day = sample_tape().remove(0);

    let read = tape_day(FIRST_DAY, batches_of(&day)).unwrap();

    assert_eq!(read, day);
}

#[test]
fn a_null_another_type_or_other_columns_are_refused_with_the_level_and_the_date() {
    let trades = trade_batch(&sample_tape().remove(0).trades);
    let with_a_null: ArrayRef = Arc::new(Int64Array::from(vec![Some(3), None, Some(2)]));
    let sizes_as_uint32: ArrayRef = Arc::new(UInt32Array::from(vec![3, 1, 2, 4, 1, 2]));
    let replaced = |name: &str, column: ArrayRef| {
        let rows = column.len();
        let mut columns: Vec<(&str, ArrayRef)> = vec![
            ("ts_recv", trades.column(0).slice(0, rows)),
            ("price", trades.column(1).slice(0, rows)),
            ("size", trades.column(2).slice(0, rows)),
        ];
        for (named, slot) in &mut columns {
            if *named == name {
                *slot = column.clone();
            }
        }
        RecordBatch::try_from_iter(columns).unwrap()
    };
    let refusal = |batch: RecordBatch| {
        let levels = vec![(Fidelity::Trades, vec![batch])];
        tape_day(FIRST_DAY, levels).unwrap_err().to_string()
    };

    let null = refusal(replaced("size", with_a_null));
    let uint32 = refusal(replaced("size", sizes_as_uint32));
    let other_columns = refusal(trades.project(&[0, 2, 1]).unwrap());

    let context = "the trades records of 2026-03-05";
    assert_eq!(
        null,
        format!("Expected no nulls, got 1 nulls in the column size of {context}")
    );
    assert_eq!(
        uint32,
        format!("Expected int64 values, got UInt32 in the column size of {context}")
    );
    assert_eq!(
        other_columns,
        format!(
            "Expected the columns [\"ts_recv\", \"price\", \"size\"], got [\"ts_recv\", \"size\", \"price\"] in {context}"
        )
    );
}

#[test]
fn a_level_named_twice_is_refused() {
    let day = sample_tape().remove(0);
    let minutes = bar_batch(&day.bars[&Timeframe::ONE_MINUTE]);
    let levels = vec![
        (Fidelity::Bars(Timeframe::ONE_MINUTE), vec![minutes.clone()]),
        (Fidelity::Bars(Timeframe::ONE_MINUTE), vec![minutes]),
    ];

    let refused = tape_day(FIRST_DAY, levels).unwrap_err();

    assert_eq!(
        refused.to_string(),
        "Expected each level once, got it twice in the 1m records of 2026-03-05"
    );
}
