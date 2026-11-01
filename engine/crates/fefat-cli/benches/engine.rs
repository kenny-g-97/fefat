//! The engine's benchmarks (step 2.15, `02-engine-and-data.md` §4 and §8 item 7, D-68), on the
//! generated year of step 2.7 read from its engine cache: one signal strategy run over the year
//! recording its trades' paths, as every saved run records them; the same run recording none, as a
//! sweep's trials run; and 1,000 runs of its execution parameters over the year's first month on
//! Rayon's threads, as `fefat_engine.run_batch` runs a sweep. `just bench` (`scripts/bench.py`)
//! builds the year and names its contract's cache folder in `FEFAT_BENCH_CONTRACT`.

use std::cmp::Ordering;
use std::env;
use std::error::Error;
use std::iter;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use criterion::measurement::WallTime;
use criterion::{BenchmarkGroup, Criterion, SamplingMode};
use fefat_core::fidelity::Timeframe;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::market_data::MarketDataReader;
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::Price;
use fefat_data::{MappedContract, Month};
use fefat_engine::template::SignalRow;
use fefat_engine::tick_run::{Recording, Replay, RunOutputs};
use fefat_run::backtest::{BacktestError, run_template};
use fefat_run::config::RunConfig;
use rayon::prelude::*;

/// The runs' settings: ES filled on its trades under the specification's defaults, open around
/// the clock, from the default capital, with no fee table, as step 2.7 timed its runs.
const CONFIG: &str = r#"{"fidelity": "trades",
    "instrument": {"tick_size": 250000000, "money_per_point": 50000000, "lot_step": 1000000000},
    "settings": {"latency_ms": 100, "slippage_ticks": {"market": 1, "stop": 1},
        "limit_fill": "through", "roll_handling": "transfer"},
    "hours": {"kind": "always"}, "capital": 50000000000, "position": null}"#;

/// The stop and the target of the single runs, in ticks, as step 2.7 timed them.
const SINGLE_RUN: (u32, u32) = (16, 32);

/// The month the batch runs over.
const BATCH_MONTH: &str = "2026-01";

const FIVE_MINUTES: i64 = 300 * 1_000_000_000;

/// How many 5-minute closes back the close an entry compares with lies.
const LOOKBACK: usize = 12;

type Failure = Box<dyn Error>;

fn main() -> ExitCode {
    match bench() {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            eprintln!("{failure}");
            ExitCode::from(2)
        }
    }
}

/// Maps the year and its first month, then runs the benchmarks under criterion's arguments.
fn bench() -> Result<(), Failure> {
    let folder = contract_folder()?;
    let year = MappedContract::open(&folder)?;
    let month: Month = BATCH_MONTH.parse()?;
    let first_month = MappedContract::open_between(&folder, &[(month, month)])?;
    let config: RunConfig = serde_json::from_str(CONFIG)?;
    describe_year(&year)?;
    let mut criterion = Criterion::default().configure_from_args();
    single_runs(&mut criterion, &config, &year)?;
    batch(&mut criterion, &config, &first_month)?;
    criterion.final_summary();
    Ok(())
}

fn contract_folder() -> Result<PathBuf, Failure> {
    let folder = env::var_os("FEFAT_BENCH_CONTRACT").ok_or(
        "Expected FEFAT_BENCH_CONTRACT, the generated year's ESH2026 cache folder, got nothing: \
         run `just bench`",
    )?;
    Ok(PathBuf::from(folder))
}

/// Prints the year's trade dates and its records at each level, by which the write-up scales the
/// runs to the targets.
fn describe_year(year: &MappedContract) -> Result<(), Failure> {
    let (mut trades, mut seconds, mut minutes) = (0, 0, 0);
    for &trade_date in year.trade_dates() {
        trades += year.trades(trade_date)?.price.len();
        seconds += year.bars(trade_date, Timeframe::ONE_SECOND)?.close.len();
        minutes += year.bars(trade_date, Timeframe::ONE_MINUTE)?.close.len();
    }
    let dates = year.trade_dates().len();
    println!(
        "year: {dates} trade dates, {trades} trades, {seconds} 1-second bars, \
         {minutes} 1-minute bars"
    );
    Ok(())
}

/// The year's run recording its trades' paths, then recording none, each checked once before it
/// is timed.
fn single_runs(
    criterion: &mut Criterion,
    config: &RunConfig,
    year: &MappedContract,
) -> Result<(), Failure> {
    let spec = spec(SINGLE_RUN)?;
    let rows = signal_rows(year)?;
    println!("single_run: {} signal rows", rows.len());
    let mut group = criterion.benchmark_group("single_run");
    configure(&mut group, Duration::from_secs(20));
    let recordings = [
        ("with_paths", Recording::Paths),
        ("without_paths", Recording::TradesOnly),
    ];
    for (name, recording) in recordings {
        let run = || {
            run_template(
                config,
                Replay::Skipping,
                recording,
                &spec,
                rows.clone(),
                year,
            )
        };
        describe_run(name, &run()?);
        group.bench_function(name, |bencher| bencher.iter(&run));
    }
    group.finish();
    Ok(())
}

fn describe_run(name: &str, outputs: &RunOutputs) {
    let points: usize = outputs
        .trade_paths
        .iter()
        .map(|path| path.points.len())
        .sum();
    let (fills, trades) = (outputs.fills.len(), outputs.trades.len());
    println!("single_run/{name}: {fills} fills, {trades} trades, {points} path points");
}

/// 1,000 runs over the month, each with its own stop and target, checked once before they are
/// timed.
fn batch(
    criterion: &mut Criterion,
    config: &RunConfig,
    month: &MappedContract,
) -> Result<(), Failure> {
    let specs = batch_specs()?;
    let rows = signal_rows(month)?;
    let fills: usize = run_batch(config, &specs, &rows, month)?.iter().sum();
    println!(
        "batch: {} runs over {} trade dates on {} threads, {fills} fills in all",
        specs.len(),
        month.trade_dates().len(),
        rayon::current_num_threads()
    );
    let mut group = criterion.benchmark_group("batch");
    configure(&mut group, Duration::from_secs(30));
    group.bench_function("1000_runs_one_month", |bencher| {
        bencher.iter(|| run_batch(config, &specs, &rows, month));
    });
    group.finish();
    Ok(())
}

/// The fills of each run of `specs` over `month`, on Rayon's threads, each run's outputs dropped
/// on its thread, as a sweep keeps a trial's metrics alone.
fn run_batch(
    config: &RunConfig,
    specs: &[StrategySpec],
    rows: &[SignalRow],
    month: &MappedContract,
) -> Result<Vec<usize>, BacktestError> {
    let runs = specs.par_iter().map(|spec| {
        let recording = Recording::TradesOnly;
        let outputs = run_template(
            config,
            Replay::Skipping,
            recording,
            spec,
            rows.to_vec(),
            month,
        )?;
        Ok(outputs.fills.len())
    });
    runs.collect()
}

/// Ten samples of a flat count of runs each, measured over `measurement`: runs this long suit
/// criterion's flat sampling, not its default linear one.
fn configure(group: &mut BenchmarkGroup<'_, WallTime>, measurement: Duration) {
    group
        .sampling_mode(SamplingMode::Flat)
        .sample_size(10)
        .measurement_time(measurement);
}

/// Stops of 4 to 28 ticks, each with targets of 8 to 86 ticks in steps of 2: 25 by 40.
fn batch_specs() -> Result<Vec<StrategySpec>, Failure> {
    let targets = (8..=86).step_by(2);
    let specs = (4..=28).flat_map(|stop| targets.clone().map(move |target| spec((stop, target))));
    Ok(specs.collect::<Result<_, _>>()?)
}

/// The template of step 2.7's timed runs: a market entry of one lot deciding on 5-minute closes,
/// with its stop and its target the given ticks away.
fn spec((stop, target): (u32, u32)) -> Result<StrategySpec, serde_json::Error> {
    serde_json::from_value(serde_json::json!({
        "spec_version": 1, "instrument": "ES", "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "ticks", "ticks": stop},
            "targets": [{"price": {"kind": "ticks", "ticks": target}}],
            "sizing": {"kind": "fixed", "units": 1}
        }
    }))
}

/// A 5-minute bar's close: its trade date, its instant, and its last 1-minute bar's close.
#[derive(Clone, Copy)]
struct FiveMinuteClose {
    trade_date: TradeDate,
    ts_close: Ts,
    close: Price,
}

/// The signal rows of step 2.7's timed runs over `reader`'s 1-minute bars: at each 5-minute
/// close, a long entry where the close is above the one `LOOKBACK` closes before, a short entry
/// where it is below.
fn signal_rows(reader: &impl MarketDataReader) -> Result<Vec<SignalRow>, Failure> {
    let closes = five_minute_closes(reader)?;
    let earlier = iter::repeat_n(None, LOOKBACK).chain(closes.iter().map(Some));
    let rows = closes.iter().zip(earlier).map(|(bar, earlier)| {
        let change = earlier.map(|earlier: &FiveMinuteClose| bar.close.cmp(&earlier.close));
        SignalRow {
            trade_date: Some(bar.trade_date),
            long_entry: change == Some(Ordering::Greater),
            short_entry: change == Some(Ordering::Less),
            ..SignalRow::at(bar.ts_close)
        }
    });
    Ok(rows.collect())
}

/// Each 5-minute bar's close over `reader`'s trade dates, from the 1-minute bars inside it, as
/// the 2.07 notebook groups them.
fn five_minute_closes(reader: &impl MarketDataReader) -> Result<Vec<FiveMinuteClose>, Failure> {
    let mut closes: Vec<FiveMinuteClose> = Vec::new();
    for &trade_date in reader.trade_dates() {
        let bars = reader.bars(trade_date, Timeframe::ONE_MINUTE)?;
        for (ts_open, &close) in bars.ts_open.iter().zip(bars.close) {
            let ts_close = Ts((ts_open.0.div_euclid(FIVE_MINUTES) + 1) * FIVE_MINUTES);
            let bar = FiveMinuteClose {
                trade_date,
                ts_close,
                close,
            };
            match closes.last_mut() {
                Some(last) if last.ts_close == ts_close => *last = bar,
                _ => closes.push(bar),
            }
        }
    }
    Ok(closes)
}
