//! PyO3 bindings: the Python module fefat_engine.

use pyo3::prelude::*;

/// The FEFAT engine, compiled from Rust.
#[pymodule]
mod fefat_engine {}
