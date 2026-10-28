//! Done means 2 of step 2.8, its third property, over generated tapes of several trade dates: once
//! the trades a trade date has counted lost `daily_loss_stop` or more, the template places no entry
//! for the rest of that date (F-LIM-02). The property reads the run's outputs alone: each entry
//! order's decision, and the trades closed before it that a decision of the same trade date
//! counted, each at the first decision at or after its closing fill.

use std::cell::RefCell;
use std::collections::BTreeMap;

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{InMemoryMarketData, TapeDay, TradeRow};
use fefat_core::orders::OrderRole;
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};
use serde_json::json;

use super::{Replay, TickRun};
use crate::hours::TradingHours;
use crate::settings::{LimitFill, RunSettings, SlippageTicks};
use crate::template::{SignalRow, TemplateStrategy};

const SEED: u64 = 20_261_029;
const CASES: u32 = 400;
const TICK: i64 = 250_000_000;
const MONEY_PER_POINT: i64 = 50 * MONEY_UNITS;
/// 2026-03-02T14:30:00Z, a Monday, and its trade date.
const FIRST: i64 = 1_772_461_800 * 1_000_000_000;
const FIRST_DATE: i32 = 20_514;
const DAY: i64 = 86_400 * 1_000_000_000;
const MILLISECOND: i64 = 1_000_000;

#[derive(Debug, Clone)]
struct DrawnDay {
    moves: Vec<(i64, i64)>,
    signals: Vec<(usize, u8)>,
}

#[derive(Debug, Clone)]
struct DrawnCase {
    days: Vec<DrawnDay>,
    stop_ticks: u32,
    target_ticks: u32,
    loss_stop: u32,
    signal_exit: bool,
}

fn drawn_day() -> impl Strategy<Value = DrawnDay> {
    let moves = prop::collection::vec((1_i64..3_000, -3_i64..=3), 20..80);
    let entry = prop_oneof![1 => Just(0_u8), 2 => Just(1_u8), 2 => Just(2_u8), 1 => Just(3_u8)];
    let signals = prop::collection::vec((0_usize..80, entry), 5..40);
    (moves, signals).prop_map(|(moves, signals)| DrawnDay { moves, signals })
}

fn drawn_case() -> impl Strategy<Value = DrawnCase> {
    let days = prop::collection::vec(drawn_day(), 2..4);
    (days, 1_u32..=6, 1_u32..=12, 10_u32..=150, any::<bool>()).prop_map(
        |(days, stop_ticks, target_ticks, loss_stop, signal_exit)| DrawnCase {
            days,
            stop_ticks,
            target_ticks,
            loss_stop,
            signal_exit,
        },
    )
}

/// Each drawn day's trades, from 14:30 UTC of its date, and the signal rows at their instants.
fn tape_and_rows(case: &DrawnCase) -> (Vec<TapeDay>, Vec<SignalRow>) {
    let (mut days, mut rows) = (Vec::new(), BTreeMap::<Ts, SignalRow>::new());
    let mut price = 5_000 * PRICE_UNITS;
    for (offset, drawn) in case.days.iter().enumerate() {
        let trade_date = TradeDate(FIRST_DATE + i32::try_from(offset).unwrap());
        let mut ts = FIRST + i64::try_from(offset).unwrap() * DAY;
        let mut trades = Vec::new();
        for &(gap, ticks) in &drawn.moves {
            ts += gap * MILLISECOND;
            price += ticks * TICK;
            trades.push(TradeRow {
                ts_recv: Ts(ts),
                price: Price(price),
                size: Qty(5),
            });
        }
        for &(index, signal) in &drawn.signals {
            let at = trades[index % trades.len()].ts_recv;
            rows.entry(at).or_insert(SignalRow {
                trade_date: Some(trade_date),
                long_entry: signal == 1,
                short_entry: signal == 2,
                long_exit: signal == 3,
                short_exit: signal == 3,
                ..SignalRow::at(at)
            });
        }
        days.push(TapeDay {
            trade_date,
            tbbo: Vec::new(),
            trades,
            bars: Default::default(),
        });
    }
    (days, rows.into_values().collect())
}

/// What the cases reached: the dates on which the stop triggered and an entry signal came later.
#[derive(Debug, Default)]
struct Coverage {
    entries: usize,
    stops_triggered: usize,
    signals_after_the_stop: usize,
}

fn no_entry_after_the_stop(case: &DrawnCase, seen: &mut Coverage) -> Result<(), TestCaseError> {
    let (days, rows) = tape_and_rows(case);
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), days).unwrap();
    let execution = json!({
        "entry": {"kind": "market"},
        "stop": {"kind": "ticks", "ticks": case.stop_ticks},
        "targets": [{"price": {"kind": "ticks", "ticks": case.target_ticks}}],
        "signal_exit": case.signal_exit,
        "limits": {"daily_loss_stop": case.loss_stop},
        "sizing": {"kind": "fixed", "units": 1}
    });
    let spec =
        json!({"spec_version": 1, "instrument": "ES", "timeframe": "1m", "execution": execution});
    let spec: StrategySpec = serde_json::from_value(spec).unwrap();
    let instrument =
        InstrumentParameters::new(Price(TICK), Money(MONEY_PER_POINT), LotStep(PRICE_UNITS))
            .unwrap();
    let mut template = TemplateStrategy::new(&spec, rows.clone(), &instrument).unwrap();
    let settings = RunSettings {
        latency_milliseconds: 0,
        slippage: SlippageTicks { market: 1, stop: 1 },
        limit_fill: LimitFill::Through,
    };
    let (hours, ledger) = (TradingHours::always(), Ledger::new(instrument, Money(0)));
    let mut run = TickRun::new(
        &reader,
        Fidelity::Trades,
        Replay::Full,
        &hours,
        settings,
        ledger,
        &mut template,
    )
    .unwrap();
    while run.step().unwrap().is_some() {}
    let closed_trades = run.closed_trades.clone();
    let orders = run.run().unwrap().orders;
    let date_of: BTreeMap<Ts, Option<TradeDate>> = rows
        .iter()
        .map(|row| (row.ts_close, row.trade_date))
        .collect();
    let closes: Vec<Ts> = rows.iter().map(|row| row.ts_close).collect();
    let counted_at = |closed_at: Ts| closes.get(closes.partition_point(|close| *close < closed_at));
    let stop = -i64::from(case.loss_stop) * MONEY_UNITS;
    let lost_by = |decision: Ts| {
        let date = date_of.get(&decision).copied().flatten();
        let counted = closed_trades.iter().filter(|trade| {
            counted_at(trade.closed_at)
                .is_some_and(|at| *at <= decision && date_of.get(at).copied().flatten() == date)
        });
        counted.map(|trade| trade.pnl.0).sum::<i64>() <= stop
    };
    let entries = orders.iter();
    for order in entries.filter(|order| order.order.role == OrderRole::Entry) {
        let placed_at = order.order.placed_at;
        prop_assert!(
            !lost_by(placed_at),
            "order {} entered at {placed_at} after the day lost {} or more: {case:?}",
            order.order.id.0,
            case.loss_stop
        );
        seen.entries += 1;
    }
    let triggered = rows.iter().filter(|row| lost_by(row.ts_close));
    let mut dates = triggered.map(|row| row.trade_date).collect::<Vec<_>>();
    let signals = rows.iter().filter(|row| row.long_entry || row.short_entry);
    seen.signals_after_the_stop += signals.filter(|row| lost_by(row.ts_close)).count();
    dates.dedup();
    seen.stops_triggered += dates.len();
    Ok(())
}

#[test]
fn the_daily_loss_stop_places_no_entry_for_the_rest_of_its_trade_date() {
    let mut seed = [0_u8; 32];
    seed[..8].copy_from_slice(&SEED.to_le_bytes());
    let config = Config {
        cases: CASES,
        failure_persistence: None,
        ..Config::default()
    };
    let mut runner =
        TestRunner::new_with_rng(config, TestRng::from_seed(RngAlgorithm::ChaCha, &seed));
    let coverage = RefCell::new(Coverage::default());
    let outcome = runner.run(&drawn_case(), |case| {
        no_entry_after_the_stop(&case, &mut coverage.borrow_mut())
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    assert!(coverage.entries >= 1_000, "{coverage:#?}");
    assert!(coverage.stops_triggered >= 100, "{coverage:#?}");
    assert!(coverage.signals_after_the_stop >= 300, "{coverage:#?}");
}
