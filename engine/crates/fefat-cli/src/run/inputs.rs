//! The Arrow IPC files a batch reads, each row tagged with its case's place in `run.json`: a file
//! per level its cases read, `trades.arrow`, `tbbo.arrow`, or a bar timeframe's such as
//! `1m.arrow`, in the engine cache's columns plus `case` and `trade_date`, and the signal rows.
//! Files are in Arrow IPC's file format, uncompressed, as Polars' `write_ipc` writes them;
//! columns are read by name. The file of every level a case names must be there, and
//! `signals.arrow` may be absent where no case has signal rows.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::path::Path;

use arrow_array::cast::AsArray;
use arrow_array::types::Int64Type;
use arrow_array::{Array, ArrayRef, Int64Array, RecordBatch};
use arrow_ipc::reader::FileReader;
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::TradeDate;
use fefat_core::market_data::TapeDay;
use fefat_engine::template::SignalRow;
use fefat_run::signal_rows::signal_rows_of;

use super::manifest::RunManifest;
use super::{BatchError, arrow_error};

/// One level's records of each case, by trade date, as slices of the file's batches in the
/// columns the engine cache uses.
type RecordsByCase = BTreeMap<i64, BTreeMap<TradeDate, Vec<RecordBatch>>>;

/// The batch's input tables: the file of each level its cases read and `signals.arrow`, grouped
/// by case.
pub(super) struct BatchTables {
    levels: BTreeMap<Fidelity, RecordsByCase>,
    signals: BTreeMap<i64, Vec<SignalRow>>,
}

impl BatchTables {
    /// The file `<level>.arrow` of every level a case of `manifest` reads, and the signal rows.
    pub(super) fn read(input: &Path, manifest: &RunManifest) -> Result<Self, BatchError> {
        let named: BTreeSet<Fidelity> = manifest
            .cases
            .iter()
            .flat_map(|case| case.tape_levels().iter().copied())
            .collect();
        let mut levels = BTreeMap::new();
        for level in named {
            let path = input.join(format!("{level}.arrow"));
            if !path.is_file() {
                return Err(BatchError::Table {
                    path,
                    expected: format!("the {level} records that a case of run.json reads"),
                    actual: "no such file".to_owned(),
                });
            }
            let records = records_by_case(&path, fefat_data::level_columns(level))?;
            levels.insert(level, records);
        }
        Ok(Self {
            levels,
            signals: signal_rows_by_case(&input.join("signals.arrow"))?,
        })
    }

    /// The tape days of `case` at each of `levels`, read as the engine cache's batches are
    /// (`fefat_data::tape_day`).
    pub(super) fn tape_days(
        &self,
        case: i64,
        levels: &[Fidelity],
    ) -> Result<Vec<TapeDay>, BatchError> {
        let mut by_date: BTreeMap<TradeDate, Vec<(Fidelity, Vec<RecordBatch>)>> = BTreeMap::new();
        for &level in levels {
            let held = self
                .levels
                .get(&level)
                .and_then(|records| records.get(&case));
            for (&trade_date, batches) in held.into_iter().flatten() {
                let day = by_date.entry(trade_date).or_default();
                day.push((level, batches.clone()));
            }
        }
        let days = by_date
            .into_iter()
            .map(|(trade_date, levels)| fefat_data::tape_day(trade_date, levels));
        Ok(days.collect::<Result<_, _>>()?)
    }

    /// The signal rows of `case`, in the file's order: none for a case without any.
    pub(super) fn signal_rows(&self, case: i64) -> Vec<SignalRow> {
        self.signals.get(&case).cloned().unwrap_or_default()
    }
}

/// The signal rows of the file at `path`, grouped by their case; no file, no rows. Each row is
/// read as `fefat_run::signal_rows` reads it.
fn signal_rows_by_case(path: &Path) -> Result<BTreeMap<i64, Vec<SignalRow>>, BatchError> {
    let mut grouped: BTreeMap<i64, Vec<SignalRow>> = BTreeMap::new();
    for batch in read_batches(path)? {
        let cases = int64s(path, &batch, "case")?.values();
        let rows = signal_rows_of(&batch).map_err(|error| BatchError::Table {
            path: path.to_path_buf(),
            expected: error.expected,
            actual: error.actual,
        })?;
        for (&case, row) in cases.iter().zip(rows) {
            grouped.entry(case).or_default().push(row);
        }
    }
    Ok(grouped)
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

fn wrong_type(path: &Path, name: &str, expected: &str, column: &ArrayRef) -> BatchError {
    BatchError::Table {
        path: path.to_path_buf(),
        expected: format!("{name} as {expected}"),
        actual: column.data_type().to_string(),
    }
}
