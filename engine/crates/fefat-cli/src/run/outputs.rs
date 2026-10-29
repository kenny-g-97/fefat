//! The Arrow IPC files a batch writes, each row tagged with its case's place in `run.json`: the
//! tables of `fefat_run::artifacts` (the fills, each with the contract it is of, the orders in
//! their last state, the event log, and the cost lines) and each case's ledger at its end, in
//! Arrow IPC's file format, uncompressed, which Polars' `read_ipc` reads.

use std::fs::File;
use std::io::BufWriter;
use std::path::Path;
use std::sync::Arc;

use arrow_array::{ArrayRef, Int64Array, RecordBatch};
use arrow_ipc::writer::FileWriter;
use arrow_schema::ArrowError;
use fefat_engine::tick_run::RunOutputs;
use fefat_run::artifacts::{CASE_COLUMN, batch, run_tables};

use super::{BatchError, arrow_error};

/// Writes each table of `fefat_run::artifacts`, as `<name>.arrow`, and `ledger.arrow` into
/// `output`.
pub(super) fn write_outputs(output: &Path, runs: &[(i64, RunOutputs)]) -> Result<(), BatchError> {
    let mut written = run_tables(runs).map_err(arrow_error(output))?;
    written.push(("ledger", ledger_batch(runs).map_err(arrow_error(output))?));
    for (name, table) in written {
        write_ipc(&output.join(format!("{name}.arrow")), &table)?;
    }
    Ok(())
}

/// Each case's ledger at its end, the lots it holds, positive long, and its cash in micro-units,
/// and the fills it flagged ambiguous, which the run counts (F-BAR-05).
fn ledger_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let int = |value: fn(&(i64, RunOutputs)) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(runs.iter().map(value)))
    };
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        (
            "position",
            int(|(_, run)| run.ledger.position().signed_lots().0),
        ),
        ("cash", int(|(_, run)| run.ledger.cash().0)),
        (
            "ambiguous_fills",
            int(|(_, run)| run.ambiguous_fills() as i64),
        ),
    ])
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
