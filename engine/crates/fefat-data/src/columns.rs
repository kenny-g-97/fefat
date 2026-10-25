//! A trade date's records as Arrow columns, both ways: [`tape_day`] reads the batches the
//! Python builder hands over, and the writer turns what a reader serves into batches.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use arrow_array::cast::AsArray;
use arrow_array::types::{Int64Type, UInt32Type};
use arrow_array::{Array, ArrayRef, Int64Array, RecordBatch, UInt32Array};
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::market_data::{BarRow, MarketDataReader, TapeDay, TbboRow, TradeRow};
use fefat_core::units::{Price, Qty};

use crate::error::CacheError;
use crate::layout::{
    BAR_COLUMNS, OFFSET_COLUMN, TBBO_COLUMNS, TRADE_COLUMNS, descent_schema, level_schema,
};

/// The tape day of `trade_date` from Arrow batches of each of its levels, in the cache's columns
/// and order: `ts_recv`, `price`, and `size` for trades, then `bid`, `ask`, `bid_size`, and
/// `ask_size` for TBBO, and `ts_open`, `ts_close`, `open`, `high`, `low`, `close`, and `volume`
/// for bars, each int64 without nulls. A level named twice, other columns, or a null is refused.
pub fn tape_day(
    trade_date: TradeDate,
    levels: Vec<(Fidelity, Vec<RecordBatch>)>,
) -> Result<TapeDay, CacheError> {
    let mut day = TapeDay {
        trade_date,
        tbbo: Vec::new(),
        trades: Vec::new(),
        bars: BTreeMap::new(),
    };
    let mut named = BTreeSet::new();
    for (level, batches) in levels {
        let context = format!("the {level} records of {trade_date}");
        if !named.insert(level) {
            return Err(CacheError::refused("each level once", "it twice", context));
        }
        match level {
            Fidelity::Tbbo => day.tbbo = tbbo_rows(&batches, &context)?,
            Fidelity::Trades => day.trades = trade_rows(&batches, &context)?,
            Fidelity::Bars(timeframe) => {
                day.bars.insert(timeframe, bar_rows(&batches, &context)?);
            }
        }
    }
    Ok(day)
}

fn trade_rows(batches: &[RecordBatch], context: &str) -> Result<Vec<TradeRow>, CacheError> {
    let mut rows = Vec::new();
    for batch in batches {
        let [ts_recv, price, size] = int64_values(batch, TRADE_COLUMNS, context)?;
        let zipped = ts_recv.iter().zip(price).zip(size);
        rows.extend(zipped.map(|((ts_recv, price), size)| TradeRow {
            ts_recv: Ts(*ts_recv),
            price: Price(*price),
            size: Qty(*size),
        }));
    }
    Ok(rows)
}

fn tbbo_rows(batches: &[RecordBatch], context: &str) -> Result<Vec<TbboRow>, CacheError> {
    let mut rows = Vec::new();
    for batch in batches {
        let [ts_recv, price, size, bid, ask, bid_size, ask_size] =
            int64_values(batch, TBBO_COLUMNS, context)?;
        let trades = ts_recv.iter().zip(price).zip(size);
        let quotes = bid.iter().zip(ask).zip(bid_size).zip(ask_size);
        rows.extend(trades.zip(quotes).map(
            |(((ts_recv, price), size), (((bid, ask), bid_size), ask_size))| TbboRow {
                ts_recv: Ts(*ts_recv),
                price: Price(*price),
                size: Qty(*size),
                bid: Price(*bid),
                ask: Price(*ask),
                bid_size: Qty(*bid_size),
                ask_size: Qty(*ask_size),
            },
        ));
    }
    Ok(rows)
}

fn bar_rows(batches: &[RecordBatch], context: &str) -> Result<Vec<BarRow>, CacheError> {
    let mut rows = Vec::new();
    for batch in batches {
        let [ts_open, ts_close, open, high, low, close, volume] =
            int64_values(batch, BAR_COLUMNS, context)?;
        let spans = ts_open.iter().zip(ts_close);
        let prices = open.iter().zip(high).zip(low).zip(close);
        rows.extend(spans.zip(prices).zip(volume).map(
            |(((ts_open, ts_close), (((open, high), low), close)), volume)| BarRow {
                ts_open: Ts(*ts_open),
                ts_close: Ts(*ts_close),
                open: Price(*open),
                high: Price(*high),
                low: Price(*low),
                close: Price(*close),
                volume: Qty(*volume),
            },
        ));
    }
    Ok(rows)
}

/// The values of a batch whose columns are `names`, in that order, each int64 without nulls.
fn int64_values<'a, const N: usize>(
    batch: &'a RecordBatch,
    names: [&str; N],
    context: &str,
) -> Result<[&'a [i64]; N], CacheError> {
    require_columns(batch, &names, context)?;
    let mut values: [&[i64]; N] = [&[]; N];
    for ((slot, column), name) in values.iter_mut().zip(batch.columns()).zip(names) {
        *slot = int64_array(column, name, context)?.values();
    }
    Ok(values)
}

/// Refuses a batch whose columns are not `names`, in that order.
pub(crate) fn require_columns(
    batch: &RecordBatch,
    names: &[&str],
    context: &str,
) -> Result<(), CacheError> {
    let schema = batch.schema_ref();
    let found: Vec<&str> = schema
        .fields()
        .iter()
        .map(|field| field.name().as_str())
        .collect();
    if found != names {
        let (expected, actual) = (format!("the columns {names:?}"), format!("{found:?}"));
        return Err(CacheError::refused(expected, actual, context));
    }
    Ok(())
}

/// A column as int64 values without nulls.
pub(crate) fn int64_array<'a>(
    column: &'a ArrayRef,
    name: &str,
    context: &str,
) -> Result<&'a Int64Array, CacheError> {
    let what = format!("the column {name} of {context}");
    let values = column.as_primitive_opt::<Int64Type>().ok_or_else(|| {
        CacheError::refused("int64 values", column.data_type().to_string(), &what)
    })?;
    refuse_nulls(values, &what)?;
    Ok(values)
}

/// A column as uint32 values without nulls.
pub(crate) fn uint32_array<'a>(
    column: &'a ArrayRef,
    context: &str,
) -> Result<&'a UInt32Array, CacheError> {
    let what = format!("the column {OFFSET_COLUMN} of {context}");
    let values = column.as_primitive_opt::<UInt32Type>().ok_or_else(|| {
        CacheError::refused("uint32 values", column.data_type().to_string(), &what)
    })?;
    refuse_nulls(values, &what)?;
    Ok(values)
}

fn refuse_nulls(values: &dyn Array, what: &str) -> Result<(), CacheError> {
    match values.null_count() {
        0 => Ok(()),
        nulls => Err(CacheError::refused(
            "no nulls",
            format!("{nulls} nulls"),
            what,
        )),
    }
}

/// The batch of one level of a trade date, as `reader` serves it.
pub(crate) fn level_batch(
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    level: Fidelity,
) -> Result<RecordBatch, CacheError> {
    let columns = match level {
        Fidelity::Tbbo => {
            let tbbo = reader.tbbo(trade_date)?;
            vec![
                int64_column(tbbo.ts_recv, |ts| ts.0),
                int64_column(tbbo.price, |price| price.0),
                int64_column(tbbo.size, |size| size.0),
                int64_column(tbbo.bid, |bid| bid.0),
                int64_column(tbbo.ask, |ask| ask.0),
                int64_column(tbbo.bid_size, |size| size.0),
                int64_column(tbbo.ask_size, |size| size.0),
            ]
        }
        Fidelity::Trades => {
            let trades = reader.trades(trade_date)?;
            vec![
                int64_column(trades.ts_recv, |ts| ts.0),
                int64_column(trades.price, |price| price.0),
                int64_column(trades.size, |size| size.0),
            ]
        }
        Fidelity::Bars(timeframe) => bar_columns(reader, trade_date, timeframe)?,
    };
    RecordBatch::try_new(level_schema(level), columns).map_err(|error| {
        let context = format!("the {level} batch of {trade_date}");
        CacheError::refused("a batch of the level's columns", error.to_string(), context)
    })
}

fn bar_columns(
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    timeframe: Timeframe,
) -> Result<Vec<ArrayRef>, CacheError> {
    let bars = reader.bars(trade_date, timeframe)?;
    Ok(vec![
        int64_column(bars.ts_open, |ts| ts.0),
        int64_column(bars.ts_close, |ts| ts.0),
        int64_column(bars.open, |price| price.0),
        int64_column(bars.high, |price| price.0),
        int64_column(bars.low, |price| price.0),
        int64_column(bars.close, |price| price.0),
        int64_column(bars.volume, |volume| volume.0),
    ])
}

fn int64_column<T: Copy>(values: &[T], value: impl Fn(T) -> i64) -> ArrayRef {
    Arc::new(Int64Array::from_iter_values(
        values.iter().copied().map(value),
    ))
}

/// The batch of the descent from `timeframe`'s bars to `finer` on a trade date.
pub(crate) fn descent_batch(
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    timeframe: Timeframe,
    finer: Fidelity,
) -> Result<RecordBatch, CacheError> {
    let offsets = reader.offsets(trade_date, timeframe, finer)?;
    let column: ArrayRef = Arc::new(UInt32Array::from_iter_values(offsets.iter().copied()));
    RecordBatch::try_new(descent_schema(), vec![column]).map_err(|error| {
        let context = format!("the descent from {timeframe} bars to {finer} on {trade_date}");
        CacheError::refused("a batch of offsets", error.to_string(), context)
    })
}
