//! Done means 2 of step 2.8 as properties of the tick loop over generated tapes and templates:
//! every move of a plan's stop that the log records lies in the position's favour, a trailing
//! stop's (F-TRL-01) and breakeven's (F-BRK-01) alike, so that neither ever worsens the stop
//! (F-PLN-03); and the level of every live stop, read after every step, never moves against the
//! position. The templates draw stops, targets, breakeven, and trailing stops in ticks, by a
//! feature, and by the column, intrabar and at bar closes; the tapes are trades or TBBO records.

use std::cell::RefCell;
use std::collections::BTreeMap;

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OrderId, OrderRole};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};
use serde_json::{Value, json};

use super::{Replay, Stepped, TickRun};
use crate::event_log::{EventKind, LogEntry};
use crate::hours::TradingHours;
use crate::settings::{LimitFill, RunSettings, SlippageTicks};
use crate::template::{RowFeatures, SignalRow, TemplateStrategy};

const SEED: u64 = 20_261_028;
const CASES: u32 = 600;
const TICK: i64 = 250_000_000;
const MONEY_PER_POINT: i64 = 50 * MONEY_UNITS;
const CAPITAL: i64 = 50_000 * MONEY_UNITS;
/// 2026-03-06T14:30:00Z.
const FIRST: i64 = 1_772_807_400 * 1_000_000_000;
const MILLISECOND: i64 = 1_000_000;
const OPENING_PRICE: i64 = 5_000 * PRICE_UNITS;

#[derive(Debug, Clone)]
struct DrawnRecord {
    gap_milliseconds: i64,
    ticks_moved: i64,
    size: i64,
    bid_ticks: i64,
    spread_ticks: i64,
}

#[derive(Debug, Clone)]
struct DrawnRow {
    record: usize,
    entry: u8,
    exits: bool,
    trail_ref_ticks: i64,
    feature_quarters: u32,
}

#[derive(Debug, Clone)]
struct DrawnCase {
    tbbo: bool,
    records: Vec<DrawnRecord>,
    rows: Vec<DrawnRow>,
    execution: Value,
    slippage: (u32, u32),
}

fn drawn_record() -> impl Strategy<Value = DrawnRecord> {
    let gap = prop_oneof![2 => Just(0_i64), 8 => 1_i64..2_000];
    let moved = prop_oneof![8 => -2_i64..=2, 1 => -8_i64..=8];
    (gap, moved, 1_i64..=20, -3_i64..=2, 1_i64..=3).prop_map(
        |(gap_milliseconds, ticks_moved, size, bid_ticks, spread_ticks)| DrawnRecord {
            gap_milliseconds,
            ticks_moved,
            size,
            bid_ticks,
            spread_ticks,
        },
    )
}

fn drawn_row() -> impl Strategy<Value = DrawnRow> {
    let entry = prop_oneof![2 => Just(0_u8), 1 => Just(1_u8), 1 => Just(2_u8)];
    (
        0_usize..120,
        entry,
        prop::bool::weighted(0.1),
        -12_i64..=4,
        1_u32..=12,
    )
        .prop_map(
            |(record, entry, exits, trail_ref_ticks, feature_quarters)| DrawnRow {
                record,
                entry,
                exits,
                trail_ref_ticks,
                feature_quarters,
            },
        )
}

fn drawn_trigger() -> impl Strategy<Value = Value> {
    prop_oneof![
        (1_u32..=8).prop_map(|ticks| json!({"kind": "ticks", "ticks": ticks})),
        prop_oneof![Just(0.5), Just(1.0), Just(1.5)]
            .prop_map(|multiple| json!({"kind": "r_multiple", "multiple": multiple})),
    ]
}

/// A template's execution: a market entry, a stop in ticks, up to two targets, and a drawn
/// breakeven and trailing stop.
fn drawn_execution() -> impl Strategy<Value = Value> {
    let targets = prop::collection::vec((2_u32..=16, prop_oneof![Just(0.5), Just(1.0)]), 0..=2);
    let breakeven = proptest::option::of((drawn_trigger(), -2_i64..=2, any::<bool>()));
    let by = prop_oneof![
        (1_u32..=8).prop_map(|ticks| json!({"kind": "ticks", "ticks": ticks})),
        prop_oneof![Just(1.0), Just(2.0)]
            .prop_map(|multiple| json!({"kind": "atr", "multiple": multiple, "feature": "atr"})),
        Just(json!({"kind": "column"})),
    ];
    let trailing = (
        by,
        proptest::option::of(1_u32..=3),
        proptest::option::of(drawn_trigger()),
        any::<bool>(),
    );
    let trailing = proptest::option::of(trailing);
    (2_u32..=12, targets, breakeven, trailing, 1_u32..=3).prop_map(
        |(stop, targets, breakeven, trailing, units)| {
            let targets: Vec<Value> = targets
                .iter()
                .map(|(ticks, fraction)| {
                    json!({"price": {"kind": "ticks", "ticks": ticks}, "fraction": fraction})
                })
                .collect();
            let mut execution = json!({
                "entry": {"kind": "market"},
                "stop": {"kind": "ticks", "ticks": stop},
                "targets": targets,
                "sizing": {"kind": "fixed", "units": units}
            });
            if let Some((trigger, offset_ticks, after_target)) = breakeven {
                let trigger = match after_target && !targets.is_empty() {
                    true => json!({"kind": "after_target", "target": 1}),
                    false => trigger,
                };
                execution["breakeven"] = json!({"trigger": trigger, "offset_ticks": offset_ticks});
            }
            if let Some((by, step_ticks, activation, intrabar)) = trailing {
                let by_column = by["kind"] == "column";
                let update = if intrabar && !by_column {
                    "intrabar"
                } else {
                    "bar_close"
                };
                let mut rule = json!({"by": by, "update": update});
                if let Some(step_ticks) = step_ticks {
                    rule["step_ticks"] = json!(step_ticks);
                }
                if let Some(activation) = activation {
                    rule["activation"] = activation;
                }
                execution["trailing"] = rule;
            }
            execution
        },
    )
}

fn drawn_case() -> impl Strategy<Value = DrawnCase> {
    let records = prop::collection::vec(drawn_record(), 20..120);
    let rows = prop::collection::vec(drawn_row(), 4..30);
    (
        any::<bool>(),
        records,
        rows,
        drawn_execution(),
        (0_u32..=2, 0_u32..=2),
    )
        .prop_map(|(tbbo, records, rows, execution, slippage)| DrawnCase {
            tbbo,
            records,
            rows,
            execution,
            slippage,
        })
}

fn tape(case: &DrawnCase) -> (Vec<TradeRow>, Vec<TbboRow>) {
    let (mut ts, mut price) = (FIRST, OPENING_PRICE);
    let (mut trades, mut tbbo) = (Vec::new(), Vec::new());
    for record in &case.records {
        ts += record.gap_milliseconds * MILLISECOND;
        price += record.ticks_moved * TICK;
        let bid = price + record.bid_ticks * TICK;
        let trade = TradeRow {
            ts_recv: Ts(ts),
            price: Price(price),
            size: Qty(record.size),
        };
        tbbo.push(TbboRow {
            ts_recv: trade.ts_recv,
            price: trade.price,
            size: trade.size,
            bid: Price(bid),
            ask: Price(bid + record.spread_ticks * TICK),
            bid_size: Qty(5),
            ask_size: Qty(5),
        });
        trades.push(trade);
    }
    (trades, tbbo)
}

/// The signal rows at the drawn records' instants, one per instant, the first drawn there.
fn signal_rows(case: &DrawnCase, trades: &[TradeRow]) -> Vec<SignalRow> {
    let mut by_close: BTreeMap<Ts, SignalRow> = BTreeMap::new();
    for row in &case.rows {
        let Some(record) = trades.get(row.record % trades.len()) else {
            continue;
        };
        let feature = f64::from(row.feature_quarters) * 0.25;
        by_close.entry(record.ts_recv).or_insert(SignalRow {
            long_entry: row.entry == 1,
            short_entry: row.entry == 2,
            long_exit: row.exits,
            short_exit: row.exits,
            trail_ref: Some(Price(record.price.0 + row.trail_ref_ticks * TICK)),
            features: RowFeatures {
                trailing: Some(feature),
                ..RowFeatures::NONE
            },
            ..SignalRow::at(record.ts_recv)
        });
    }
    by_close.into_values().collect()
}

/// A level the log writes, such as `4998.25` or `5000`, in 1e-9 units.
fn price_of(text: &str) -> Price {
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    let units = whole.trim_start_matches('-').parse::<i64>().unwrap() * PRICE_UNITS
        + format!("{fraction:0<9}").parse::<i64>().unwrap();
    Price(if whole.starts_with('-') {
        -units
    } else {
        units
    })
}

/// The levels a `moved` entry names: from where, to where.
fn moved_levels(entry: &LogEntry) -> (Price, Price) {
    let (_, levels) = entry.text.split_once(" from ").unwrap();
    let (before, after) = levels.split_once(" to ").unwrap();
    (price_of(before), price_of(after))
}

/// What the cases reached, so that the properties never hold because nothing moved.
#[derive(Debug, Default)]
struct Coverage {
    moves: BTreeMap<&'static str, usize>,
    moves_at_decisions: usize,
    stops_followed: usize,
}

/// Runs `case` step by step, holding every move and every stop's level to the position's favour.
fn moves_only_in_favour(case: &DrawnCase, seen: &mut Coverage) -> Result<(), TestCaseError> {
    let (trades, tbbo) = tape(case);
    let level = if case.tbbo {
        Fidelity::Tbbo
    } else {
        Fidelity::Trades
    };
    let day = TapeDay {
        trade_date: TradeDate(20_518),
        tbbo: if case.tbbo { tbbo } else { Vec::new() },
        trades: if case.tbbo {
            Vec::new()
        } else {
            trades.clone()
        },
        bars: Default::default(),
    };
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![day]).unwrap();
    let spec = json!({
        "spec_version": 1, "instrument": "ES", "timeframe": "1m", "execution": case.execution
    });
    let spec: StrategySpec = serde_json::from_value(spec).unwrap();
    let instrument =
        InstrumentParameters::new(Price(TICK), Money(MONEY_PER_POINT), LotStep(PRICE_UNITS))
            .unwrap();
    let rows = signal_rows(case, &trades);
    let mut template = TemplateStrategy::new(&spec, rows, &instrument).unwrap();
    let settings = RunSettings {
        latency_milliseconds: 0,
        slippage: SlippageTicks {
            market: case.slippage.0,
            stop: case.slippage.1,
        },
        limit_fill: LimitFill::Through,
    };
    let hours = TradingHours::always();
    let ledger = Ledger::new(instrument, Money(CAPITAL));
    let mut run = TickRun::new(
        &reader,
        level,
        Replay::Full,
        &hours,
        settings,
        ledger,
        &mut template,
    )
    .unwrap();
    let (mut levels, mut logged) = (BTreeMap::<OrderId, Price>::new(), 0);
    while let Some(stepped) = run.step().unwrap() {
        for entry in run.log.get(logged..).unwrap_or_default() {
            if entry.kind != EventKind::Moved {
                continue;
            }
            let stop = run.book.order(entry.order.unwrap()).unwrap();
            let position = stop.order.side.opposite();
            let (before, after) = moved_levels(entry);
            let rule = entry.rule.unwrap();
            prop_assert!(
                position.better(after, before) == after && after != before,
                "{rule} moved order {} from {before} to {after}, against the {position}'s favour: {case:?}",
                stop.order.id.0
            );
            *seen.moves.entry(rule).or_default() += 1;
            seen.moves_at_decisions += usize::from(matches!(stepped, Stepped::Decision(_)));
        }
        logged = run.log.len();
        for stop in run
            .book
            .live()
            .filter(|order| order.order.role == OrderRole::Stop)
        {
            let (id, level) = (stop.order.id, stop.level().unwrap());
            let position = stop.order.side.opposite();
            if let Some(&before) = levels.get(&id) {
                prop_assert!(
                    position.better(level, before) == level,
                    "order {} went from {before} to {level}: {case:?}",
                    id.0
                );
            } else {
                seen.stops_followed += 1;
            }
            levels.insert(id, level);
        }
    }
    Ok(())
}

#[test]
fn a_plans_stop_moves_only_in_the_positions_favour_by_breakeven_and_trailing_alike() {
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
        moves_only_in_favour(&case, &mut coverage.borrow_mut())
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    for rule in ["F-BRK-01", "F-TRL-01"] {
        let moves = coverage.moves.get(rule).copied().unwrap_or(0);
        assert!(
            moves >= 100,
            "Expected 100 moves by {rule}, got {coverage:#?}"
        );
    }
    assert!(coverage.moves_at_decisions >= 50, "{coverage:#?}");
    assert!(coverage.stops_followed >= 500, "{coverage:#?}");
}
