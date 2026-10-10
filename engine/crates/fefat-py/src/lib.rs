//! PyO3 bindings: the Python module fefat_engine.

use pyo3::prelude::*;

/// The FEFAT engine, compiled from Rust.
#[pymodule]
mod fefat_engine {
    use std::collections::BTreeMap;

    use arrow_array::cast::AsArray;
    use arrow_array::types::{ArrowPrimitiveType, Int64Type};
    use arrow_array::{Array, PrimitiveArray};
    use fefat_core::drawdown::{self, DrawdownOverflow};
    use pyo3::exceptions::{PyOverflowError, PyTypeError, PyValueError};
    use pyo3::prelude::*;
    use pyo3_arrow::input::AnyArray;

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
