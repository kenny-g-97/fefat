//! Backtests through the bindings (step 2.10): one signal strategy's run, or a batch of them on
//! Rayon's threads, each run on one thread over caches mapped once and shared by all (`02` §4),
//! with the interpreter released while they run (`02` §5). A run reads its specification and its
//! config as JSON (`fefat_run::config`), its signal frame as Arrow (`fefat_run::signal_rows`),
//! and its fronts' engine caches, in the order it trades them (`fefat_data::FrontSequence`); it
//! returns its tables as Arrow (`fefat_run::artifacts`) and a summary of its end.

use std::collections::BTreeMap;
use std::path::PathBuf;

use fefat_core::instants::TradeDate;
use fefat_core::strategy_spec::StrategySpec;
use fefat_data::{FrontSequence, MappedContract};
use fefat_engine::template::SignalRow;
use fefat_engine::tick_run::{Replay, RunOutputs};
use fefat_run::artifacts::{run_tables, untagged};
use fefat_run::backtest::run_template;
use fefat_run::config::RunConfig;
use fefat_run::signal_rows::signal_rows_of;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3_arrow::PyTable;
use rayon::prelude::*;

use crate::value_error;

/// A backtest's inputs as Python gives them: its specification as JSON, its signal frame as
/// Arrow, the folders of its fronts' caches in the order it trades them, and its config as JSON.
type BacktestArguments = (String, PyTable, Vec<PathBuf>, String);

/// Runs the execution template of `spec_json` over `signal_frame` on the caches in `cache_paths`,
/// one per front in the order the run trades them, as `config_json` says, replayed as `replay`
/// says, `skipping` or `full`: its tables, `fills`, `orders`, `log`, `costs`, `trades`, and
/// `equity`, and its `summary`, the lots held at the end, the cash, and the ambiguous fills.
#[pyfunction]
#[pyo3(signature = (spec_json, signal_frame, cache_paths, config_json, replay = "skipping"))]
pub fn run_signal_backtest<'py>(
    py: Python<'py>,
    spec_json: &str,
    signal_frame: PyTable,
    cache_paths: Vec<PathBuf>,
    config_json: &str,
    replay: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let replay = replay_of(replay)?;
    let backtest = Backtest::read(spec_json, signal_frame, cache_paths, config_json)?;
    let caches = mapped(backtest.folders.iter())?;
    let outputs = py.detach(|| backtest.run(&caches, replay));
    run_of(py, outputs.map_err(PyValueError::new_err)?)
}

/// Runs each case of `cases`, `(spec_json, signal_frame, cache_paths, config_json)` as
/// `run_signal_backtest` takes them, on Rayon's threads, each cache mapped once and shared, with
/// the interpreter released: each run as `run_signal_backtest` gives it, in the order of
/// `cases`; a case that does not run stops the batch with its place.
#[pyfunction]
#[pyo3(signature = (cases, replay = "skipping"))]
pub fn run_batch<'py>(
    py: Python<'py>,
    cases: Vec<BacktestArguments>,
    replay: &str,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let replay = replay_of(replay)?;
    let backtests = cases
        .into_iter()
        .map(|(spec, frame, folders, config)| Backtest::read(&spec, frame, folders, &config))
        .collect::<PyResult<Vec<_>>>()?;
    let caches = mapped(
        backtests
            .iter()
            .flat_map(|backtest| backtest.folders.iter()),
    )?;
    let runs: Vec<Result<RunOutputs, String>> = py.detach(|| {
        let runs = backtests.into_par_iter();
        runs.map(|backtest| backtest.run(&caches, replay)).collect()
    });
    runs.into_iter()
        .enumerate()
        .map(|(case, run)| {
            let outputs = run.map_err(|error| {
                PyValueError::new_err(format!(
                    "Expected case {case} of the batch to run, got: {error}"
                ))
            })?;
            run_of(py, outputs)
        })
        .collect()
}

/// A backtest read from Python, before it runs.
struct Backtest {
    spec: StrategySpec,
    rows: Vec<SignalRow>,
    folders: Vec<PathBuf>,
    config: RunConfig,
}

impl Backtest {
    fn read(
        spec_json: &str,
        signal_frame: PyTable,
        folders: Vec<PathBuf>,
        config_json: &str,
    ) -> PyResult<Self> {
        let spec: StrategySpec = serde_json::from_str(spec_json).map_err(|error| {
            value_error(format!(
                "Expected a strategy specification as JSON, got: {error}"
            ))
        })?;
        let config: RunConfig = serde_json::from_str(config_json).map_err(|error| {
            value_error(format!("Expected a run's config as JSON, got: {error}"))
        })?;
        let (batches, _) = signal_frame.into_inner();
        let mut rows = Vec::new();
        for batch in &batches {
            rows.extend(signal_rows_of(batch).map_err(value_error)?);
        }
        Ok(Self {
            spec,
            rows,
            folders,
            config,
        })
    }

    /// The run over the fronts' caches, `caches` holding each folder mapped.
    fn run(
        self,
        caches: &BTreeMap<PathBuf, MappedContract>,
        replay: Replay,
    ) -> Result<RunOutputs, String> {
        let fronts = self
            .folders
            .iter()
            .map(|folder| {
                caches
                    .get(folder)
                    .ok_or_else(|| format!("Expected the cache of {} mapped", folder.display()))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let (first, last) = window(&self.rows)?;
        let rolls = self.config.fronts_from();
        let reader = FrontSequence::new(&fronts, &rolls, first, last).map_err(|e| e.to_string())?;
        run_template(&self.config, replay, &self.spec, self.rows, &reader)
            .map_err(|error| error.to_string())
    }
}

/// The first and the last trade date of the signal rows, which the run replays: every row
/// must name its trade date.
fn window(rows: &[SignalRow]) -> Result<(TradeDate, TradeDate), String> {
    let dates: Option<Vec<TradeDate>> = rows.iter().map(|row| row.trade_date).collect();
    let dates = dates.ok_or("Expected a trade_date on every signal row, got a row without one")?;
    match (dates.iter().min(), dates.iter().max()) {
        (Some(&first), Some(&last)) => Ok((first, last)),
        _ => Err("Expected signal rows to replay, got none".to_owned()),
    }
}

/// Each folder of `folders` mapped once.
fn mapped<'folder>(
    folders: impl Iterator<Item = &'folder PathBuf>,
) -> PyResult<BTreeMap<PathBuf, MappedContract>> {
    let mut caches = BTreeMap::new();
    for folder in folders {
        if caches.contains_key(folder) {
            continue;
        }
        let cache = MappedContract::open(folder).map_err(value_error)?;
        caches.insert(folder.clone(), cache);
    }
    Ok(caches)
}

fn replay_of(replay: &str) -> PyResult<Replay> {
    match replay {
        "skipping" => Ok(Replay::Skipping),
        "full" => Ok(Replay::Full),
        other => Err(value_error(format!(
            "Expected a replay of skipping or full, got {other:?}"
        ))),
    }
}

/// A run's tables, each without the `case` column a batch's carry, and its summary.
fn run_of(py: Python<'_>, outputs: RunOutputs) -> PyResult<Bound<'_, PyDict>> {
    let summary = PyDict::new(py);
    summary.set_item("position", outputs.ledger.position().signed_lots().0)?;
    summary.set_item("cash", outputs.ledger.cash().0)?;
    summary.set_item("ambiguous_fills", outputs.ambiguous_fills())?;
    let run = PyDict::new(py);
    for (name, table) in run_tables(&[(0, outputs)]).map_err(value_error)? {
        let table = untagged(table).map_err(value_error)?;
        let schema = table.schema();
        run.set_item(
            name,
            Bound::new(py, PyTable::try_new(vec![table], schema)?)?,
        )?;
    }
    run.set_item("summary", summary)?;
    Ok(run)
}
