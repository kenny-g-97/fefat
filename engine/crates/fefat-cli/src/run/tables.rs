//! The Arrow IPC files of a batch: the records and signal rows it reads, each row tagged with its
//! case's place in `run.json`, and the fills, orders, and event log it writes, tagged the same
//! way. Files are in Arrow IPC's file format, uncompressed, as Polars' `write_ipc` and
//! `read_ipc` write and read them; columns are read by name.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::BufWriter;
use std::path::Path;
use std::sync::Arc;

use arrow_array::cast::AsArray;
use arrow_array::types::{Float64Type, Int64Type};
use arrow_array::{
    Array, ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch, StringArray, UInt64Array,
};
use arrow_ipc::reader::FileReader;
use arrow_ipc::writer::FileWriter;
use arrow_schema::{ArrowError, Field, Schema};
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::market_data::TapeDay;
use fefat_core::units::Price;
use fefat_engine::book::WorkingOrder;
use fefat_engine::event_log::LogEntry;
use fefat_engine::template::SignalRow;
use fefat_engine::tick_run::{BookedFill, RunOutputs};

use super::BatchError;

const TRADE_COLUMNS: [&str; 3] = ["ts_recv", "price", "size"];
const TBBO_COLUMNS: [&str; 7] = [
    "ts_recv", "price", "size", "bid", "ask", "bid_size", "ask_size",
];

/// One level's records of each case, by trade date, as slices of the file's batches in the
/// columns the engine cache uses.
type RecordsByCase = BTreeMap<i64, BTreeMap<TradeDate, Vec<RecordBatch>>>;

type FillRow<'run> = (i64, &'run BookedFill);
type OrderRow<'run> = (i64, &'run WorkingOrder);
type LogRow<'run> = (i64, &'run LogEntry);

/// The batch's input tables: `trades.arrow`, `tbbo.arrow`, and `signals.arrow`, each present
/// when a case needs it.
pub(super) struct BatchTables {
    trades: RecordsByCase,
    tbbo: RecordsByCase,
    signals: Vec<RecordBatch>,
    signals_path: Box<Path>,
}

impl BatchTables {
    pub(super) fn read(input: &Path) -> Result<Self, BatchError> {
        let signals_path = input.join("signals.arrow");
        Ok(Self {
            trades: records_by_case(&input.join("trades.arrow"), &TRADE_COLUMNS)?,
            tbbo: records_by_case(&input.join("tbbo.arrow"), &TBBO_COLUMNS)?,
            signals: read_batches(&signals_path)?,
            signals_path: signals_path.into_boxed_path(),
        })
    }

    /// The tape days of `case` at `fidelity`, read as the engine cache's batches are
    /// (`fefat_data::tape_day`).
    pub(super) fn tape_days(
        &self,
        case: i64,
        fidelity: Fidelity,
    ) -> Result<Vec<TapeDay>, BatchError> {
        let records = match fidelity {
            Fidelity::Tbbo => &self.tbbo,
            Fidelity::Trades | Fidelity::Bars(_) => &self.trades,
        };
        let Some(days) = records.get(&case) else {
            return Ok(Vec::new());
        };
        let days = days.iter().map(|(&trade_date, batches)| {
            fefat_data::tape_day(trade_date, vec![(fidelity, batches.clone())])
        });
        Ok(days.collect::<Result<_, _>>()?)
    }

    /// The signal rows of `case`, in the file's order (D-53: a null signal reads as false, a null
    /// or absent `wake` as true).
    pub(super) fn signal_rows(&self, case: i64) -> Result<Vec<SignalRow>, BatchError> {
        let mut rows = Vec::new();
        for batch in &self.signals {
            rows.extend(signal_rows_of(&self.signals_path, batch, case)?);
        }
        Ok(rows)
    }
}

fn signal_rows_of(
    path: &Path,
    batch: &RecordBatch,
    case: i64,
) -> Result<Vec<SignalRow>, BatchError> {
    let cases = int64s(path, batch, "case")?.values();
    let ts_close = int64s(path, batch, "ts_close")?.values();
    let (long_entry, short_entry) = (
        booleans(path, batch, "long_entry")?,
        booleans(path, batch, "short_entry")?,
    );
    let (long_exit, short_exit) = (
        booleans(path, batch, "long_exit")?,
        booleans(path, batch, "short_exit")?,
    );
    let stop_price = optional(path, batch, "stop_price", "int64", |column| {
        column.as_primitive_opt::<Int64Type>()
    })?;
    let target_price = optional(path, batch, "target_price", "int64", |column| {
        column.as_primitive_opt::<Int64Type>()
    })?;
    let size_mult = optional(path, batch, "size_mult", "float64", |column| {
        column.as_primitive_opt::<Float64Type>()
    })?;
    let wake = optional(path, batch, "wake", "boolean", |column| {
        column.as_boolean_opt()
    })?;
    let price_at = |column: Option<&Int64Array>, row: usize| {
        column.and_then(|column| column.is_valid(row).then(|| Price(column.value(row))))
    };
    let float_at = |column: Option<&Float64Array>, row: usize| {
        column.and_then(|column| column.is_valid(row).then(|| column.value(row)))
    };
    let signal = |column: &BooleanArray, row: usize| column.is_valid(row) && column.value(row);
    let rows = cases.iter().zip(ts_close).enumerate();
    Ok(rows
        .filter(|(_, (row_case, _))| **row_case == case)
        .map(|(row, (_, &ts))| SignalRow {
            ts_close: Ts(ts),
            long_entry: signal(long_entry, row),
            short_entry: signal(short_entry, row),
            long_exit: signal(long_exit, row),
            short_exit: signal(short_exit, row),
            stop_price: price_at(stop_price, row),
            target_price: price_at(target_price, row),
            size_mult: float_at(size_mult, row),
            wake: wake.is_none_or(|wake| wake.is_null(row) || wake.value(row)),
        })
        .collect())
}

/// The records of a level's file grouped by case and trade date, each run of rows a slice of its
/// batch in `columns`; no file, no records.
fn records_by_case(path: &Path, columns: &[&str]) -> Result<RecordsByCase, BatchError> {
    let mut grouped = RecordsByCase::new();
    for batch in read_batches(path)? {
        let cases = int64s(path, &batch, "case")?.values();
        let dates = int64s(path, &batch, "trade_date")?.values();
        let level = project(path, &batch, columns)?;
        let keys: Vec<(i64, i64)> = cases.iter().copied().zip(dates.iter().copied()).collect();
        let mut offset = 0;
        for run in keys.chunk_by(|left, right| left == right) {
            let Some(&(case, days)) = run.first() else {
                continue;
            };
            let trade_date = i32::try_from(days).map_err(|_| BatchError::Table {
                path: path.to_path_buf(),
                expected: "a trade_date as days since 1970-01-01".to_owned(),
                actual: days.to_string(),
            })?;
            let slice = level.slice(offset, run.len());
            let days_of_case = grouped.entry(case).or_default();
            days_of_case
                .entry(TradeDate(trade_date))
                .or_default()
                .push(slice);
            offset += run.len();
        }
    }
    Ok(grouped)
}

fn read_batches(path: &Path) -> Result<Vec<RecordBatch>, BatchError> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let file = File::open(path).map_err(|source| BatchError::Io {
        action: "open",
        path: path.to_path_buf(),
        source,
    })?;
    let reader = FileReader::try_new(file, None).map_err(arrow_error(path))?;
    reader
        .collect::<Result<Vec<_>, _>>()
        .map_err(arrow_error(path))
}

fn project(path: &Path, batch: &RecordBatch, columns: &[&str]) -> Result<RecordBatch, BatchError> {
    let schema = batch.schema();
    let indices = columns
        .iter()
        .map(|name| schema.index_of(name))
        .collect::<Result<Vec<_>, _>>()
        .map_err(arrow_error(path))?;
    batch.project(&indices).map_err(arrow_error(path))
}

/// A column of int64 values without nulls.
fn int64s<'batch>(
    path: &Path,
    batch: &'batch RecordBatch,
    name: &str,
) -> Result<&'batch Int64Array, BatchError> {
    let column = required(path, batch, name)?;
    if column.null_count() > 0 {
        return Err(BatchError::Table {
            path: path.to_path_buf(),
            expected: format!("no null in {name}"),
            actual: format!("{} nulls", column.null_count()),
        });
    }
    column
        .as_primitive_opt::<Int64Type>()
        .ok_or_else(|| wrong_type(path, name, "int64", column))
}

/// A column of booleans, whose nulls the caller reads.
fn booleans<'batch>(
    path: &Path,
    batch: &'batch RecordBatch,
    name: &str,
) -> Result<&'batch BooleanArray, BatchError> {
    let column = required(path, batch, name)?;
    column
        .as_boolean_opt()
        .ok_or_else(|| wrong_type(path, name, "boolean", column))
}

fn required<'batch>(
    path: &Path,
    batch: &'batch RecordBatch,
    name: &str,
) -> Result<&'batch ArrayRef, BatchError> {
    batch.column_by_name(name).ok_or_else(|| BatchError::Table {
        path: path.to_path_buf(),
        expected: format!("a column {name}"),
        actual: "none".to_owned(),
    })
}

/// A column the frame may leave out, as `cast` reads it; a column of another type is refused.
fn optional<'batch, T: 'batch>(
    path: &Path,
    batch: &'batch RecordBatch,
    name: &str,
    expected: &str,
    cast: impl Fn(&'batch ArrayRef) -> Option<&'batch T>,
) -> Result<Option<&'batch T>, BatchError> {
    let Some(column) = batch.column_by_name(name) else {
        return Ok(None);
    };
    cast(column)
        .map(Some)
        .ok_or_else(|| wrong_type(path, name, expected, column))
}

fn wrong_type(path: &Path, name: &str, expected: &str, column: &ArrayRef) -> BatchError {
    BatchError::Table {
        path: path.to_path_buf(),
        expected: format!("{name} as {expected}"),
        actual: column.data_type().to_string(),
    }
}

fn arrow_error(path: &Path) -> impl Fn(ArrowError) -> BatchError + '_ {
    move |source| BatchError::Arrow {
        path: path.to_path_buf(),
        source,
    }
}

/// Writes the fills, the orders, and the event log of each case, in `run.json`'s order, into
/// `fills.arrow`, `orders.arrow`, and `log.arrow` in `output`.
pub(super) fn write_outputs(output: &Path, runs: &[(i64, RunOutputs)]) -> Result<(), BatchError> {
    let written = [
        ("fills.arrow", fills_batch(runs)),
        ("orders.arrow", orders_batch(runs)),
        ("log.arrow", log_batch(runs)),
    ];
    for (name, batch) in written {
        let path = output.join(name);
        write_ipc(&path, &batch.map_err(arrow_error(&path))?)?;
    }
    Ok(())
}

fn fills_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<FillRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.fills.iter().map(move |booked| (*case, booked)))
        .collect();
    let int = |value: fn(&FillRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let text = |value: fn(&FillRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let flag = |value: fn(&FillRow<'_>) -> bool| -> ArrayRef {
        Arc::new(BooleanArray::from(
            rows.iter().map(value).collect::<Vec<_>>(),
        ))
    };
    let order = UInt64Array::from_iter_values(rows.iter().map(|(_, booked)| booked.fill.order.0));
    batch(vec![
        ("case", int(|(case, _)| *case)),
        ("order", Arc::new(order)),
        ("role", text(|(_, booked)| booked.fill.role.to_string())),
        ("side", text(|(_, booked)| booked.fill.side.to_string())),
        ("lots", int(|(_, booked)| booked.fill.lots.0)),
        ("ts", int(|(_, booked)| booked.fill.ts.0)),
        ("price", int(|(_, booked)| booked.fill.price.0)),
        ("rule", text(|(_, booked)| booked.fill.rule.id().to_owned())),
        (
            "fidelity",
            text(|(_, booked)| booked.fill.fidelity.to_string()),
        ),
        (
            "liquidity",
            text(|(_, booked)| booked.fill.liquidity.to_string()),
        ),
        (
            "slippage_ticks",
            int(|(_, booked)| booked.fill.slippage_ticks),
        ),
        ("ambiguous", flag(|(_, booked)| booked.fill.flags.ambiguous)),
        (
            "size_exceeded",
            flag(|(_, booked)| booked.fill.flags.size_exceeded),
        ),
        ("fee", int(|(_, booked)| booked.fill.fee.0)),
        ("cash", int(|(_, booked)| booked.cash.0)),
    ])
}

fn orders_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<OrderRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.orders.iter().map(move |order| (*case, order)))
        .collect();
    let int = |value: fn(&OrderRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let id = |value: fn(&OrderRow<'_>) -> Option<u64>| -> ArrayRef {
        Arc::new(UInt64Array::from(
            rows.iter().map(value).collect::<Vec<_>>(),
        ))
    };
    let text = |value: fn(&OrderRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let price = rows
        .iter()
        .map(|(_, order)| order.level().map(|price| price.0));
    batch(vec![
        ("case", int(|(case, _)| *case)),
        ("id", id(|(_, order)| Some(order.order.id.0))),
        ("side", text(|(_, order)| order.order.side.to_string())),
        ("kind", text(|(_, order)| order.order.kind.to_string())),
        (
            "price",
            Arc::new(Int64Array::from(price.collect::<Vec<_>>())),
        ),
        ("lots", int(|(_, order)| order.order.lots.0)),
        ("role", text(|(_, order)| order.order.role.to_string())),
        ("placed_at", int(|(_, order)| order.order.placed_at.0)),
        ("activation", int(|(_, order)| order.order.activation.0)),
        ("oco", id(|(_, order)| order.order.oco.map(|group| group.0))),
        (
            "bracket_of",
            id(|(_, order)| order.bracket_of.map(|entry| entry.0)),
        ),
        ("state", text(|(_, order)| order.state.to_string())),
    ])
}

fn log_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<LogRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.log.iter().map(move |entry| (*case, entry)))
        .collect();
    let int = |value: fn(&LogRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let text = |value: fn(&LogRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let order = rows
        .iter()
        .map(|(_, entry)| entry.order.map(|order| order.0));
    let rule = rows.iter().map(|(_, entry)| entry.rule);
    batch(vec![
        ("case", int(|(case, _)| *case)),
        ("ts", int(|(_, entry)| entry.ts.0)),
        ("kind", text(|(_, entry)| entry.kind.to_string())),
        (
            "order",
            Arc::new(UInt64Array::from(order.collect::<Vec<_>>())),
        ),
        (
            "rule",
            Arc::new(StringArray::from(rule.collect::<Vec<_>>())),
        ),
        ("text", text(|(_, entry)| entry.text.clone())),
    ])
}

fn batch(columns: Vec<(&str, ArrayRef)>) -> Result<RecordBatch, ArrowError> {
    let fields: Vec<Field> = columns
        .iter()
        .map(|(name, column)| Field::new(*name, column.data_type().clone(), true))
        .collect();
    let arrays = columns.into_iter().map(|(_, column)| column).collect();
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
}

fn write_ipc(path: &Path, batch: &RecordBatch) -> Result<(), BatchError> {
    let io_error = |source| BatchError::Io {
        action: "write",
        path: path.to_path_buf(),
        source,
    };
    let file = File::create(path).map_err(io_error)?;
    let mut writer =
        FileWriter::try_new(BufWriter::new(file), &batch.schema()).map_err(arrow_error(path))?;
    writer.write(batch).map_err(arrow_error(path))?;
    writer.finish().map_err(arrow_error(path))?;
    let buffered = writer.into_inner().map_err(arrow_error(path))?;
    buffered
        .into_inner()
        .map(drop)
        .map_err(|error| io_error(error.into_error()))
}
