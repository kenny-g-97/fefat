//! The loop's part of the determinism digest (steps 2.6 to 2.8): the seeded tape's trades, its
//! TBBO records, its 1-second bars, and its 1-minute bars run in full through `TickRun` with
//! seeded orders, its TBBO records again skipping by its bars, and its 1-minute bars under a
//! seeded execution template whose exit plan has two targets, breakeven, a trailing stop, and max
//! bars; each run paying a futures fee table whose first schedule starts after the tape's date,
//! funding at two times, and rolling once, a gap of 5.00, inside the tape (step 2.9); and every
//! order, fill with its contract, entry of the event log, and cost line, with the final cash and
//! position, the trades and the account at each decision (step 2.10), and the fidelity eras of
//! each run's trade dates (step 2.12), hashed in order.

use fefat_core::costs::{CostReason, FeeRate, FeeSchedule, FeeTable, FundingRate, Rate};
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::ledger::Ledger;
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::{OrderId, OrderKind, Side};
use fefat_core::rolls::{Roll, RollReason};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, Price, Qty};
use fefat_engine::book::{Bracket, BracketLeg, LegPrice};
use fefat_engine::hours::TradingHours;
use fefat_engine::settings::{RollHandling, RunCosts, RunSettings};
use fefat_engine::strategy::{ScenarioOrder, ScenarioOrders, Strategy};
use fefat_engine::template::{SignalRow, TemplateStrategy};
use fefat_engine::tick_run::{Replay, RunOutputs, TickRun};

use super::{DeterminismError, es, hash_numbers};
use crate::seeded_tape::{FIRST_SECOND, SEEDED_CONTRACT, SEEDED_TRADE_DATE, SplitMix64, TICK};

/// The seeded template of the digest's sixth run (step 2.8): a market entry of two lots, a stop
/// of 8 ticks, two targets each closing half, breakeven after the first, an intrabar trailing
/// stop of 6 ticks working from 8 ticks of profit, ten bars at most, and signal exits.
const TEMPLATE_SPEC: &str = r#"{
    "spec_version": 1, "instrument": "ES", "timeframe": "1m",
    "execution": {
        "entry": {"kind": "market"},
        "stop": {"kind": "ticks", "ticks": 8},
        "targets": [
            {"price": {"kind": "ticks", "ticks": 4}, "fraction": 0.5},
            {"price": {"kind": "ticks", "ticks": 12}}
        ],
        "breakeven": {"trigger": {"kind": "after_target", "target": 1}},
        "trailing": {"by": {"kind": "ticks", "ticks": 6}, "activation": {"kind": "ticks", "ticks": 8}},
        "time": {"tz": "UTC", "max_bars": 10},
        "sizing": {"kind": "fixed", "units": 2},
        "signal_exit": true
    }
}"#;

/// Every hundredth trade of the seeded tape's instant decides an order of the loop's run.
const TRADES_PER_ORDER: usize = 100;

/// The runs of the digest: each level in full, then TBBO skipping by the bars above it.
const RUNS: [(Fidelity, Replay); 5] = [
    (Fidelity::Trades, Replay::Full),
    (Fidelity::Tbbo, Replay::Full),
    (Fidelity::Bars(Timeframe::ONE_SECOND), Replay::Full),
    (Fidelity::Bars(Timeframe::ONE_MINUTE), Replay::Full),
    (Fidelity::Tbbo, Replay::Skipping),
];

/// BLAKE3 over every order, fill, and entry of the event log, and the final cash and position, of
/// each of the loop's [`RUNS`] on the seeded tape, with the same seeded orders and the
/// specification's default settings, and of the seeded template's run on its 1-minute bars.
pub(super) fn loop_run_hash(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<blake3::Hash, DeterminismError> {
    let mut hasher = blake3::Hasher::new();
    for outputs in loop_runs(reader, generator)? {
        hash_outputs(&mut hasher, &outputs);
    }
    Ok(hasher.finalize())
}

/// The outputs of the loop's [`RUNS`] with the seeded orders, then of the seeded template's run on
/// the 1-minute bars, in that order.
pub(super) fn loop_runs(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<Vec<RunOutputs>, DeterminismError> {
    let orders = seeded_orders(reader, generator)?;
    let mut runs = Vec::with_capacity(RUNS.len() + 1);
    for (fidelity, replay) in RUNS {
        let mut strategy = ScenarioOrders::new(orders.clone());
        runs.push(seeded_run(reader, fidelity, replay, &mut strategy)?);
    }
    let mut template = seeded_template(reader, generator)?;
    let minutes = Fidelity::Bars(Timeframe::ONE_MINUTE);
    runs.push(seeded_run(reader, minutes, Replay::Full, &mut template)?);
    Ok(runs)
}

/// `strategy` run on the seeded tape at `fidelity`, replayed as `replay`, from the run's capital
/// with the specification's default settings, paying the seeded costs and rolling once.
fn seeded_run(
    reader: &impl MarketDataReader,
    fidelity: Fidelity,
    replay: Replay,
    strategy: &mut dyn Strategy,
) -> Result<RunOutputs, DeterminismError> {
    let hours = TradingHours::always();
    let ledger = Ledger::new(es()?, Money(50_000 * MONEY_UNITS));
    let settings = RunSettings::defaults_for(fidelity);
    let run = TickRun::new(reader, fidelity, replay, &hours, settings, ledger, strategy)?;
    let run = run.with_costs(seeded_costs()?)?;
    let run = run.with_rolls(vec![seeded_roll()], RollHandling::Transfer)?;
    Ok(run.run()?)
}

/// A fee of 2.50 per contract per side from 2026-03-06, the day after the tape's, so that the run
/// warns that the first schedule prices its fills (F-FEE-01), and funding at 14:35 and 14:40, at
/// 0.0001 and -0.0002.
fn seeded_costs() -> Result<RunCosts, DeterminismError> {
    let fees = FeeTable::new(vec![FeeSchedule {
        effective_from: TradeDate(SEEDED_TRADE_DATE.0 + 1),
        fee: FeeRate::Futures {
            per_contract_side: Money(2_500_000),
        },
    }])?;
    let at = |minutes: i64| Ts(FIRST_SECOND + minutes * 60 * NANOSECONDS_PER_SECOND);
    let funding = vec![
        FundingRate {
            ts: at(5),
            rate: Rate(100_000),
        },
        FundingRate {
            ts: at(10),
            rate: Rate(-200_000),
        },
    ];
    Ok(RunCosts {
        fees: Some(fees),
        funding,
    })
}

/// A roll at 14:38, from the seeded contract to ESM2026, a gap of 5.00, on volume.
fn seeded_roll() -> Roll {
    Roll {
        session_open: Ts(FIRST_SECOND + 8 * 60 * NANOSECONDS_PER_SECOND),
        rolled_from: Contract(SEEDED_CONTRACT.to_owned()),
        contract: Contract("ESM2026".to_owned()),
        gap: Price(20 * TICK),
        reason: RollReason::Volume,
    }
}

/// The seeded template over a signal row at each 1-minute bar's close of the seeded tape, each
/// with a long entry, a short entry, both exits, or no signal, at random.
fn seeded_template(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<TemplateStrategy, DeterminismError> {
    let bars = reader.bars(SEEDED_TRADE_DATE, Timeframe::ONE_MINUTE)?;
    let rows = bars.ts_close.iter().map(|&ts_close| {
        let signal = generator.below(4);
        SignalRow {
            trade_date: Some(SEEDED_TRADE_DATE),
            long_entry: signal == 1,
            short_entry: signal == 2,
            long_exit: signal == 3,
            short_exit: signal == 3,
            ..SignalRow::at(ts_close)
        }
    });
    let spec: StrategySpec = serde_json::from_str(TEMPLATE_SPEC)?;
    Ok(TemplateStrategy::new(&spec, rows.collect(), &es()?)?)
}

/// An order at every hundredth trade's instant: market, stop, or limit, on either side, one to
/// eight ticks from that trade's price, of one to five lots, every market entry with a bracket of
/// four to twelve ticks each way.
fn seeded_orders(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<Vec<ScenarioOrder>, DeterminismError> {
    let trades = reader.trades(SEEDED_TRADE_DATE)?;
    let decided = trades
        .ts_recv
        .iter()
        .zip(trades.price)
        .step_by(TRADES_PER_ORDER);
    let mut orders = Vec::new();
    for (number, (&placed_at, &price)) in (1_u64..).zip(decided) {
        let side = if generator.below(2) == 1 {
            Side::Buy
        } else {
            Side::Sell
        };
        let away = Price(TICK * (1 + generator.below(8)));
        let level = if generator.below(2) == 1 {
            price.checked_add(away)?
        } else {
            price.checked_sub(away)?
        };
        let kind = match generator.below(3) {
            0 => OrderKind::Market,
            1 => OrderKind::StopMarket { stop: level },
            _ => OrderKind::Limit { limit: level },
        };
        let mut leg = |id: u64| BracketLeg {
            id: Some(OrderId(id)),
            price: LegPrice::TicksFromFill(4 + generator.below_u32(9)),
        };
        let bracket = (kind == OrderKind::Market).then(|| Bracket {
            stop: leg(1_000 + number),
            target: leg(2_000 + number),
        });
        orders.push(ScenarioOrder {
            placed_at,
            id: OrderId(number),
            side,
            lots: Qty(1 + generator.below(5)),
            kind,
            oco: None,
            bracket,
        });
    }
    Ok(orders)
}

fn hash_outputs(hasher: &mut blake3::Hasher, outputs: &RunOutputs) {
    hash_numbers(
        hasher,
        [outputs.orders.len(), outputs.fills.len(), outputs.log.len()]
            .map(|count| count as i64)
            .into_iter(),
    );
    for order in &outputs.orders {
        let placed = &order.order;
        let level = order.level().map_or(0, |price| price.0);
        let oco = placed.oco.map_or(0, |group| group.0 as i64);
        let entry = order.link.leg_of().map_or(0, |entry| entry.0 as i64);
        hash_numbers(
            hasher,
            [placed.id.0 as i64, placed.side.sign(), level, placed.lots.0].into_iter(),
        );
        hash_numbers(
            hasher,
            [placed.placed_at.0, placed.activation.0, oco, entry].into_iter(),
        );
        hash_words(
            hasher,
            [
                placed.kind.to_string(),
                placed.role.to_string(),
                order.state().to_string(),
            ],
        );
    }
    for booked in &outputs.fills {
        let fill = &booked.fill;
        let flags = [fill.flags.ambiguous, fill.flags.size_exceeded].map(i64::from);
        hash_numbers(
            hasher,
            [
                fill.order.0 as i64,
                fill.side.sign(),
                fill.lots.0,
                fill.ts.0,
                fill.price.0,
            ]
            .into_iter(),
        );
        hash_numbers(
            hasher,
            [
                fill.slippage_ticks,
                fill.fee.0,
                booked.cash.0,
                flags[0],
                flags[1],
            ]
            .into_iter(),
        );
        hash_words(
            hasher,
            [
                fill.rule.id().to_owned(),
                fill.fidelity.to_string(),
                fill.liquidity.to_string(),
                fill.role.to_string(),
                booked.contract.0.clone(),
            ],
        );
    }
    for line in &outputs.cost_lines {
        let (reason, detail) = match line.reason {
            CostReason::Fee { order } => (1, order.0 as i64),
            CostReason::Funding { rate } => (2, rate.0),
        };
        hash_numbers(
            hasher,
            [line.ts.0, line.amount.0, reason, detail].into_iter(),
        );
    }
    for entry in &outputs.log {
        let order = entry.order.map_or(0, |order| order.0 as i64);
        hash_numbers(hasher, [entry.ts.0, order].into_iter());
        hash_words(
            hasher,
            [
                entry.kind.to_string(),
                entry.rule.unwrap_or("").to_owned(),
                entry.text.clone(),
            ],
        );
    }
    let held = outputs.ledger.position().signed_lots();
    hash_numbers(hasher, [outputs.ledger.cash().0, held.0].into_iter());
    hash_trades_and_equity(hasher, outputs);
    hash_eras(hasher, outputs);
}

/// Step 2.12's fidelity eras: their count, then each era's first and last trade date, its count
/// of trade dates, and its level.
fn hash_eras(hasher: &mut blake3::Hasher, outputs: &RunOutputs) {
    hash_numbers(hasher, [outputs.eras.len() as i64].into_iter());
    for era in &outputs.eras {
        let dates = [
            i64::from(era.first.0),
            i64::from(era.last.0),
            era.trade_dates as i64,
        ];
        hash_numbers(hasher, dates.into_iter());
        hash_words(hasher, [era.fidelity.to_string()]);
    }
}

/// Step 2.10's outputs: each fill's trade date, each trade closed, and the account at each
/// decision, a missing value hashed as -1 after the counts.
fn hash_trades_and_equity(hasher: &mut blake3::Hasher, outputs: &RunOutputs) {
    let counts = [outputs.trades.len(), outputs.equity.len()].map(|count| count as i64);
    hash_numbers(hasher, counts.into_iter());
    let dates = outputs
        .fills
        .iter()
        .map(|booked| i64::from(booked.trade_date.0));
    hash_numbers(hasher, dates);
    for trade in &outputs.trades {
        let exit_price = trade.exit_price.map_or(-1, |price| price.to_bits() as i64);
        let risk = trade.initial_risk_ticks.unwrap_or(-1);
        let entry = [
            trade.entry_decision.0,
            trade.entry_ts.0,
            trade.entry_price.0,
        ];
        hash_numbers(hasher, entry.into_iter());
        let exit = [
            trade.exit_ts.0,
            exit_price,
            i64::from(trade.exits),
            i64::from(trade.rolls),
        ];
        hash_numbers(hasher, exit.into_iter());
        let money = [
            trade.gross_pnl.0,
            trade.fees.0,
            trade.funding.0,
            trade.pnl.0,
        ];
        hash_numbers(hasher, money.into_iter());
        let excursions = [
            risk,
            trade.mae_ticks,
            trade.mfe_ticks,
            trade.mae.0,
            trade.mfe.0,
        ];
        hash_numbers(hasher, excursions.into_iter());
        hash_words(
            hasher,
            [
                trade.side.to_string(),
                trade.exit_reason.to_string(),
                trade.entry_contract.0.clone(),
                trade.exit_contract.0.clone(),
            ],
        );
    }
    for point in &outputs.equity {
        let mark = point.mark.map_or(-1, |mark| mark.0);
        let equity = point.equity.map_or(-1, |equity| equity.0);
        let account = [point.ts.0, point.cash.0, point.position.0, mark, equity];
        hash_numbers(hasher, account.into_iter());
    }
}

/// Each word framed by its length, so that two lists of words never share their bytes.
fn hash_words<const N: usize>(hasher: &mut blake3::Hasher, words: [String; N]) {
    for word in words {
        hasher.update(&(word.len() as u64).to_le_bytes());
        hasher.update(word.as_bytes());
    }
}
