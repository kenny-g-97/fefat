//! The Arrow IPC files a batch reads, each row tagged with its case's place in `run.json`: the
//! trades and TBBO records, in the engine cache's columns plus `case` and `trade_date`, and the
//! signal rows. Files are in Arrow IPC's file format, uncompressed, as Polars' `write_ipc` writes
//! them; columns are read by name, and a file a batch does not need may be absent.

use std::collections::BTreeMap;
use std::fs::File;
use std::path::Path;

use arrow_array::cast::AsArray;
use arrow_array::types::{Float64Type, Int64Type};
use arrow_array::{Array, ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch};
use arrow_ipc::reader::FileReader;
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::market_data::TapeDay;
use fefat_core::units::Price;
use fefat_engine::template::SignalRow;
use fefat_engine::tick_run::TickFidelity;

use super::{BatchError, arrow_error};

/// One level's records of each case, by trade date, as slices of the file's batches in the
/// columns the engine cache uses.
type RecordsByCase = BTreeMap<i64, BTreeMap<TradeDate, Vec<RecordBatch>>>;

/// The batch's input tables: `trades.arrow`, `tbbo.arrow`, and `signals.arrow`, each present
/// when a case needs it, grouped by case.
pub(super) struct BatchTables {
    trades: RecordsByCase,
    tbbo: RecordsByCase,
    signals: BTreeMap<i64, Vec<SignalRow>>,
}

impl BatchTables {
    pub(super) fn read(input: &Path) -> Result<Self, BatchError> {
        Ok(Self {
            trades: records_by_case(
                &input.join("trades.arrow"),
                fefat_data::level_columns(Fidelity::Trades),
            )?,
            tbbo: records_by_case(
                &input.join("tbbo.arrow"),
                fefat_data::level_columns(Fidelity::Tbbo),
            )?,
            signals: signal_rows_by_case(&input.join("signals.arrow"))?,
        })
    }

    /// The tape days of `case` at `level`, read as the engine cache's batches are
    /// (`fefat_data::tape_day`).
    pub(super) fn tape_days(
        &self,
        case: i64,
        level: TickFidelity,
    ) -> Result<Vec<TapeDay>, BatchError> {
        let records = match level {
            TickFidelity::Tbbo => &self.tbbo,
            TickFidelity::Trades => &self.trades,
        };
        let Some(days) = records.get(&case) else {
            return Ok(Vec::new());
        };
        let days = days.iter().map(|(&trade_date, batches)| {
            fefat_data::tape_day(trade_date, vec![(level.fidelity(), batches.clone())])
        });
        Ok(days.collect::<Result<_, _>>()?)
    }

    /// The signal rows of `case`, in the file's order: none for a case without any.
    pub(super) fn signal_rows(&self, case: i64) -> Vec<SignalRow> {
        self.signals.get(&case).cloned().unwrap_or_default()
    }
}

/// The signal rows of the file at `path`, grouped by their case; no file, no rows.
fn signal_rows_by_case(path: &Path) -> Result<BTreeMap<i64, Vec<SignalRow>>, BatchError> {
    let mut grouped: BTreeMap<i64, Vec<SignalRow>> = BTreeMap::new();
    for batch in read_batches(path)? {
        for (case, row) in signal_rows_of(path, &batch)? {
            grouped.entry(case).or_default().push(row);
        }
    }
    Ok(grouped)
}

/// Each row of `batch` as its case and its signal row (D-53: a null signal reads as false, a
/// null or absent `wake` as true).
fn signal_rows_of(path: &Path, batch: &RecordBatch) -> Result<Vec<(i64, SignalRow)>, BatchError> {
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
        .map(|(row, (&case, &ts))| {
            let signal_row = SignalRow {
                ts_close: Ts(ts),
                long_entry: signal(long_entry, row),
                short_entry: signal(short_entry, row),
                long_exit: signal(long_exit, row),
                short_exit: signal(short_exit, row),
                stop_price: price_at(stop_price, row),
                target_price: price_at(target_price, row),
                size_mult: float_at(size_mult, row),
                wake: wake.is_none_or(|wake| wake.is_null(row) || wake.value(row)),
            };
            (case, signal_row)
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
