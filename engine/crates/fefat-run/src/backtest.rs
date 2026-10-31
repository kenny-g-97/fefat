//! A run assembled from its config, how it replays its records and what it records of its trades'
//! paths, a reader of them, and its strategy (steps 2.10 and 2.13): the instrument's parameters,
//! the ledger it starts from, its trading hours, its settings, its fee table and funding rates, and
//! its rolls, given to the tick loop (`fefat_engine::tick_run::TickRun`), which runs to the end of
//! its records.

use fefat_core::costs::FeeTableError;
use fefat_core::instrument::NonPositiveParameter;
use fefat_core::ledger::LedgerError;
use fefat_core::market_data::MarketDataReader;
use fefat_core::strategy_spec::StrategySpec;
use fefat_engine::strategy::Strategy;
use fefat_engine::template::{SignalRow, TemplateError, TemplateStrategy};
use fefat_engine::tick_run::{Recording, Replay, RunError, RunOutputs, TickRun};
use thiserror::Error;

use crate::config::RunConfig;

/// What stopped a backtest before or while it ran.
#[derive(Debug, Error)]
pub enum BacktestError {
    /// Its instrument's parameters.
    #[error(transparent)]
    Instrument(#[from] NonPositiveParameter),
    /// Its opening position.
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    /// Its fee table.
    #[error(transparent)]
    Fees(#[from] FeeTableError),
    /// Its specification or its signal rows.
    #[error(transparent)]
    Template(#[from] TemplateError),
    /// The run.
    #[error(transparent)]
    Run(#[from] RunError),
}

/// Runs `strategy` over `reader` as `config` says, replayed as `replay` says, recording of its
/// trades' paths what `recording` says (step 2.13).
pub fn run_strategy<R: MarketDataReader>(
    config: &RunConfig,
    replay: Replay,
    recording: Recording,
    reader: &R,
    strategy: &mut dyn Strategy,
) -> Result<RunOutputs, BacktestError> {
    let instrument = config.instrument()?;
    let ledger = config.ledger(instrument)?;
    let (hours, settings) = (config.hours(), config.settings());
    let fidelity = config.fidelity;
    let run = TickRun::new(reader, fidelity, replay, &hours, settings, ledger, strategy)?;
    let run = run.with_costs(config.costs()?)?;
    let run = run.with_rolls(config.rolls(), config.roll_handling())?;
    Ok(run.with_recording(recording).run()?)
}

/// Runs the execution template of `spec` over `rows`, its signal rows, on `reader`, replayed and
/// recorded as `run_strategy` takes them.
pub fn run_template<R: MarketDataReader>(
    config: &RunConfig,
    replay: Replay,
    recording: Recording,
    spec: &StrategySpec,
    rows: Vec<SignalRow>,
    reader: &R,
) -> Result<RunOutputs, BacktestError> {
    let mut strategy = TemplateStrategy::new(spec, rows, &config.instrument()?)?;
    run_strategy(config, replay, recording, reader, &mut strategy)
}
