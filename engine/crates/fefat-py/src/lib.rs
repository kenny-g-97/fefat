//! PyO3 bindings: the Python module fefat_engine.

mod backtests;
mod hashing;

use std::fmt::Display;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// An error of the engine as Python's `ValueError`, its message the engine's.
fn value_error(error: impl Display) -> PyErr {
    PyValueError::new_err(error.to_string())
}

/// The FEFAT engine, compiled from Rust.
#[pymodule]
mod fefat_engine {
    use std::collections::BTreeMap;
    use std::path::PathBuf;

    use arrow_array::cast::AsArray;
    use arrow_array::types::{ArrowPrimitiveType, Int64Type};
    use arrow_array::{Array, PrimitiveArray};
    use fefat_core::drawdown::{self, DrawdownOverflow};
    use fefat_core::fidelity::Fidelity;
    use fefat_core::instants::TradeDate;
    use fefat_core::instrument::Contract;
    use fefat_core::run_key::{ARTIFACT_SCHEMA_VERSION, ENGINE_VERSION, FILL_MODEL_VERSION};
    use fefat_data::{Month, SourceFile};
    use pyo3::exceptions::{PyOverflowError, PyTypeError, PyValueError};
    use pyo3::prelude::*;
    use pyo3_arrow::PyTable;
    use pyo3_arrow::input::AnyArray;

    use crate::value_error;

    #[pymodule_export]
    use crate::backtests::{run_batch, run_signal_backtest};
    #[pymodule_export]
    use crate::hashing::{run_key, table_hash};

    /// The engine's versions, which a run key covers (`02` §4): `ENGINE_VERSION`,
    /// `FILL_MODEL_VERSION`, and `ARTIFACT_SCHEMA_VERSION`.
    #[pymodule_init]
    fn add_versions(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add("ENGINE_VERSION", ENGINE_VERSION.0)?;
        module.add("FILL_MODEL_VERSION", FILL_MODEL_VERSION.0)?;
        module.add("ARTIFACT_SCHEMA_VERSION", ARTIFACT_SCHEMA_VERSION.0)?;
        Ok(())
    }

    /// Writes one contract-month of the engine cache (`fefat_data::CacheMonthWriter`): `contract`'s
    /// `month` (`2026-03`) in `contract_folder`, built from the store partitions `sources`, each
    /// its path and SHA-256, from `trade_dates`, an iterable of each trade date (`2026-03-05`), in
    /// ascending order, with a frame per level named as the fidelity type spells it (`trades`,
    /// `1m`), pulled one date at a time. A month refused part way is removed.
    #[pyfunction]
    fn write_cache_month(
        contract_folder: PathBuf,
        contract: String,
        month: &str,
        sources: Vec<(String, String)>,
        trade_dates: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let month: Month = month.parse().map_err(value_error)?;
        let sources = sources
            .into_iter()
            .map(|(path, sha256)| SourceFile { path, sha256 })
            .collect();
        let contract = Contract(contract);
        let mut writer =
            fefat_data::CacheMonthWriter::create(&contract_folder, contract, month, sources)
                .map_err(value_error)?;
        match write_trade_dates(&mut writer, trade_dates) {
            Ok(()) => writer.finish().map(|_| ()).map_err(value_error),
            Err(refusal) => {
                if let Err(removal) = writer.abandon() {
                    refusal.set_cause(trade_dates.py(), Some(value_error(removal)));
                }
                Err(refusal)
            }
        }
    }

    fn write_trade_dates(
        writer: &mut fefat_data::CacheMonthWriter,
        trade_dates: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        for item in trade_dates.try_iter()? {
            let (trade_date, levels): (String, Vec<(String, PyTable)>) = item?.extract()?;
            let trade_date: TradeDate = trade_date.parse().map_err(value_error)?;
            let levels = levels
                .into_iter()
                .map(|(level, frame)| {
                    let level: Fidelity = level.parse().map_err(value_error)?;
                    Ok((level, frame.into_inner().0))
                })
                .collect::<PyResult<Vec<_>>>()?;
            let day = fefat_data::tape_day(trade_date, levels).map_err(value_error)?;
            writer.write_trade_date(day).map_err(value_error)?;
        }
        Ok(())
    }

    /// The largest fall of the cumulative sum of `values` below its highest point so far.
    #[pyfunction]
    fn max_drawdown(values: Vec<i64>) -> PyResult<i64> {
        drawdown::max_drawdown(values).map_err(overflow_error)
    }

    /// `max_drawdown` over an int64 Arrow array or stream, such as a PyArrow array or a
    /// Polars series, read in place through the Arrow PyCapsule interface.
    #[pyfunction]
    fn max_drawdown_arrow(values: AnyArray) -> PyResult<i64> {
        let chunks = int64_chunks(values)?;
        drawdown::max_drawdown(
            chunks
                .iter()
                .flat_map(|chunk| chunk.values().iter().copied()),
        )
        .map_err(overflow_error)
    }

    /// The memory address of each chunk's first value where the engine reads it, the
    /// witness for tests that the import copied nothing: for an unsliced array it equals
    /// the buffer address that PyArrow reports.
    #[pyfunction]
    fn arrow_values_addresses(values: AnyArray) -> PyResult<Vec<usize>> {
        let chunks = int64_chunks(values)?;
        Ok(chunks
            .iter()
            .map(|chunk| chunk.values().as_ptr().addr())
            .collect())
    }

    /// The engine's version, the system it was compiled for, and its build profile.
    #[pyfunction]
    fn build_details() -> BTreeMap<&'static str, &'static str> {
        let profile = if cfg!(debug_assertions) {
            "debug"
        } else {
            "release"
        };
        BTreeMap::from([
            ("version", env!("CARGO_PKG_VERSION")),
            ("target_os", std::env::consts::OS),
            ("target_arch", std::env::consts::ARCH),
            ("profile", profile),
        ])
    }

    fn int64_chunks(values: AnyArray) -> PyResult<Vec<PrimitiveArray<Int64Type>>> {
        let (chunks, field) = values.into_chunked_array()?.into_inner();
        let not_int64 = || {
            PyTypeError::new_err(format!(
                "Expected an int64 Arrow array, got {} in field {:?}",
                field.data_type(),
                field.name()
            ))
        };
        if field.data_type() != &Int64Type::DATA_TYPE {
            return Err(not_int64());
        }
        let chunks = chunks
            .iter()
            .map(|chunk| {
                chunk
                    .as_primitive_opt::<Int64Type>()
                    .cloned()
                    .ok_or_else(not_int64)
            })
            .collect::<PyResult<Vec<_>>>()?;
        let nulls: usize = chunks.iter().map(|chunk| chunk.null_count()).sum();
        if nulls > 0 {
            return Err(PyValueError::new_err(format!(
                "Expected an int64 Arrow array without nulls, got {nulls} nulls in field {:?}",
                field.name()
            )));
        }
        Ok(chunks)
    }

    fn overflow_error(overflow: DrawdownOverflow) -> PyErr {
        PyOverflowError::new_err(overflow.to_string())
    }
}
