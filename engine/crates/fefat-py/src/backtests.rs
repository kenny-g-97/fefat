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
use fefat_data::{FrontSequence, MappedContract, Month};
use fefat_engine::template::SignalRow;
use fefat_engine::tick_run::{FidelityEra, Replay, RunOutputs};
use fefat_run::artifacts::{run_tables, untagged};
use fefat_run::backtest::run_template;
use fefat_run::config::RunConfig;
use fefat_run::signal_rows::signal_rows_of;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3_arrow::PyTable;
use rayon::prelude::*;

use crate::{config_of, spec_of, value_error};

/// A backtest's inputs as Python gives them: its specification as JSON, its signal frame as
/// Arrow, the folders of its fronts' caches in the order it trades them, and its config as JSON.
type BacktestArguments = (String, PyTable, Vec<PathBuf>, String);

/// Runs the execution template of `spec_json` over `signal_frame` on the caches in `cache_paths`,
/// one per front in the order the run trades them, as `config_json` says, replayed as `replay`
/// says, `skipping` or `full`: its tables, `fills`, `orders`, `log`, `costs`, `trades`, and
/// `equity`, and its `summary`, the lots held at the end, the cash, the ambiguous fills, and the
/// fidelity eras of its trade dates (`02` §1.6).
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
    let backtest = Backtest::read(spec_json, signal_frame, cache_paths, config_json)
        .map_err(PyValueError::new_err)?;
    let caches = mapped(backtest.spans())?;
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
        .enumerate()
        .map(|(case, (spec, frame, folders, config))| {
            Backtest::read(&spec, frame, folders, &config).map_err(|error| failed(case, &error))
        })
        .collect::<PyResult<Vec<_>>>()?;
    let caches = mapped(backtests.iter().flat_map(Backtest::spans))?;
    let runs: Vec<Result<RunOutputs, String>> = py.detach(|| {
        let runs = backtests.into_par_iter();
        runs.map(|backtest| backtest.run(&caches, replay)).collect()
    });
    runs.into_iter()
        .enumerate()
        .map(|(case, run)| run_of(py, run.map_err(|error| failed(case, &error))?))
        .collect()
}

/// The case at `case` of a batch, which `error` stops.
fn failed(case: usize, error: &str) -> PyErr {
    PyValueError::new_err(format!(
        "Expected case {case} of the batch to run, got: {error}"
    ))
}

/// A backtest read from Python, before it runs: its trade dates from `first` to `last`, those
/// of its signal rows, and its fronts' folders in the order it trades them.
struct Backtest {
    spec: StrategySpec,
    rows: Vec<SignalRow>,
    folders: Vec<PathBuf>,
    config: RunConfig,
    first: TradeDate,
    last: TradeDate,
}

impl Backtest {
    fn read(
        spec_json: &str,
        signal_frame: PyTable,
        folders: Vec<PathBuf>,
        config_json: &str,
    ) -> Result<Self, String> {
        let spec = spec_of(spec_json)?;
        let config = config_of(config_json)?;
        let (batches, _) = signal_frame.into_inner();
        let mut rows = Vec::new();
        for batch in &batches {
            rows.extend(signal_rows_of(batch).map_err(|error| error.to_string())?);
        }
        let fronts = config.fronts_from().len() + 1;
        if folders.len() != fronts {
            return Err(format!(
                "Expected a cache folder of the first front and one per roll, {fronts}, got {}",
                folders.len()
            ));
        }
        let (first, last) = window(&rows)?;
        Ok(Self {
            spec,
            rows,
            folders,
            config,
            first,
            last,
        })
    }

    /// Each front's folder and the first and last month of the trade dates it serves: the first
    /// front's from the window's start, each later one's from its roll's trade date, to the day
    /// before the next roll's or the window's end.
    fn spans(&self) -> Vec<(PathBuf, Month, Month)> {
        let rolls: Vec<TradeDate> = self
            .config
            .fronts_from()
            .into_iter()
            .map(|(on, _)| on)
            .collect();
        let starts = std::iter::once(self.first).chain(rolls.iter().copied());
        let ends = rolls
            .iter()
            .map(|on| TradeDate(on.0 - 1))
            .chain([self.last]);
        let spans = self.folders.iter().zip(starts.zip(ends));
        spans
            .map(|(folder, (from, until))| {
                let (from, until) = (from.max(self.first), until.min(self.last));
                (folder.clone(), Month::of(from), Month::of(until.max(from)))
            })
            .collect()
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
        let rolls = self.config.fronts_from();
        let reader = FrontSequence::new(&fronts, &rolls, self.first, self.last);
        let reader = reader.map_err(|error| error.to_string())?;
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

/// Each folder of `spans` mapped once, over the months its spans name alone, so that a run, or a
/// batch of runs, maps the months it reads and none between them.
fn mapped(
    spans: impl IntoIterator<Item = (PathBuf, Month, Month)>,
) -> PyResult<BTreeMap<PathBuf, MappedContract>> {
    let mut months: BTreeMap<PathBuf, Vec<(Month, Month)>> = BTreeMap::new();
    for (folder, first, last) in spans {
        months.entry(folder).or_default().push((first, last));
    }
    months
        .into_iter()
        .map(|(folder, spans)| {
            let cache = MappedContract::open_between(&folder, &spans).map_err(value_error)?;
            Ok((folder, cache))
        })
        .collect()
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
    summary.set_item("eras", eras_of(py, &outputs.eras)?)?;
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

/// Each fidelity era as a dict of its first and last trade date (`2026-03-05`), its count of
/// trade dates, and its level as the fidelity type spells it (`trades`, `1m`).
fn eras_of<'py>(py: Python<'py>, eras: &[FidelityEra]) -> PyResult<Vec<Bound<'py, PyDict>>> {
    eras.iter()
        .map(|era| {
            let dict = PyDict::new(py);
            dict.set_item("first", era.first.to_string())?;
            dict.set_item("last", era.last.to_string())?;
            dict.set_item("trade_dates", era.trade_dates)?;
            dict.set_item("fidelity", era.fidelity.to_string())?;
            Ok(dict)
        })
        .collect()
}
