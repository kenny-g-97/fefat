//! The hashes that key a run (step 2.10, `02` §4): an Arrow table's, which keys its signal
//! frame (`fefat_run::table_hash`), and the run key over the specification, the run's config,
//! that hash, and the data's hashes (`fefat_core::run_key`).

use pyo3::prelude::*;
use pyo3_arrow::PyTable;

use crate::{config_of, spec_of, value_error};

/// The hash of `table`, an Arrow table or stream such as a Polars frame: 64 lower-case
/// hexadecimal digits, alike however its rows are split into batches and on every system.
#[pyfunction]
pub fn table_hash(table: PyTable) -> PyResult<String> {
    let (batches, schema) = table.into_inner();
    fefat_run::table_hash::table_hash(&schema, &batches).map_err(value_error)
}

/// The run key of `spec_json` under `config_json` on the signal frame hashed
/// `signal_frame_hash`, reading the data hashed `partition_hashes`, by this build's versions.
#[pyfunction]
pub fn run_key(
    spec_json: &str,
    signal_frame_hash: &str,
    partition_hashes: Vec<String>,
    config_json: &str,
) -> PyResult<String> {
    let spec = spec_of(spec_json).map_err(value_error)?;
    let config = config_of(config_json).map_err(value_error)?;
    let key = fefat_core::run_key::run_key(&spec, &config, signal_frame_hash, &partition_hashes);
    Ok(key.map_err(value_error)?.as_str().to_owned())
}
