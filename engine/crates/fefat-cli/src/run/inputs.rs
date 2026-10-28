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
use arrow_array::types::{Float64Type, Int64Type};
use arrow_array::{Array, ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch};
use arrow_ipc::reader::FileReader;
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::market_data::TapeDay;
use fefat_core::units::Price;
use fefat_engine::template::{RowFeatures, SignalRow};

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
/// null or absent `wake` as true, and a null or absent price, feature, or `flat_by` as none).
fn signal_rows_of(path: &Path, batch: &RecordBatch) -> Result<Vec<(i64, SignalRow)>, BatchError> {
    let cases = int64s(path, batch, "case")?.values();
    let ts_close = int64s(path, batch, "ts_close")?.values();
    let columns = SignalColumns::of(path, batch)?;
    let rows = cases.iter().zip(ts_close).enumerate();
    Ok(rows
        .map(|(row, (&case, &ts))| (case, columns.row(row, Ts(ts))))
        .collect())
}

/// The columns of the signal rows but their case and close: the four signals; the prices the
/// exit plan reads; the features its rules name, which `fefat.reference.rust_batch` writes
/// under the names of their rules (`stop_feature`, `target_feature_1` to `target_feature_3`,
/// `trail_feature`); and the size's multiple, `wake`, and `flat_by`, each absent where the frame
/// leaves it out.
struct SignalColumns<'batch> {
    signals: [&'batch BooleanArray; 4],
    prices: [Option<&'batch Int64Array>; 4],
    features: [Option<&'batch Float64Array>; 5],
    size_mult: Option<&'batch Float64Array>,
    wake: Option<&'batch BooleanArray>,
    flat_by: Option<&'batch Int64Array>,
    times: [Option<&'batch BooleanArray>; 3],
}

impl<'batch> SignalColumns<'batch> {
    fn of(path: &Path, batch: &'batch RecordBatch) -> Result<Self, BatchError> {
        let signal = |name| booleans(path, batch, name);
        let ints = |name| {
            optional(path, batch, name, "int64", |column| {
                column.as_primitive_opt::<Int64Type>()
            })
        };
        let floats = |name| {
            optional(path, batch, name, "float64", |column| {
                column.as_primitive_opt::<Float64Type>()
            })
        };
        let flags = |name| {
            optional(path, batch, name, "boolean", |column| {
                column.as_boolean_opt()
            })
        };
        Ok(Self {
            signals: [
                signal("long_entry")?,
                signal("short_entry")?,
                signal("long_exit")?,
                signal("short_exit")?,
            ],
            prices: [
                ints("entry_price")?,
                ints("stop_price")?,
                ints("target_price")?,
                ints("trail_ref")?,
            ],
            features: [
                floats("stop_feature")?,
                floats("target_feature_1")?,
                floats("target_feature_2")?,
                floats("target_feature_3")?,
                floats("trail_feature")?,
            ],
            size_mult: floats("size_mult")?,
            wake: flags("wake")?,
            flat_by: ints("flat_by")?,
            times: [
                flags("session_end")?,
                flags("week_end")?,
                flags("in_window")?,
            ],
        })
    }

    fn row(&self, row: usize, ts_close: Ts) -> SignalRow {
        let signal = |column: &BooleanArray| column.is_valid(row) && column.value(row);
        let [long_entry, short_entry, long_exit, short_exit] = self.signals.map(signal);
        let [entry_price, stop_price, target_price, trail_ref] = self.prices.map(|column| {
            let price = column.filter(|column| column.is_valid(row));
            price.map(|column| Price(column.value(row)))
        });
        let [stop, first, second, third, trailing] = self.features.map(|column| {
            let value = column.filter(|column| column.is_valid(row));
            value.map(|column| column.value(row))
        });
        let flat_by = self.flat_by.filter(|column| column.is_valid(row));
        let [session_end, week_end, in_window] = self.times.map(|column| {
            let flag = column.filter(|column| column.is_valid(row));
            flag.map(|column| column.value(row))
        });
        SignalRow {
            ts_close,
            long_entry,
            short_entry,
            long_exit,
            short_exit,
            entry_price,
            stop_price,
            target_price,
            trail_ref,
            features: RowFeatures {
                stop,
                targets: [first, second, third],
                trailing,
            },
            size_mult: self
                .size_mult
                .filter(|column| column.is_valid(row))
                .map(|column| column.value(row)),
            wake: self
                .wake
                .is_none_or(|wake| wake.is_null(row) || wake.value(row)),
            flat_by: flat_by.map(|column| Ts(column.value(row))),
            session_end,
            week_end,
            in_window,
        }
    }
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
