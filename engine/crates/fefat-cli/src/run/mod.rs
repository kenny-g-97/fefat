//! `fefat-cli run <input folder> <output folder>` (steps 2.6 and 2.7): a batch of cases through
//! the engine in one process, so that the differential test drives thousands of tapes through few
//! invocations. The input folder holds `run.json`, which lists the cases ([`manifest`]), and the
//! Arrow IPC files of their records and signal rows, a file per level such as `trades.arrow`,
//! `tbbo.arrow`, or `1m.arrow`, and `signals.arrow`, each row tagged with its case's place in that
//! list ([`inputs`]). A case reads its records from those files, through the in-memory reader, or
//! from an engine cache's contract folder (step 2.5), in full or skipping what no order can act
//! on. The output folder receives `fills.arrow`, `orders.arrow`, `log.arrow`, and `ledger.arrow`,
//! tagged the same way ([`outputs`]).

mod inputs;
mod manifest;
mod outputs;
#[cfg(test)]
mod tests;

use std::fs;
use std::path::{Path, PathBuf};

use arrow_schema::ArrowError;
use fefat_core::fidelity::Fidelity;
use fefat_core::instrument::{Contract, NonPositiveParameter};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::{InMemoryMarketData, MarketDataReader, TapeError};
use fefat_data::{CacheError, MappedContract};
use fefat_engine::hours::TradingHours;
use fefat_engine::settings::RunSettings;
use fefat_engine::strategy::{ScenarioOrders, Strategy};
use fefat_engine::template::{TemplateError, TemplateStrategy};
use fefat_engine::tick_run::{Replay, RunError, RunOutputs, TickRun};
use thiserror::Error;

use inputs::BatchTables;
use manifest::{
    CaseManifest, DecisionsManifest, MarketDataManifest, MispricedOrder, RepeatedOrderId,
    RunManifest, with_distinct_ids,
};

/// What stopped a batch.
#[derive(Debug, Error)]
pub enum BatchError {
    /// A file or a folder that could not be read or written.
    #[error("Expected to {action} {}, got: {source}", path.display())]
    Io {
        /// What was done.
        action: &'static str,
        /// To what.
        path: PathBuf,
        /// Why it failed.
        source: std::io::Error,
    },
    /// A `run.json` that lists no cases the batch can read.
    #[error("Expected {} to list the cases of a batch, got: {source}", path.display())]
    Manifest {
        /// The file.
        path: PathBuf,
        /// What serde found.
        source: serde_json::Error,
    },
    /// An Arrow file that could not be read or written.
    #[error("Expected Arrow IPC in {}, got: {source}", path.display())]
    Arrow {
        /// The file.
        path: PathBuf,
        /// What Arrow found.
        source: ArrowError,
    },
    /// A table without the columns a batch reads.
    #[error("Expected {expected} in {}, got {actual}", path.display())]
    Table {
        /// The file.
        path: PathBuf,
        /// What it should hold.
        expected: String,
        /// What it holds.
        actual: String,
    },
    /// A case's records that the cache's reader refuses.
    #[error(transparent)]
    Records(#[from] CacheError),
    /// A case that did not run.
    #[error("Expected case {case} to run, got: {source}")]
    Case {
        /// The case's id.
        case: String,
        /// Why it did not.
        source: CaseError,
    },
}

/// Why a case did not run.
#[derive(Debug, Error)]
pub enum CaseError {
    /// Its instrument's parameters.
    #[error(transparent)]
    Instrument(#[from] NonPositiveParameter),
    /// Its opening position.
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    /// An order of its scenario.
    #[error(transparent)]
    Order(#[from] MispricedOrder),
    /// Two of its orders under one id.
    #[error(transparent)]
    RepeatedOrder(#[from] RepeatedOrderId),
    /// Its specification or its signal rows.
    #[error(transparent)]
    Template(#[from] TemplateError),
    /// Its tape.
    #[error(transparent)]
    Tape(#[from] TapeError),
    /// Its records, from the batch's files or from a cache.
    #[error(transparent)]
    Records(#[from] Box<BatchError>),
    /// The run.
    #[error(transparent)]
    Run(#[from] RunError),
}

/// What a batch ran.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BatchSummary {
    /// The cases run.
    pub cases: usize,
    /// Their fills, all told.
    pub fills: usize,
    /// Their fills flagged ambiguous (F-BAR-05).
    pub ambiguous_fills: usize,
}

/// Runs the batch in `input` and writes its outputs into `output`.
pub fn run_batch(input: &Path, output: &Path) -> Result<BatchSummary, BatchError> {
    let manifest_path = input.join("run.json");
    let text = fs::read_to_string(&manifest_path).map_err(|source| BatchError::Io {
        action: "read",
        path: manifest_path.clone(),
        source,
    })?;
    let manifest: RunManifest =
        serde_json::from_str(&text).map_err(|source| BatchError::Manifest {
            path: manifest_path,
            source,
        })?;
    let tables = BatchTables::read(input, &manifest)?;
    let mut runs = Vec::with_capacity(manifest.cases.len());
    for (index, case) in (0_i64..).zip(&manifest.cases) {
        let run = run_case(case, index, &tables).map_err(|source| BatchError::Case {
            case: case.id.clone(),
            source,
        })?;
        runs.push((index, run));
    }
    fs::create_dir_all(output).map_err(|source| BatchError::Io {
        action: "create",
        path: output.to_path_buf(),
        source,
    })?;
    outputs::write_outputs(output, &runs)?;
    let fills = runs.iter().map(|(_, run)| run.fills.len()).sum();
    let ambiguous_fills = runs.iter().map(|(_, run)| run.ambiguous_fills()).sum();
    Ok(BatchSummary {
        cases: runs.len(),
        fills,
        ambiguous_fills,
    })
}

fn run_case(
    case: &CaseManifest,
    index: i64,
    tables: &BatchTables,
) -> Result<RunOutputs, CaseError> {
    let instrument = case.instrument()?;
    let ledger = case.ledger(instrument)?;
    let (hours, settings) = (case.hours(), case.settings());
    let mut strategy: Box<dyn Strategy> = match &case.decisions {
        DecisionsManifest::Orders { orders } => {
            let placed = orders.iter().map(|order| order.scenario_order());
            let placed = with_distinct_ids(placed.collect::<Result<_, _>>()?)?;
            Box::new(ScenarioOrders::new(placed))
        }
        DecisionsManifest::Template { strategy } => {
            let rows = tables.signal_rows(index);
            Box::new(TemplateStrategy::new(strategy, rows, &instrument)?)
        }
    };
    let run = Run {
        fidelity: case.fidelity,
        replay: case.replay(),
        hours: &hours,
        settings,
        ledger,
    };
    match &case.market_data {
        MarketDataManifest::Tape { levels } => {
            let days = tables.tape_days(index, levels).map_err(Box::new)?;
            let reader = InMemoryMarketData::new(Contract(case.contract.clone()), days)?;
            run.on(&reader, strategy.as_mut())
        }
        MarketDataManifest::Cache { folder } => {
            let reader = MappedContract::open(folder)
                .map_err(|error| Box::new(BatchError::Records(error)))?;
            run.on(&reader, strategy.as_mut())
        }
    }
}

/// A case's run but for its records and its strategy.
struct Run<'case> {
    fidelity: Fidelity,
    replay: Replay,
    hours: &'case TradingHours,
    settings: RunSettings,
    ledger: Ledger,
}

impl Run<'_> {
    fn on(
        self,
        reader: &impl MarketDataReader,
        strategy: &mut dyn Strategy,
    ) -> Result<RunOutputs, CaseError> {
        let Self {
            fidelity,
            replay,
            hours,
            settings,
            ledger,
        } = self;
        let run = TickRun::new(reader, fidelity, replay, hours, settings, ledger, strategy)?;
        Ok(run.run()?)
    }
}

/// An Arrow error as the batch's error about the file at `path`.
fn arrow_error(path: &Path) -> impl Fn(ArrowError) -> BatchError + '_ {
    move |source| BatchError::Arrow {
        path: path.to_path_buf(),
        source,
    }
}
