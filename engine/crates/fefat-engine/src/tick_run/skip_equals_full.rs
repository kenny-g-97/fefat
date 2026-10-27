//! Step 2.7's Done means 2, skip equals no-skip: on generated months of mixed fidelity, the
//! skipping engine and the full replay give identical orders, fills, event logs, and ledgers, and
//! count the same ambiguous fills, over 1,000 cases under a fixed seed. A case draws one to four
//! trade dates, each holding the levels of a drawn profile (TBBO, trades, 1-second, 1-minute,
//! 5-minute, or daily bars, all built from one walk of trades with jumps and quiet minutes), the
//! finest fidelity it fills on, an order scenario or the template over drawn signal rows, flat-by
//! included, run settings, and trading hours with a break and a halt. The cases must skip records
//! and fill by every rule on ticks and bars, so that agreement never means that nothing happened.

use std::cell::RefCell;
use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, TimeUnit, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, SECONDS_PER_DAY, TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, Side};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};

use super::{Replay, RunError, RunOutputs, Stepped, TickRun};
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::hours::{Halt, Session, TradingHours};
use crate::settings::{LimitFill, RunSettings, SlippageTicks};
use crate::strategy::{ScenarioOrder, ScenarioOrders, Strategy as RunStrategy};
use crate::template::{SignalRow, TemplateStrategy};

/// The run's seed, recorded in the pull request, so that a failure reproduces.
const SEED: u64 = 20_261_027;
const CASES: u32 = 1_000;
const TICK: i64 = 250_000_000;
const MONEY_PER_POINT: i64 = 50 * MONEY_UNITS;
const CAPITAL: i64 = 50_000 * MONEY_UNITS;
const MILLISECOND: i64 = 1_000_000;
const SECOND: i64 = NANOSECONDS_PER_SECOND;
const DAY: i64 = SECONDS_PER_DAY * NANOSECONDS_PER_SECOND;
/// 2026-03-05, the first drawn trade date.
const FIRST_DATE: i32 = 20_517;
/// 14:30 UTC, when each drawn trade date's walk starts.
const WALK_STARTS: i64 = (14 * 3_600 + 30 * 60) * SECOND;
/// 15:00 UTC, the template's flat-by time when it has one.
const FLAT_BY: i64 = 15 * 3_600 * SECOND;
const OPENING_PRICE: i64 = 5_000 * PRICE_UNITS;

/// The levels a drawn trade date holds, finest first, all built from its walk of trades.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Profile {
    TbboTradesSecondsMinutes,
    TradesSecondsMinutes,
    TradesMinutesFiveMinutes,
    SecondsMinutes,
    Minutes,
    MinutesFiveMinutes,
    FiveMinutes,
    Daily,
}

impl Profile {
    const ALL: [Self; 8] = [
        Self::TbboTradesSecondsMinutes,
        Self::TradesSecondsMinutes,
        Self::TradesMinutesFiveMinutes,
        Self::SecondsMinutes,
        Self::Minutes,
        Self::MinutesFiveMinutes,
        Self::FiveMinutes,
        Self::Daily,
    ];

    /// Whether it holds TBBO records and trades.
    const fn ticks(self) -> (bool, bool) {
        match self {
            Self::TbboTradesSecondsMinutes => (true, true),
            Self::TradesSecondsMinutes | Self::TradesMinutesFiveMinutes => (false, true),
            _ => (false, false),
        }
    }

    /// The timeframes of its bars.
    fn timeframes(self) -> Vec<Timeframe> {
        let (second, minute, five) = (
            Timeframe::ONE_SECOND,
            Timeframe::ONE_MINUTE,
            Timeframe::FIVE_MINUTES,
        );
        match self {
            Self::TbboTradesSecondsMinutes | Self::TradesSecondsMinutes | Self::SecondsMinutes => {
                vec![second, minute]
            }
            Self::TradesMinutesFiveMinutes | Self::MinutesFiveMinutes => vec![minute, five],
            Self::Minutes => vec![minute],
            Self::FiveMinutes => vec![five],
            Self::Daily => vec![Timeframe::new(1, TimeUnit::Day).unwrap()],
        }
    }
}

#[derive(Debug, Clone)]
struct DrawnTick {
    gap_milliseconds: i64,
    ticks_moved: i64,
    size: i64,
    bid_ticks: i64,
    spread_ticks: i64,
    bid_size: i64,
    ask_size: i64,
}

#[derive(Debug, Clone)]
struct DrawnDay {
    profile: Profile,
    ticks: Vec<DrawnTick>,
}

/// An instant beside a drawn tick: the tick's own, a millisecond or a tenth of a second either
/// side, or the close of the second or the minute it falls in.
#[derive(Debug, Clone, Copy)]
struct DrawnInstant {
    day: usize,
    tick: usize,
    offset: u8,
}

#[derive(Debug, Clone)]
struct DrawnBracket {
    in_ticks: bool,
    stop_ticks: i64,
    target_ticks: i64,
}

#[derive(Debug, Clone)]
struct DrawnOrder {
    decision: usize,
    buys: bool,
    class: u8,
    away_ticks: i64,
    lots: i64,
    bracket: Option<DrawnBracket>,
    grouped_with_next: bool,
}

#[derive(Debug, Clone)]
struct DrawnRow {
    instant: DrawnInstant,
    entry: u8,
    long_exit: bool,
    short_exit: bool,
    wake: bool,
}

#[derive(Debug, Clone)]
struct DrawnTemplate {
    stop_ticks: u32,
    target_ticks: u32,
    signal_exit: bool,
    flat_by: bool,
    rows: Vec<DrawnRow>,
}

#[derive(Debug, Clone)]
enum DrawnStrategy {
    Orders {
        decisions: Vec<DrawnInstant>,
        orders: Vec<DrawnOrder>,
    },
    Template(DrawnTemplate),
}

#[derive(Debug, Clone)]
struct DrawnMonth {
    days: Vec<DrawnDay>,
    fidelity: Fidelity,
    strategy: DrawnStrategy,
    opening: Option<(bool, i64)>,
    latency_milliseconds: u32,
    ticks: (u32, u32),
    touch: bool,
    closed: Option<(usize, usize)>,
    halted: Option<(usize, usize)>,
}

fn drawn_tick() -> impl Strategy<Value = DrawnTick> {
    let gap = prop_oneof![
        3 => Just(0_i64),
        5 => 1_i64..1_000,
        2 => 1_000_i64..30_000,
        1 => Just(61_000_i64),
        1 => Just(300_000_i64),
    ];
    let moved = prop_oneof![8 => -2_i64..=2, 1 => -40_i64..=40];
    let quote = (-3_i64..=2, 1_i64..=3, 1_i64..=9, 1_i64..=9);
    (gap, moved, 1_i64..=9, quote).prop_map(
        |(gap_milliseconds, ticks_moved, size, (bid_ticks, spread_ticks, bid_size, ask_size))| {
            DrawnTick {
                gap_milliseconds,
                ticks_moved,
                size,
                bid_ticks,
                spread_ticks,
                bid_size,
                ask_size,
            }
        },
    )
}

fn drawn_day() -> impl Strategy<Value = DrawnDay> {
    let profile = proptest::sample::select(Profile::ALL.to_vec());
    let ticks = proptest::collection::vec(drawn_tick(), 1..40);
    (profile, ticks).prop_map(|(profile, ticks)| DrawnDay { profile, ticks })
}

fn drawn_instant() -> impl Strategy<Value = DrawnInstant> {
    (0_usize..4, 0_usize..40, 0_u8..7).prop_map(|(day, tick, offset)| DrawnInstant {
        day,
        tick,
        offset,
    })
}

fn drawn_order() -> impl Strategy<Value = DrawnOrder> {
    let bracket =
        (any::<bool>(), 1_i64..=12, 1_i64..=12).prop_map(|(in_ticks, stop_ticks, target_ticks)| {
            DrawnBracket {
                in_ticks,
                stop_ticks,
                target_ticks,
            }
        });
    (
        0_usize..3,
        any::<bool>(),
        0_u8..3,
        -20_i64..=20,
        1_i64..=3,
        proptest::option::of(bracket),
        any::<bool>(),
    )
        .prop_map(
            |(decision, buys, class, away_ticks, lots, bracket, grouped_with_next)| DrawnOrder {
                decision,
                buys,
                class,
                away_ticks,
                lots,
                bracket,
                grouped_with_next,
            },
        )
}

fn drawn_row() -> impl Strategy<Value = DrawnRow> {
    (
        drawn_instant(),
        0_u8..3,
        any::<bool>(),
        any::<bool>(),
        prop_oneof![3 => Just(true), 1 => Just(false)],
    )
        .prop_map(|(instant, entry, long_exit, short_exit, wake)| DrawnRow {
            instant,
            entry,
            long_exit,
            short_exit,
            wake,
        })
}

fn drawn_strategy() -> impl Strategy<Value = DrawnStrategy> {
    let orders = (
        proptest::collection::vec(drawn_instant(), 3),
        proptest::collection::vec(drawn_order(), 1..5),
    )
        .prop_map(|(decisions, orders)| DrawnStrategy::Orders { decisions, orders });
    let template = (
        1_u32..=12,
        1_u32..=24,
        any::<bool>(),
        any::<bool>(),
        proptest::collection::vec(drawn_row(), 1..8),
    )
        .prop_map(|(stop_ticks, target_ticks, signal_exit, flat_by, rows)| {
            DrawnStrategy::Template(DrawnTemplate {
                stop_ticks,
                target_ticks,
                signal_exit,
                flat_by,
                rows,
            })
        });
    prop_oneof![3 => orders, 2 => template]
}

fn drawn_month() -> impl Strategy<Value = DrawnMonth> {
    let fidelity = proptest::sample::select(vec![
        Fidelity::Tbbo,
        Fidelity::Trades,
        Fidelity::Bars(Timeframe::ONE_SECOND),
        Fidelity::Bars(Timeframe::ONE_MINUTE),
    ]);
    let settings = (
        prop_oneof![Just(0_u32), Just(100), Just(1_000)],
        (0_u32..=2, 0_u32..=2),
        any::<bool>(),
    );
    let span = || proptest::option::of((0_usize..160, 0_usize..160));
    (
        proptest::collection::vec(drawn_day(), 1..5),
        fidelity,
        drawn_strategy(),
        proptest::option::of((any::<bool>(), 1_i64..=3)),
        settings,
        span(),
        span(),
    )
        .prop_map(
            |(days, fidelity, strategy, opening, settings, closed, halted)| DrawnMonth {
                days,
                fidelity,
                strategy,
                opening,
                latency_milliseconds: settings.0,
                ticks: settings.1,
                touch: settings.2,
                closed,
                halted,
            },
        )
}

/// Each drawn trade date's walk of trades, with the quote before each, in order: the walk goes on
/// from one date to the next.
fn walks(month: &DrawnMonth) -> Vec<Vec<TbboRow>> {
    let mut price = OPENING_PRICE;
    let mut walks = Vec::new();
    for (number, day) in month.days.iter().enumerate() {
        let mut ts = day_start(number) + WALK_STARTS;
        let mut walk = Vec::new();
        for tick in &day.ticks {
            ts += tick.gap_milliseconds * MILLISECOND;
            price += tick.ticks_moved * TICK;
            let bid = price + tick.bid_ticks * TICK;
            walk.push(TbboRow {
                ts_recv: Ts(ts),
                price: Price(price),
                size: Qty(tick.size),
                bid: Price(bid),
                ask: Price(bid + tick.spread_ticks * TICK),
                bid_size: Qty(tick.bid_size),
                ask_size: Qty(tick.ask_size),
            });
        }
        walks.push(walk);
    }
    walks
}

fn day_start(number: usize) -> i64 {
    (i64::from(FIRST_DATE) + i64::try_from(number).unwrap()) * DAY
}

/// The bars of `length` nanoseconds that `walk` makes, one for each bucket of the UTC clock that
/// holds a trade.
fn bars_of(walk: &[TbboRow], length: i64) -> Vec<BarRow> {
    let mut bars: Vec<BarRow> = Vec::new();
    for trade in walk {
        let ts_open = Ts(trade.ts_recv.0 - trade.ts_recv.0.rem_euclid(length));
        match bars.last_mut() {
            Some(bar) if bar.ts_open == ts_open => {
                bar.high = bar.high.max(trade.price);
                bar.low = bar.low.min(trade.price);
                bar.close = trade.price;
                bar.volume = Qty(bar.volume.0 + trade.size.0);
            }
            _ => bars.push(BarRow {
                ts_open,
                ts_close: Ts(ts_open.0 + length),
                open: trade.price,
                high: trade.price,
                low: trade.price,
                close: trade.price,
                volume: trade.size,
            }),
        }
    }
    bars
}

fn length_of(timeframe: Timeframe) -> i64 {
    i64::try_from(timeframe.nominal_seconds()).unwrap() * SECOND
}

fn reader(month: &DrawnMonth, walks: &[Vec<TbboRow>]) -> InMemoryMarketData {
    let days = month
        .days
        .iter()
        .zip(walks)
        .enumerate()
        .map(|(number, (day, walk))| {
            let (tbbo, trades) = day.profile.ticks();
            let trade = |row: &TbboRow| TradeRow {
                ts_recv: row.ts_recv,
                price: row.price,
                size: row.size,
            };
            let bars = day
                .profile
                .timeframes()
                .into_iter()
                .map(|timeframe| (timeframe, bars_of(walk, length_of(timeframe))));
            TapeDay {
                trade_date: TradeDate(FIRST_DATE + i32::try_from(number).unwrap()),
                tbbo: if tbbo { walk.clone() } else { Vec::new() },
                trades: if trades {
                    walk.iter().map(trade).collect()
                } else {
                    Vec::new()
                },
                bars: bars.collect::<BTreeMap<_, _>>(),
            }
        });
    InMemoryMarketData::new(Contract("ESH2026".to_owned()), days.collect()).unwrap()
}

/// The drawn instant and the price of the trade beside it.
fn instant_of(drawn: DrawnInstant, walks: &[Vec<TbboRow>]) -> (Ts, Price) {
    let walk = &walks[drawn.day % walks.len()];
    let trade = walk[drawn.tick % walk.len()];
    let ts = trade.ts_recv.0;
    let close_of = |length: i64| ts - ts.rem_euclid(length) + length;
    let at = match drawn.offset {
        0 => ts,
        1 => ts - MILLISECOND,
        2 => ts + MILLISECOND,
        3 => ts - 100 * MILLISECOND,
        4 => ts + 100 * MILLISECOND,
        5 => close_of(SECOND),
        _ => close_of(60 * SECOND),
    };
    (Ts(at), trade.price)
}

fn side(buys: bool) -> Side {
    if buys { Side::Buy } else { Side::Sell }
}

fn scenario_orders(
    decisions: &[DrawnInstant],
    drawn: &[DrawnOrder],
    walks: &[Vec<TbboRow>],
) -> Vec<ScenarioOrder> {
    let mut placed = Vec::new();
    let mut group = None;
    for (index, order) in drawn.iter().enumerate() {
        let id = u64::try_from(index).unwrap() + 1;
        let (placed_at, near) = instant_of(decisions[order.decision % decisions.len()], walks);
        let order_side = side(order.buys);
        let level = Price(near.0 + order.away_ticks * TICK);
        let kind = match order.class {
            0 => OrderKind::Market,
            1 => OrderKind::StopMarket { stop: level },
            _ => OrderKind::Limit { limit: level },
        };
        let bracket = order.bracket.as_ref().map(|bracket| {
            let leg = |leg_id: u64, ticks: i64, against: bool| {
                let away = if against == (order_side == Side::Buy) {
                    -ticks
                } else {
                    ticks
                };
                let price = if bracket.in_ticks {
                    LegPrice::TicksFromFill(u32::try_from(ticks).unwrap())
                } else {
                    LegPrice::At(Price(level.0 + away * TICK))
                };
                BracketLeg {
                    id: Some(OrderId(leg_id)),
                    price,
                }
            };
            Bracket {
                stop: leg(id + 100, bracket.stop_ticks, true),
                target: leg(id + 200, bracket.target_ticks, false),
            }
        });
        let in_group = group.or(order.grouped_with_next.then_some(id));
        placed.push(ScenarioOrder {
            placed_at,
            id: OrderId(id),
            side: order_side,
            lots: Qty(order.lots),
            kind,
            oco: in_group.map(OcoGroupId),
            bracket,
        });
        group = if group.is_none() && order.grouped_with_next {
            Some(id)
        } else {
            None
        };
    }
    placed
}

fn template(drawn: &DrawnTemplate, walks: &[Vec<TbboRow>]) -> TemplateStrategy {
    let mut execution = serde_json::json!({
        "entry": {"kind": "market"},
        "stop": {"kind": "ticks", "ticks": drawn.stop_ticks},
        "targets": [{"price": {"kind": "ticks", "ticks": drawn.target_ticks}}],
        "sizing": {"kind": "fixed", "units": 1},
        "signal_exit": drawn.signal_exit
    });
    if drawn.flat_by {
        execution["time"] = serde_json::json!({"tz": "UTC", "flat_by": "15:00"});
    }
    let spec = serde_json::json!({
        "spec_version": 1, "instrument": "ES", "timeframe": "1m", "execution": execution
    });
    let spec: StrategySpec = serde_json::from_value(spec).unwrap();
    let mut by_close: BTreeMap<Ts, SignalRow> = BTreeMap::new();
    for row in &drawn.rows {
        let (ts_close, _) = instant_of(row.instant, walks);
        let day = usize::try_from(ts_close.0.div_euclid(DAY) - i64::from(FIRST_DATE)).unwrap();
        by_close.entry(ts_close).or_insert(SignalRow {
            ts_close,
            long_entry: row.entry == 1,
            short_entry: row.entry == 2,
            long_exit: row.long_exit,
            short_exit: row.short_exit,
            stop_price: None,
            target_price: None,
            size_mult: None,
            wake: row.wake,
            flat_by: drawn.flat_by.then(|| Ts(day_start(day) + FLAT_BY)),
        });
    }
    TemplateStrategy::new(&spec, by_close.into_values().collect(), &instrument()).unwrap()
}

fn instrument() -> InstrumentParameters {
    InstrumentParameters::new(Price(TICK), Money(MONEY_PER_POINT), LotStep(PRICE_UNITS)).unwrap()
}

/// Always open, or one session over the month closed from one drawn trade's instant to another's
/// and halted between two others.
fn hours(month: &DrawnMonth, walks: &[Vec<TbboRow>]) -> TradingHours {
    let instants: Vec<Ts> = walks.iter().flatten().map(|trade| trade.ts_recv).collect();
    let at = |index: usize| instants[index % instants.len()];
    let (first, last) = (Ts(day_start(0)), Ts(day_start(month.days.len())));
    let Some((one, other)) = month.closed else {
        return TradingHours::always();
    };
    let (closes, opens) = (at(one).min(at(other)), Ts(at(one).max(at(other)).0 + 1));
    let halts = month.halted.map_or_else(Vec::new, |(start, end)| {
        let (start, end) = (at(start).min(at(end)), at(start).max(at(end)));
        vec![Halt {
            start,
            end: Ts(end.0 + 1),
        }]
    });
    TradingHours::of_sessions(vec![
        Session {
            open: first,
            close: closes,
            halts: Vec::new(),
        },
        Session {
            open: opens,
            close: last,
            halts,
        },
    ])
}

/// What one replay of a case gave: its outputs or its error, and the records it skipped.
struct Replayed {
    outputs: Result<RunOutputs, RunError>,
    skipped: usize,
}

fn replayed(month: &DrawnMonth, replay: Replay) -> Replayed {
    let walks = walks(month);
    let reader = reader(month, &walks);
    let hours = hours(month, &walks);
    let settings = RunSettings {
        latency_milliseconds: month.latency_milliseconds,
        slippage: SlippageTicks {
            market: month.ticks.0,
            stop: month.ticks.1,
        },
        limit_fill: if month.touch {
            LimitFill::Touch
        } else {
            LimitFill::Through
        },
    };
    let ledger = match month.opening {
        None => Ledger::new(instrument(), Money(CAPITAL)),
        Some((buys, lots)) => Ledger::holding(
            instrument(),
            Money(CAPITAL),
            side(buys),
            Qty(lots),
            Price(OPENING_PRICE),
        )
        .unwrap(),
    };
    let mut strategy: Box<dyn RunStrategy> = match &month.strategy {
        DrawnStrategy::Orders { decisions, orders } => Box::new(ScenarioOrders::new(
            scenario_orders(decisions, orders, &walks),
        )),
        DrawnStrategy::Template(drawn) => Box::new(template(drawn, &walks)),
    };
    let mut run = TickRun::new(
        &reader,
        month.fidelity,
        replay,
        &hours,
        settings,
        ledger,
        strategy.as_mut(),
    )
    .unwrap();
    let mut skipped = 0;
    loop {
        match run.step() {
            Ok(Some(Stepped::Skipped { units })) => skipped += units,
            Ok(Some(_)) => {}
            Ok(None) => break,
            Err(error) => {
                return Replayed {
                    outputs: Err(error),
                    skipped,
                };
            }
        }
    }
    Replayed {
        outputs: run.run(),
        skipped,
    }
}

/// What the cases reached, so that agreement never means that nothing happened.
#[derive(Debug, Default)]
struct Coverage {
    cases: usize,
    cases_skipping: usize,
    skipped: usize,
    refused: usize,
    ambiguous: usize,
    fills: BTreeMap<String, usize>,
    profiles: BTreeMap<String, usize>,
}

#[test]
fn the_skipping_engine_fills_1000_generated_months_as_the_full_replay_does() {
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
    let outcome = runner.run(&drawn_month(), |month| {
        let full = replayed(&month, Replay::Full);
        let skipping = replayed(&month, Replay::Skipping);
        prop_assert_eq!(&skipping.outputs, &full.outputs, "{:?}", month);
        let mut seen = coverage.borrow_mut();
        seen.cases += 1;
        seen.skipped += skipping.skipped;
        seen.cases_skipping += usize::from(skipping.skipped > 0);
        for day in &month.days {
            *seen
                .profiles
                .entry(format!("{:?}", day.profile))
                .or_default() += 1;
        }
        let Ok(outputs) = &full.outputs else {
            seen.refused += 1;
            return Ok(());
        };
        prop_assert_eq!(
            skipping.outputs.as_ref().map(RunOutputs::ambiguous_fills),
            Ok(outputs.ambiguous_fills())
        );
        seen.ambiguous += outputs.ambiguous_fills();
        for booked in &outputs.fills {
            let fill = booked.fill;
            let key = format!("{} on {}", fill.rule.id(), fill.fidelity);
            *seen.fills.entry(key).or_default() += 1;
        }
        Ok(())
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    assert_eq!(coverage.cases, CASES as usize);
    assert_eq!(coverage.refused, 0, "{coverage:#?}");
    assert!(coverage.cases_skipping >= 300, "{coverage:#?}");
    assert!(coverage.ambiguous > 0, "{coverage:#?}");
    let rules: Vec<&str> = coverage.fills.keys().map(String::as_str).collect();
    for wanted in [
        "F-MKT-01 on tbbo",
        "F-MKT-02 on trades",
        "F-MKT-03 on 1s",
        "F-MKT-03 on 1m",
        "F-MKT-03 on 5m",
        "F-MKT-03 on 1d",
        "F-STP-02 on tbbo",
        "F-STP-03 on trades",
        "F-STP-04 on 1s",
        "F-STP-04 on 1m",
        "F-STP-05 on 1m",
        "F-LMT-03 on trades",
        "F-LMT-03 on 1m",
    ] {
        assert!(
            rules.contains(&wanted),
            "Expected fills by {wanted}, got {rules:?}"
        );
    }
    assert_eq!(coverage.profiles.len(), Profile::ALL.len(), "{coverage:#?}");
}
