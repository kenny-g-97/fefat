//! Step 2.7's Done means 2, skip equals no-skip: on generated months of mixed fidelity, the
//! skipping engine and the full replay give identical orders, fills, event logs, and ledgers, and
//! count the same ambiguous fills, over 1,000 cases under a fixed seed. A case draws one to four
//! trade dates, each holding the levels of a drawn profile (TBBO, trades, 1-second, 1-minute,
//! 5-minute, or daily bars, all built from one walk of trades with jumps and quiet minutes), the
//! finest fidelity it fills on, an order scenario or the template over drawn signal rows, flat-by
//! included, run settings, and trading hours with a break and a halt; and from step 2.9 a dated
//! fee table, funding times, and a roll between two dates, transferring or flattening, whose
//! instants bound the blocks a skip passes over (F-CLK-02). The cases must skip records, fill by
//! every rule on ticks and bars, pay fees and funding, and roll, so that agreement never means that
//! nothing happened.

use std::cell::RefCell;
use std::collections::BTreeMap;

use fefat_core::costs::{CostReason, FeeRate, FeeSchedule, FeeTable, FundingRate, Rate};
use fefat_core::fidelity::{Fidelity, TimeUnit, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, SECONDS_PER_DAY, TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, OrderRole, Side};
use fefat_core::rolls::{Roll, RollReason};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};

use super::{BookedFill, Replay, RunError, RunOutputs, Stepped, TickRun};
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::event_log::EventKind;
use crate::exit_plan::LivePlan;
use crate::hours::{Halt, Session, TradingHours};
use crate::settings::{LimitFill, RollHandling, RunCosts, RunSettings, SlippageTicks};
use crate::strategy::{ScenarioOrder, ScenarioOrders, Strategy as RunStrategy};
use crate::template::{RowFeatures, SignalRow, TemplateStrategy};

/// The run's seed, recorded in the pull request, so that a failure reproduces.
const SEED: u64 = 20_261_027;
const CASES: u32 = 1_000;
const TICK: i64 = 250_000_000;
const MONEY_PER_POINT: i64 = 50 * MONEY_UNITS;
pub(super) const CAPITAL: i64 = 50_000 * MONEY_UNITS;
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
    /// The row's feature for a trailing stop by a feature, in ticks.
    trail_ticks: u32,
}

#[derive(Debug, Clone)]
struct DrawnTemplate {
    stop_ticks: u32,
    target_ticks: u32,
    signal_exit: bool,
    flat_by: bool,
    rows: Vec<DrawnRow>,
    plan: DrawnPlan,
}

/// The rest of a drawn template's exit plan (step 2.8): a second target, each closing half of two
/// lots, a breakeven trigger in ticks, and a trailing stop: its ticks, whether it moves intrabar,
/// its activation in ticks, and whether it trails by the feature each row gives instead, whose
/// distance a decision can shorten while the market holds the stop below it (F-PLN-05).
#[derive(Debug, Clone)]
struct DrawnPlan {
    two_targets: bool,
    breakeven: Option<u32>,
    trailing: Option<(u32, bool, Option<u32>, bool)>,
}

#[derive(Debug, Clone)]
enum DrawnStrategy {
    Orders {
        decisions: Vec<DrawnInstant>,
        orders: Vec<DrawnOrder>,
    },
    Template(DrawnTemplate),
}

/// A drawn fee table (step 2.9): futures or crypto, the day its first schedule takes effect,
/// counted from the first trade date, and the fees of its two schedules, the second a day later:
/// cents per contract per side, or maker and taker rates in thousandths of a basis point, the
/// maker's below zero for a rebate.
#[derive(Debug, Clone)]
pub(super) struct DrawnFees {
    futures: bool,
    first_day: i32,
    first: (i64, i64),
    second: (i64, i64),
}

/// A drawn roll between two trade dates, at 13:00 UTC of the later one, its gap in ticks, its
/// reason, and whether it flattens.
#[derive(Debug, Clone)]
pub(super) struct DrawnRoll {
    day: usize,
    gap_ticks: i64,
    reason: u8,
    flattens: bool,
}

#[derive(Debug, Clone)]
pub(super) struct DrawnMonth {
    days: Vec<DrawnDay>,
    fidelity: Fidelity,
    strategy: DrawnStrategy,
    opening: Option<(bool, i64)>,
    latency_milliseconds: u32,
    ticks: (u32, u32),
    touch: bool,
    closed: Option<(usize, usize)>,
    halted: Option<(usize, usize)>,
    fees: Option<DrawnFees>,
    funding: Vec<(DrawnInstant, i64)>,
    roll: Option<DrawnRoll>,
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
        1_u32..=8,
    )
        .prop_map(
            |(instant, entry, long_exit, short_exit, wake, trail_ticks)| DrawnRow {
                instant,
                entry,
                long_exit,
                short_exit,
                wake,
                trail_ticks,
            },
        )
}

fn drawn_strategy() -> impl Strategy<Value = DrawnStrategy> {
    let orders = (
        proptest::collection::vec(drawn_instant(), 3),
        proptest::collection::vec(drawn_order(), 1..5),
    )
        .prop_map(|(decisions, orders)| DrawnStrategy::Orders { decisions, orders });
    let plan = (
        any::<bool>(),
        proptest::option::of(1_u32..=8),
        proptest::option::of((
            1_u32..=8,
            any::<bool>(),
            proptest::option::of(1_u32..=6),
            any::<bool>(),
        )),
    )
        .prop_map(|(two_targets, breakeven, trailing)| DrawnPlan {
            two_targets,
            breakeven,
            trailing,
        });
    let template = (
        1_u32..=12,
        1_u32..=24,
        any::<bool>(),
        any::<bool>(),
        proptest::collection::vec(drawn_row(), 1..8),
        plan,
    )
        .prop_map(
            |(stop_ticks, target_ticks, signal_exit, flat_by, rows, plan)| {
                DrawnStrategy::Template(DrawnTemplate {
                    stop_ticks,
                    target_ticks,
                    signal_exit,
                    flat_by,
                    rows,
                    plan,
                })
            },
        );
    prop_oneof![3 => orders, 2 => template]
}

fn drawn_fees() -> impl Strategy<Value = DrawnFees> {
    let fee = || (0_i64..=500, 0_i64..=500);
    (any::<bool>(), -1_i32..=3, fee(), fee()).prop_map(|(futures, first_day, first, second)| {
        DrawnFees {
            futures,
            first_day,
            first,
            second,
        }
    })
}

fn drawn_roll() -> impl Strategy<Value = DrawnRoll> {
    (0_usize..3, -40_i64..=40, 0_u8..4, any::<bool>()).prop_map(
        |(day, gap_ticks, reason, flattens)| DrawnRoll {
            day,
            gap_ticks,
            reason,
            flattens,
        },
    )
}

/// The drawn costs and roll of a month (step 2.9).
fn drawn_costs() -> impl Strategy<
    Value = (
        Option<DrawnFees>,
        Vec<(DrawnInstant, i64)>,
        Option<DrawnRoll>,
    ),
> {
    let funding = proptest::collection::vec((drawn_instant(), -1_000_000_i64..=1_000_000), 0..4);
    (
        proptest::option::of(drawn_fees()),
        funding,
        proptest::option::of(drawn_roll()),
    )
}

pub(super) fn drawn_month() -> impl Strategy<Value = DrawnMonth> {
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
        drawn_costs(),
    )
        .prop_map(
            |(days, fidelity, strategy, opening, settings, closed, halted, costs)| DrawnMonth {
                days,
                fidelity,
                strategy,
                opening,
                latency_milliseconds: settings.0,
                ticks: settings.1,
                touch: settings.2,
                closed,
                halted,
                fees: costs.0,
                funding: costs.1,
                roll: costs.2,
            },
        )
}

/// The month's fee table and funding rates, each funding time once, in order, after the month's
/// first mark, so that a position held when the tape starts mostly has a mark to pay at.
fn costs(month: &DrawnMonth, walks: &[Vec<TbboRow>]) -> RunCosts {
    let fees = month.fees.as_ref().map(|drawn| {
        let fee = |(first, second): (i64, i64)| match drawn.futures {
            true => FeeRate::Futures {
                per_contract_side: Money(first * 10_000),
            },
            false => FeeRate::Crypto {
                maker: Rate((first - 100) * 1_000),
                taker: Rate(second * 1_000),
            },
        };
        let from = |offset: i32| TradeDate(FIRST_DATE + drawn.first_day + offset);
        let schedules = vec![
            FeeSchedule {
                effective_from: from(0),
                fee: fee(drawn.first),
            },
            FeeSchedule {
                effective_from: from(1),
                fee: fee(drawn.second),
            },
        ];
        FeeTable::new(schedules).unwrap()
    });
    let marked_from = first_mark(month, walks);
    let mut funding: BTreeMap<Ts, Rate> = BTreeMap::new();
    for &(instant, rate) in &month.funding {
        let (ts, _) = instant_of(instant, walks);
        if marked_from.is_some_and(|first| ts > first) {
            funding.insert(ts, Rate(rate));
        }
    }
    let funding = funding
        .into_iter()
        .map(|(ts, rate)| FundingRate { ts, rate });
    RunCosts {
        fees,
        funding: funding.collect(),
    }
}

/// When the run first marks a position: the first trade of its first date at the level it fills
/// on, or the close of that trade's bar.
fn first_mark(month: &DrawnMonth, walks: &[Vec<TbboRow>]) -> Option<Ts> {
    let (day, walk) = month.days.first().zip(walks.first())?;
    let first = walk.first()?.ts_recv.0;
    let (tbbo, trades) = day.profile.ticks();
    let ticks = [(tbbo, Fidelity::Tbbo), (trades, Fidelity::Trades)];
    let ticks = ticks
        .into_iter()
        .filter(|(held, _)| *held)
        .map(|(_, level)| (level, 0));
    let timeframes = day.profile.timeframes().into_iter();
    let bars = timeframes.map(|timeframe| (Fidelity::Bars(timeframe), length_of(timeframe)));
    let (_, length) = ticks
        .chain(bars)
        .find(|(level, _)| *level >= month.fidelity)?;
    Some(Ts(match length {
        0 => first,
        _ => first - first.rem_euclid(length) + length,
    }))
}

/// The month's roll, between two of its dates, at 13:00 UTC of the later one, before its walk
/// starts; none for a month of one date.
pub(super) fn rolls(month: &DrawnMonth) -> (Vec<Roll>, RollHandling) {
    let (Some(drawn), true) = (&month.roll, month.days.len() > 1) else {
        return (Vec::new(), RollHandling::Transfer);
    };
    let day = 1 + drawn.day % (month.days.len() - 1);
    let reason = [
        RollReason::Volume,
        RollReason::OpenInterest,
        RollReason::Calendar,
        RollReason::Expiry,
    ][usize::from(drawn.reason % 4)];
    let roll = Roll {
        session_open: Ts(day_start(day) + 13 * 3_600 * SECOND),
        rolled_from: Contract("ESH2026".to_owned()),
        contract: Contract("ESM2026".to_owned()),
        gap: Price(drawn.gap_ticks * TICK),
        reason,
    };
    let handling = match drawn.flattens {
        true => RollHandling::Flatten,
        false => RollHandling::Transfer,
    };
    (vec![roll], handling)
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
    plan_of(&drawn.plan, drawn.target_ticks, &mut execution);
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
            long_entry: row.entry == 1,
            short_entry: row.entry == 2,
            long_exit: row.long_exit,
            short_exit: row.short_exit,
            wake: row.wake,
            flat_by: drawn.flat_by.then(|| Ts(day_start(day) + FLAT_BY)),
            features: RowFeatures {
                trailing: Some(f64::from(row.trail_ticks) * 250_000_000.0),
                ..RowFeatures::NONE
            },
            ..SignalRow::at(ts_close)
        });
    }
    TemplateStrategy::new(&spec, by_close.into_values().collect(), &instrument()).unwrap()
}

/// The drawn plan's second target, breakeven, and trailing stop, written into `execution`.
fn plan_of(plan: &DrawnPlan, target_ticks: u32, execution: &mut serde_json::Value) {
    let ticks = |ticks: u32| serde_json::json!({"kind": "ticks", "ticks": ticks});
    if plan.two_targets {
        execution["targets"] = serde_json::json!([
            {"price": ticks(target_ticks), "fraction": 0.5},
            {"price": ticks(target_ticks * 2)}
        ]);
        execution["sizing"] = serde_json::json!({"kind": "fixed", "units": 2});
    }
    if let Some(trigger) = plan.breakeven {
        execution["breakeven"] = serde_json::json!({"trigger": ticks(trigger)});
    }
    if let Some((distance, intrabar, activation, by_feature)) = plan.trailing {
        let update = if intrabar { "intrabar" } else { "bar_close" };
        let by = match by_feature {
            true => serde_json::json!({"kind": "atr", "multiple": 1.0, "feature": "atr"}),
            false => ticks(distance),
        };
        let mut trailing = serde_json::json!({"by": by, "update": update});
        if let Some(activation) = activation {
            trailing["activation"] = ticks(activation);
        }
        execution["trailing"] = trailing;
    }
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

/// What one replay of a case gave: its outputs or its error, the fills and the ledger it had
/// reached when refused, and the records it skipped.
struct Replayed {
    outputs: Result<RunOutputs, RunError>,
    refused_at: Option<(Vec<BookedFill>, Ledger)>,
    skipped: usize,
    skipped_trailing: usize,
}

fn replayed(month: &DrawnMonth, replay: Replay) -> Replayed {
    with_month(month, replay, |mut run| {
        let (mut skipped, mut skipped_trailing) = (0, 0);
        loop {
            match run.step() {
                Ok(Some(Stepped::Skipped { units })) => {
                    skipped += units;
                    // F-PLN-05: a skip that a live trailing stop allowed, its bar not past the best
                    // price.
                    if run.book.plans().any(LivePlan::trails) {
                        skipped_trailing += units;
                    }
                }
                Ok(Some(_)) => {}
                Ok(None) => break,
                Err(error) => {
                    return Replayed {
                        outputs: Err(error),
                        refused_at: Some((run.fills().to_vec(), run.ledger().clone())),
                        skipped,
                        skipped_trailing,
                    };
                }
            }
        }
        Replayed {
            outputs: run.run(),
            refused_at: None,
            skipped,
            skipped_trailing,
        }
    })
}

/// `inspect` given the run of `month`, replayed as `replay`, before its first step.
pub(super) fn with_month<T>(
    month: &DrawnMonth,
    replay: Replay,
    inspect: impl FnOnce(TickRun<'_, InMemoryMarketData>) -> T,
) -> T {
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
    let (rolls, handling) = rolls(month);
    let run = TickRun::new(
        &reader,
        month.fidelity,
        replay,
        &hours,
        settings,
        ledger,
        strategy.as_mut(),
    )
    .unwrap()
    .with_costs(costs(month, &walks))
    .unwrap()
    .with_rolls(rolls, handling)
    .unwrap();
    inspect(run)
}

/// What the cases reached, so that agreement never means that nothing happened.
#[derive(Debug, Default)]
struct Coverage {
    cases: usize,
    cases_skipping: usize,
    skipped: usize,
    refused: usize,
    /// Months whose stop, triggered on TBBO, meets a tradeable trade or bar before a quote,
    /// which both replays refuse alike, since F-STP-02 prices such a fill from a quote alone.
    unquoted: usize,
    /// Months that pay funding on a position held when the tape starts before its first
    /// tradeable record, without a mark, which both replays refuse alike (F-FND-01).
    unmarked: usize,
    /// Fee and funding lines paid, warnings of a fee table's first schedule taken before its
    /// date, and roll legs filled (step 2.9).
    fee_lines: usize,
    funding_lines: usize,
    extended: usize,
    roll_legs: usize,
    ambiguous: usize,
    /// Stops moved by an exit plan, by the rule that moved them (F-BRK-01, F-TRL-01).
    moves: BTreeMap<&'static str, usize>,
    /// Records skipped while a trailing stop was live, each bar no higher than its best price.
    skipped_trailing: usize,
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
        prop_assert_eq!(&skipping.refused_at, &full.refused_at, "{:?}", month);
        let mut seen = coverage.borrow_mut();
        seen.cases += 1;
        seen.skipped += skipping.skipped;
        seen.skipped_trailing += skipping.skipped_trailing;
        seen.cases_skipping += usize::from(skipping.skipped > 0);
        for day in &month.days {
            *seen
                .profiles
                .entry(format!("{:?}", day.profile))
                .or_default() += 1;
        }
        let outputs = match &full.outputs {
            Ok(outputs) => outputs,
            Err(RunError::TriggeredWithoutQuotes { .. }) => {
                seen.unquoted += 1;
                return Ok(());
            }
            Err(RunError::FundingWithoutMark { .. }) => {
                seen.unmarked += 1;
                return Ok(());
            }
            Err(_) => {
                seen.refused += 1;
                return Ok(());
            }
        };
        prop_assert_eq!(
            skipping.outputs.as_ref().map(RunOutputs::ambiguous_fills),
            Ok(outputs.ambiguous_fills())
        );
        seen.ambiguous += outputs.ambiguous_fills();
        let moves = outputs
            .log
            .iter()
            .filter(|entry| entry.kind == EventKind::Moved);
        for rule in moves.filter_map(|entry| entry.rule) {
            *seen.moves.entry(rule).or_default() += 1;
        }
        for booked in &outputs.fills {
            let fill = booked.fill;
            let key = format!("{} on {}", fill.rule.id(), fill.fidelity);
            *seen.fills.entry(key).or_default() += 1;
            seen.roll_legs += usize::from(matches!(fill.role, OrderRole::Roll(_)));
        }
        for line in &outputs.cost_lines {
            match line.reason {
                CostReason::Fee { .. } => seen.fee_lines += 1,
                CostReason::Funding { .. } => seen.funding_lines += 1,
            }
        }
        let warnings = outputs
            .log
            .iter()
            .filter(|entry| entry.kind == EventKind::Warning);
        seen.extended += warnings.count();
        Ok(())
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    assert_eq!(coverage.cases, CASES as usize);
    assert_eq!(coverage.refused, 0, "{coverage:#?}");
    assert!(coverage.unquoted <= CASES as usize / 100, "{coverage:#?}");
    assert!(coverage.unmarked <= CASES as usize / 50, "{coverage:#?}");
    for paid in [
        coverage.fee_lines,
        coverage.funding_lines,
        coverage.extended,
        coverage.roll_legs,
    ] {
        assert!(paid > 0, "{coverage:#?}");
    }
    assert!(coverage.cases_skipping >= 300, "{coverage:#?}");
    assert!(coverage.ambiguous > 0, "{coverage:#?}");
    assert!(coverage.skipped_trailing > 0, "{coverage:#?}");
    for rule in ["F-BRK-01", "F-TRL-01"] {
        assert!(coverage.moves.contains_key(rule), "{coverage:#?}");
    }
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
