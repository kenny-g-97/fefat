//! The determinism harness (step 2.4, D-11): one digest of everything the engine computes from a
//! seeded tape, the records and offsets its in-memory reader serves, the ledger after a seeded
//! run of fills and marks, the orders, fills, and event log of the loop on its trades and TBBO
//! records with seeded orders (step 2.6) and on its bars, in full and skipping (step 2.7), each
//! paying a fee table and funding and rolling once (step 2.9), and a
//! run key, so that two runs, two processes, and Windows and Linux can be compared by one BLAKE3
//! hash. No wall clock, no hash map, and integers alone. `just regenerate-goldens` writes its
//! golden manifest.

use fefat_core::costs::FeeTableError;
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::{Fill, FillFlags, Liquidity, PricingRule};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep, NonPositiveParameter};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::{InMemoryMarketData, MarketDataError, MarketDataReader, TapeError};
use fefat_core::orders::{OrderId, OrderRole, Side};
use fefat_core::run_key::{
    ARTIFACT_SCHEMA_VERSION, ENGINE_VERSION, FILL_MODEL_VERSION, RunKeyError, run_key,
};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, Overflow, PRICE_UNITS, Price, Qty};
use fefat_engine::template::TemplateError;
use fefat_engine::tick_run::RunError;
use fefat_run::config::RunConfig;
use serde::Serialize;
use thiserror::Error;

use crate::seeded_tape::{SEEDED_CONTRACT, SEEDED_TRADE_DATE, SplitMix64, TICK, seeded_tape};
use loop_run::loop_run_hash;

mod loop_run;

const DOMAIN: &[u8] = b"fefat determinism 8\n";
/// The example specification of `02-engine-and-data.md` §2.1, the run key's spec.
const EXAMPLE_SPEC: &str = r#"{"spec_version": 1, "instrument": "ES", "timeframe": "5m",
    "execution": {"entry": {"kind": "market"}, "sizing": {"kind": "fixed", "units": 1}}}"#;
/// The run key's settings: a run of the seeded tape's trades of ES under the specification's
/// defaults, open around the clock, from the default capital (`fefat_run::config::RunConfig`).
const EXAMPLE_CONFIG: &str = r#"{"fidelity": "trades",
    "instrument": {"tick_size": 250000000, "money_per_point": 50000000, "lot_step": 1000000000},
    "settings": {"latency_ms": 100, "slippage_ticks": {"market": 1, "stop": 1},
        "limit_fill": "through", "roll_handling": "transfer"},
    "hours": {"kind": "always"}, "capital": 50000000000, "position": null}"#;
/// Every tenth trade of the seeded tape is a fill.
const TRADES_PER_FILL: usize = 10;

/// What stopped the harness.
#[derive(Debug, Error)]
pub enum DeterminismError {
    /// The seeded tape broke a rule of the in-memory reader.
    #[error(transparent)]
    Tape(#[from] TapeError),
    /// The reader could not serve what the harness asked for.
    #[error(transparent)]
    MarketData(#[from] MarketDataError),
    /// The ledger refused a seeded fill.
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    /// The instrument's parameters were refused.
    #[error(transparent)]
    Instrument(#[from] NonPositiveParameter),
    /// The run key could not be worked out.
    #[error(transparent)]
    RunKey(#[from] RunKeyError),
    /// The example specification did not read, or the manifest did not write.
    #[error("Expected JSON serde reads and writes, got: {0}")]
    Json(#[from] serde_json::Error),
    /// The tick loop refused the seeded run.
    #[error(transparent)]
    Run(#[from] RunError),
    /// A seeded order's price beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
    /// The seeded template was refused.
    #[error(transparent)]
    Template(#[from] TemplateError),
    /// The seeded fee table was refused.
    #[error(transparent)]
    Fees(#[from] FeeTableError),
}

/// The digest of `seed`: 64 lower-case hexadecimal digits of BLAKE3.
pub fn digest(seed: u64) -> Result<String, DeterminismError> {
    let mut generator = SplitMix64::new(seed);
    let contract = Contract(SEEDED_CONTRACT.to_owned());
    let reader = InMemoryMarketData::new(contract, seeded_tape(&mut generator))?;
    let records_digest = market_data_hash(&reader)?;
    let ledger_run_digest = ledger_run_hash(&reader, &mut generator)?;
    let loop_run_digest = loop_run_hash(&reader, &mut generator)?;
    let spec: StrategySpec = serde_json::from_str(EXAMPLE_SPEC)?;
    let config: RunConfig = serde_json::from_str(EXAMPLE_CONFIG)?;
    let partitions = [records_digest.to_hex().to_string()];
    let key = run_key(&spec, &config, &ledger_run_digest.to_hex(), &partitions)?;
    let mut hasher = blake3::Hasher::new();
    hasher.update(DOMAIN);
    hasher.update(records_digest.as_bytes());
    hasher.update(ledger_run_digest.as_bytes());
    hasher.update(loop_run_digest.as_bytes());
    hasher.update(key.as_str().as_bytes());
    Ok(hasher.finalize().to_hex().to_string())
}

/// ES's instrument parameters: a tick of 0.25, 50 USD a point, and lots of one contract.
fn es() -> Result<InstrumentParameters, NonPositiveParameter> {
    InstrumentParameters::new(Price(TICK), Money(50 * MONEY_UNITS), LotStep(PRICE_UNITS))
}

/// The golden manifest of `seed`'s digest, as the `engine-golden` skill describes it: the
/// command, the versions, the inputs (a seed, no fixture), and the output.
pub fn golden_manifest(seed: u64, digest: &str) -> Result<String, DeterminismError> {
    let manifest = GoldenManifest {
        command: format!("cargo run -p fefat-cli -- determinism {seed}"),
        versions: GoldenVersions {
            engine: ENGINE_VERSION.0,
            fill_model: FILL_MODEL_VERSION.0,
            artifact_schema: ARTIFACT_SCHEMA_VERSION.0,
        },
        inputs: GoldenInputs { seed },
        outputs: GoldenOutputs { digest },
    };
    Ok(serde_json::to_string_pretty(&manifest)? + "\n")
}

#[derive(Serialize)]
struct GoldenManifest<'digest> {
    command: String,
    versions: GoldenVersions,
    inputs: GoldenInputs,
    outputs: GoldenOutputs<'digest>,
}

#[derive(Serialize)]
struct GoldenVersions {
    engine: u32,
    fill_model: u32,
    artifact_schema: u32,
}

#[derive(Serialize)]
struct GoldenInputs {
    seed: u64,
}

#[derive(Serialize)]
struct GoldenOutputs<'digest> {
    digest: &'digest str,
}

/// BLAKE3 over every column of every level and every offsets table the reader serves, in the
/// order of its trade dates and levels.
fn market_data_hash(reader: &impl MarketDataReader) -> Result<blake3::Hash, MarketDataError> {
    let mut hasher = blake3::Hasher::new();
    for &trade_date in reader.trade_dates() {
        hasher.update(&trade_date.0.to_le_bytes());
        let levels = reader.levels(trade_date)?;
        for &level in levels {
            hasher.update(level.to_string().as_bytes());
            hash_level(&mut hasher, reader, trade_date, level)?;
            hash_descents(&mut hasher, reader, trade_date, level, levels)?;
        }
    }
    Ok(hasher.finalize())
}

fn hash_level(
    hasher: &mut blake3::Hasher,
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    level: Fidelity,
) -> Result<(), MarketDataError> {
    match level {
        Fidelity::Tbbo => {
            let tbbo = reader.tbbo(trade_date)?;
            hash_numbers(hasher, tbbo.ts_recv.iter().map(|ts| ts.0));
            for prices in [tbbo.price, tbbo.bid, tbbo.ask] {
                hash_numbers(hasher, prices.iter().map(|price| price.0));
            }
            for sizes in [tbbo.size, tbbo.bid_size, tbbo.ask_size] {
                hash_numbers(hasher, sizes.iter().map(|size| size.0));
            }
        }
        Fidelity::Trades => {
            let trades = reader.trades(trade_date)?;
            hash_numbers(hasher, trades.ts_recv.iter().map(|ts| ts.0));
            hash_numbers(hasher, trades.price.iter().map(|price| price.0));
            hash_numbers(hasher, trades.size.iter().map(|size| size.0));
        }
        Fidelity::Bars(timeframe) => {
            let bars = reader.bars(trade_date, timeframe)?;
            for instants in [bars.ts_open, bars.ts_close] {
                hash_numbers(hasher, instants.iter().map(|ts| ts.0));
            }
            for prices in [bars.open, bars.high, bars.low, bars.close] {
                hash_numbers(hasher, prices.iter().map(|price| price.0));
            }
            hash_numbers(hasher, bars.volume.iter().map(|volume| volume.0));
        }
    }
    Ok(())
}

fn hash_descents(
    hasher: &mut blake3::Hasher,
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    level: Fidelity,
    levels: &[Fidelity],
) -> Result<(), MarketDataError> {
    let Fidelity::Bars(timeframe) = level else {
        return Ok(());
    };
    for &finer in levels.iter().filter(|finer| **finer < level) {
        let offsets = reader.offsets(trade_date, timeframe, finer)?;
        hash_numbers(hasher, offsets.iter().map(|offset| i64::from(*offset)));
    }
    Ok(())
}

/// BLAKE3 over the ledger after each of a seeded run of fills at every tenth trade's price, each
/// followed by a mark there: the cash the fill moved, the cash, the lots held, and the equity.
fn ledger_run_hash(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<blake3::Hash, DeterminismError> {
    let mut ledger = Ledger::new(es()?, Money(50_000 * MONEY_UNITS));
    let trades = reader.trades(SEEDED_TRADE_DATE)?;
    let mut hasher = blake3::Hasher::new();
    for (index, (&ts, &price)) in trades.ts_recv.iter().zip(trades.price).enumerate() {
        if index % TRADES_PER_FILL != 0 {
            continue;
        }
        let side = if generator.below(2) == 1 {
            Side::Buy
        } else {
            Side::Sell
        };
        let fill = Fill {
            order: OrderId(index as u64),
            role: OrderRole::Entry,
            side,
            lots: Qty(1 + generator.below(5)),
            ts,
            price,
            rule: PricingRule::MarketAtTrade,
            fidelity: Fidelity::Trades,
            liquidity: Liquidity::Taker,
            slippage_ticks: 0,
            flags: FillFlags::default(),
            fee: Money(2_500_000),
        };
        let cash_moved = ledger.book(&fill)?;
        ledger.mark_at(price);
        let held = ledger.position().signed_lots();
        hash_numbers(
            &mut hasher,
            [cash_moved.0, ledger.cash().0, held.0, ledger.equity()?.0].into_iter(),
        );
    }
    Ok(hasher.finalize())
}

fn hash_numbers(hasher: &mut blake3::Hasher, numbers: impl Iterator<Item = i64>) {
    for number in numbers {
        hasher.update(&number.to_le_bytes());
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use fefat_engine::event_log::EventKind;

    use super::*;

    #[test]
    fn one_seed_gives_one_digest_and_another_seed_another() {
        let digest_of_the_seed = digest(20_260_308).unwrap();
        assert_eq!(digest(20_260_308).unwrap(), digest_of_the_seed);
        assert_ne!(digest(20_260_309).unwrap(), digest_of_the_seed);
        assert_eq!(digest_of_the_seed.len(), 64);
    }

    #[test]
    fn the_digests_template_run_flags_ambiguous_fills() {
        // BACKLOG.md, step 2.7: the golden pins the swapped replay of bars (F-BAR-05) once one of
        // the digest's runs on bars flags fills ambiguous, the template's on the 1-minute bars.
        let mut generator = SplitMix64::new(20_260_308);
        let contract = Contract(SEEDED_CONTRACT.to_owned());
        let reader = InMemoryMarketData::new(contract, seeded_tape(&mut generator)).unwrap();
        ledger_run_hash(&reader, &mut generator).unwrap();
        let runs = loop_run::loop_runs(&reader, &mut generator).unwrap();
        let ambiguous: Vec<usize> = runs
            .iter()
            .map(fefat_engine::tick_run::RunOutputs::ambiguous_fills)
            .collect();
        assert!(ambiguous[5] > 0, "{ambiguous:?}");
    }

    #[test]
    fn every_run_of_the_digest_pays_fees_and_rolls_and_one_pays_funding() {
        // Step 2.9: the golden pins the fee table's warning and fees, funding, and a roll's legs on
        // two contracts in every run of the digest that holds a position across them.
        let mut generator = SplitMix64::new(20_260_308);
        let contract = Contract(SEEDED_CONTRACT.to_owned());
        let reader = InMemoryMarketData::new(contract, seeded_tape(&mut generator)).unwrap();
        ledger_run_hash(&reader, &mut generator).unwrap();
        let runs = loop_run::loop_runs(&reader, &mut generator).unwrap();
        let kind_logged = |run: &fefat_engine::tick_run::RunOutputs, kind| {
            run.log.iter().filter(|entry| entry.kind == kind).count()
        };
        for run in &runs {
            assert_eq!(kind_logged(run, EventKind::Warning), 1);
            assert_eq!(kind_logged(run, EventKind::Rolled), 1);
            assert!(run.fills.iter().all(|booked| booked.fill.fee.0 > 0));
        }
        let legs = runs
            .iter()
            .flat_map(|run| &run.fills)
            .filter(|booked| matches!(booked.fill.role, OrderRole::Roll(_)));
        let contracts: BTreeSet<&str> = legs.map(|booked| booked.contract.0.as_str()).collect();
        assert_eq!(contracts, ["ESH2026", "ESM2026"].into());
        let funded = runs.iter().map(|run| kind_logged(run, EventKind::Funding));
        assert!(funded.sum::<usize>() > 0);
    }

    #[test]
    fn the_golden_manifest_names_the_command_the_versions_and_the_digest() {
        let manifest: serde_json::Value =
            serde_json::from_str(&golden_manifest(7, "digest").unwrap()).unwrap();
        assert_eq!(
            manifest["command"],
            "cargo run -p fefat-cli -- determinism 7"
        );
        assert_eq!(manifest["versions"]["fill_model"], FILL_MODEL_VERSION.0);
        assert_eq!(manifest["inputs"]["seed"], 7);
        assert_eq!(manifest["outputs"]["digest"], "digest");
    }
}
