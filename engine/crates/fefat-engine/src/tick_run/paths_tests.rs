//! Step 2.13's trade paths on hand-written tapes (`03-prop-simulator.md` §4.2): each fill at its
//! own price, where the tracking restarts; each new favourable extreme, and each new adverse one
//! since the last favourable; the mark at each whole minute from the entry's on, closed hours
//! included; the paths of a fill that reverses a position; and, on a bar, the adverse extreme a
//! favourable one may have come before (`docs/spec/fill-semantics.md` §15), for a long and a
//! short; a path's fidelity across a day of trades and a day of bars; and a partial exit's fill
//! in the trade's excursions. A path across a roll is in `roll_tests`.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TradeRow};
use fefat_core::orders::{OrderId, OrderKind, Side};
use fefat_core::units::{MONEY_UNITS, Money, Qty};

use super::tests::{
    HALF_PAST_TWO, TRADE_DATE, at, es, flat, limit, minutes, order, price, run_orders, stop, trades,
};
use super::*;
use crate::hours::Session;
use crate::settings::LimitFill;
use crate::strategy::{ScenarioOrder, ScenarioOrders};
use PathPointKind::{Adverse, Favourable, Minute, PossibleAdverse};

/// Each point's milliseconds after 14:30, its price in hundredths, and its kind.
fn points(path: &TradePath) -> Vec<(i64, i64, PathPointKind)> {
    let point = |point: &PathPoint| {
        let milliseconds = (point.ts.0 - HALF_PAST_TWO) / 1_000_000;
        (milliseconds, point.price.0 / 10_000_000, point.kind)
    };
    path.points.iter().map(point).collect()
}

const fn fill(order: u64) -> PathPointKind {
    PathPointKind::Fill(OrderId(order))
}

const fn minute() -> Fidelity {
    Fidelity::Bars(Timeframe::ONE_MINUTE)
}

/// `orders` on `reader`'s trades from flat, open during `hours`, recording `recording`.
fn run_on_trades(
    reader: &InMemoryMarketData,
    hours: &TradingHours,
    orders: Vec<ScenarioOrder>,
    recording: Recording,
) -> RunOutputs {
    let settings = RunSettings::defaults_for(Fidelity::Trades);
    let mut strategy = ScenarioOrders::new(orders);
    let run = TickRun::new(
        reader,
        Fidelity::Trades,
        Replay::Full,
        hours,
        settings,
        flat(),
        &mut strategy,
    );
    run.unwrap().with_recording(recording).run().unwrap()
}

/// A long of 2 lots bought at the market, whose limit at 5002.00 sells one lot at 70 s and a
/// market order placed at 120 s the other at 125 s.
fn long_closed_in_parts() -> (InMemoryMarketData, Vec<ScenarioOrder>) {
    let reader = trades(&[
        (200, 500_000, 5),
        (10_000, 500_050, 1),
        (20_000, 499_975, 1),
        (30_000, 500_025, 1),
        (60_000, 500_100, 1),
        (70_000, 500_225, 1),
        (100_000, 500_125, 1),
        (125_000, 500_175, 1),
    ]);
    let orders = vec![
        ScenarioOrder {
            lots: Qty(2),
            ..order(1, Side::Buy, OrderKind::Market)
        },
        order(2, Side::Sell, limit(500_200)),
        ScenarioOrder {
            placed_at: at(120_000),
            ..order(3, Side::Sell, OrderKind::Market)
        },
    ];
    (reader, orders)
}

#[test]
fn a_longs_path_keeps_its_fills_its_new_extremes_and_the_mark_at_each_minute() {
    // The long buys at 5000.25, a tick above the trade (F-MKT-02). The record at 60 s, on the
    // whole minute, sets that minute's mark, recorded once a later record arrives. Each fill and
    // each minute restarts the tracking, so that 5002.25 after the limit's fill at 5002.00 is a
    // new favourable extreme, and 5000.25 at 30 s, between the extremes since 10 s, is none.
    let (reader, orders) = long_closed_in_parts();

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    let [path] = outputs.trade_paths.as_slice() else {
        panic!("Expected one path, got {:?}", outputs.trade_paths);
    };
    assert_eq!(
        points(path),
        [
            (200, 500_025, fill(1)),
            (200, 500_000, Adverse),
            (10_000, 500_050, Favourable),
            (20_000, 499_975, Adverse),
            (60_000, 500_100, Favourable),
            (60_000, 500_100, Minute),
            (70_000, 500_200, fill(2)),
            (70_000, 500_225, Favourable),
            (100_000, 500_125, Adverse),
            (120_000, 500_125, Minute),
            (125_000, 500_150, fill(3)),
        ]
    );
}

#[test]
fn a_trades_summary_comes_from_its_marks_and_its_exits_and_its_path_ends_at_its_last_exit() {
    // The marks and exits of the long closed in parts reach 4999.75, 2 ticks against it, and
    // 5002.25, 8 for it; its deepest fall from the best before it is from 5002.25 to 5001.25, 4
    // ticks, deeper than the 3 from 5000.50 to 4999.75: 100.00 over its 2 lots.
    let (reader, orders) = long_closed_in_parts();

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!((trade.mae_ticks, trade.mfe_ticks), (2, 8));
    assert_eq!(
        (trade.max_drawdown_ticks, trade.max_drawdown),
        (4, Money(100 * MONEY_UNITS))
    );
    assert_eq!(trade.path_fidelity, Fidelity::Trades);
    let lowest = path.points.iter().map(|point| point.price).min();
    let tick = es().tick_size().0;
    assert_eq!(
        lowest,
        Some(Price(trade.entry_price.0 - trade.mae_ticks * tick))
    );
    assert_eq!(
        path.points.last().map(|point| point.price),
        Some(price(500_150))
    );
}

#[test]
fn a_run_without_paths_fills_and_closes_its_trades_as_a_run_with_them() {
    // `run_batch`'s trials may leave paths out (`02` §7): recording is a pure observer.
    let (reader, orders) = long_closed_in_parts();
    let hours = TradingHours::always();

    let with = run_on_trades(&reader, &hours, orders.clone(), Recording::Paths);
    let without = run_on_trades(&reader, &hours, orders, Recording::TradesOnly);

    assert_eq!(without.trade_paths, []);
    assert_eq!(with.trade_paths.len(), 1);
    assert_eq!(
        (&without.fills, &without.trades),
        (&with.fills, &with.trades)
    );
    assert_eq!((&without.orders, &without.log), (&with.orders, &with.log));
}

#[test]
fn a_path_across_a_session_break_marks_each_minute_of_the_break_at_the_last_mark() {
    // The session closes at 14:32 and opens again at 14:35: the trade at 14:33 is received while
    // the market is closed and sets no mark (F-SES-02), so the minutes from 14:32 to 14:35 take
    // 5001.00, the last mark before the close; the stop at 4999.50 fills at the first trade after
    // the open, 4999.00, the gap's price (F-STP-03).
    let reader = trades(&[
        (200, 500_000, 5),
        (30_000, 500_075, 1),
        (90_000, 500_100, 1),
        (180_000, 499_000, 1),
        (305_000, 499_900, 1),
    ]);
    let hours = TradingHours::of_sessions(vec![
        Session {
            open: at(-3_600_000),
            close: at(120_000),
            halts: Vec::new(),
        },
        Session {
            open: at(300_000),
            close: at(3_600_000),
            halts: Vec::new(),
        },
    ]);
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        order(2, Side::Sell, stop(499_950)),
    ];

    let outputs = run_on_trades(&reader, &hours, orders, Recording::Paths);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!(
        points(path),
        [
            (200, 500_025, fill(1)),
            (200, 500_000, Adverse),
            (30_000, 500_075, Favourable),
            (60_000, 500_075, Minute),
            (90_000, 500_100, Favourable),
            (120_000, 500_100, Minute),
            (180_000, 500_100, Minute),
            (240_000, 500_100, Minute),
            (300_000, 500_100, Minute),
            (305_000, 499_900, fill(2)),
        ]
    );
    assert_eq!(
        (trade.mae_ticks, trade.mfe_ticks, trade.max_drawdown_ticks),
        (5, 3, 8)
    );
}

#[test]
fn a_fill_that_reverses_a_long_ends_its_path_and_starts_the_shorts_at_its_price() {
    // S-fill-042: the sell of 2 lots at 5000.75 closes the long and opens the short; the mark of
    // its record, 5001.00, is the short's, against it, and the buy at 4999.25 closes the short
    // before its record marks 4999.00.
    let reader = trades(&[(200, 500_000, 5), (1_200, 500_100, 5), (2_200, 499_900, 5)]);
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(1_000),
            lots: Qty(2),
            ..order(2, Side::Sell, OrderKind::Market)
        },
        ScenarioOrder {
            placed_at: at(2_000),
            ..order(3, Side::Buy, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    let [long, short] = outputs.trade_paths.as_slice() else {
        panic!("Expected two paths, got {:?}", outputs.trade_paths);
    };
    assert_eq!(
        points(long),
        [
            (200, 500_025, fill(1)),
            (200, 500_000, Adverse),
            (1_200, 500_075, fill(2)),
        ]
    );
    assert_eq!(
        points(short),
        [
            (1_200, 500_075, fill(2)),
            (1_200, 500_100, Adverse),
            (2_200, 499_925, fill(3)),
        ]
    );
}

#[test]
fn a_bar_that_takes_a_long_to_a_new_high_above_its_low_below_its_close_flags_that_low() {
    // §15 of the fill specification: the long bought at the open of the first bar, 5000.25 on
    // 1-minute bars (F-MKT-03), is followed by the move against it, the low first (F-BAR-04), then
    // the high, 5000.50, a new favourable extreme while the low, 4999.75, lies below the close,
    // 5000.25: the bar may have reached its low after its high, a fall of 3 ticks from it, where
    // its assumed path falls 1 to the close, which the trade's fall from its peak follows. All of
    // a bar's points are at its close (F-BAR-06), the minute of the entry's fill among them, and
    // the sell at the next bar's open closes it.
    let reader = minutes(&[
        (0, [500_000, 500_050, 499_975, 500_025], 10),
        (1, [500_050, 500_100, 500_025, 500_075], 10),
    ]);
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(60_000),
            ..order(2, Side::Sell, OrderKind::Market)
        },
    ];
    let minute = Fidelity::Bars(Timeframe::ONE_MINUTE);

    let outputs = run_orders(&reader, minute, flat(), orders);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!(
        points(path),
        [
            (60_000, 500_025, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 499_975, Adverse),
            (60_000, 500_050, Favourable),
            (60_000, 499_975, PossibleAdverse),
            (60_000, 500_025, Adverse),
            (60_000, 500_025, Minute),
            (120_000, 500_025, fill(2)),
        ]
    );
    assert_eq!(
        (trade.mae_ticks, trade.mfe_ticks, trade.max_drawdown_ticks),
        (2, 1, 2)
    );
    assert_eq!(trade.path_fidelity, minute);
}

/// The milliseconds in a day, from 14:30 on 2026-03-06 to 14:30 on 03-07.
const DAY: i64 = 86_400_000;

#[test]
fn a_trade_held_from_a_day_of_trades_into_a_day_of_bars_has_a_path_of_bars() {
    // `03-prop-simulator.md` §4.4, D-65: the long buys on 03-06's trades and sells on 03-07's
    // 1-minute bars, so its path is only as exact as its bars: its fidelity is the coarsest
    // level its marks and fills came from, `1m`, though its entry filled on trades.
    let trades_day = TapeDay {
        trade_date: TRADE_DATE,
        tbbo: Vec::new(),
        trades: vec![TradeRow {
            ts_recv: at(200),
            price: price(500_000),
            size: Qty(5),
        }],
        bars: Default::default(),
    };
    let bar = |minute: i64, [open, high, low, close]: [i64; 4]| BarRow {
        ts_open: at(DAY + minute * 60_000),
        ts_close: at(DAY + (minute + 1) * 60_000),
        open: price(open),
        high: price(high),
        low: price(low),
        close: price(close),
        volume: Qty(10),
    };
    let bars_day = TapeDay {
        trade_date: TradeDate(TRADE_DATE.0 + 1),
        tbbo: Vec::new(),
        trades: Vec::new(),
        bars: BTreeMap::from([(
            Timeframe::ONE_MINUTE,
            vec![
                bar(0, [500_050, 500_075, 500_025, 500_050]),
                bar(1, [500_100, 500_125, 500_075, 500_100]),
            ],
        )]),
    };
    let reader =
        InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![trades_day, bars_day])
            .unwrap();
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(DAY + 60_000),
            ..order(2, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    let entry = outputs.fills.first().map(|booked| booked.fill.fidelity);
    assert_eq!(entry, Some(Fidelity::Trades));
    assert_eq!(trade.path_fidelity, Fidelity::Bars(Timeframe::ONE_MINUTE));
}

#[test]
fn a_bar_that_takes_a_short_to_a_new_low_below_its_high_above_its_close_flags_that_high() {
    // §15 of the fill specification, mirrored: the short sold at the open of the first bar,
    // 4999.75, meets the bar's high first (F-BAR-04), then its low, 4999.50, a new favourable
    // extreme while the high, 5000.25, lies above the close, 4999.75: the bar may have reached
    // its high after its low.
    let reader = minutes(&[
        (0, [500_000, 500_025, 499_950, 499_975], 10),
        (1, [499_950, 500_000, 499_925, 499_975], 10),
    ]);
    let orders = vec![
        order(1, Side::Sell, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(60_000),
            ..order(2, Side::Buy, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, minute(), flat(), orders);

    let [path] = outputs.trade_paths.as_slice() else {
        panic!("Expected one path, got {:?}", outputs.trade_paths);
    };
    assert_eq!(
        points(path),
        [
            (60_000, 499_975, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 500_025, Adverse),
            (60_000, 499_950, Favourable),
            (60_000, 500_025, PossibleAdverse),
            (60_000, 499_975, Adverse),
            (60_000, 499_975, Minute),
            (120_000, 499_975, fill(2)),
        ]
    );
}

#[test]
fn a_bar_whose_adverse_extreme_is_its_close_flags_nothing() {
    // §15: a long's new high in a bar whose low is its close falls to that low in either order,
    // so the path keeps no possible adverse extreme.
    let reader = minutes(&[
        (0, [500_000, 500_050, 499_975, 499_975], 10),
        (1, [500_000, 500_025, 499_975, 500_000], 10),
    ]);
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(60_000),
            ..order(2, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, minute(), flat(), orders);

    let [path] = outputs.trade_paths.as_slice() else {
        panic!("Expected one path, got {:?}", outputs.trade_paths);
    };
    assert_eq!(
        points(path),
        [
            (60_000, 500_025, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 499_975, Adverse),
            (60_000, 500_050, Favourable),
            (60_000, 499_975, Adverse),
            (60_000, 499_975, Minute),
            (120_000, 499_975, fill(2)),
        ]
    );
}

#[test]
fn a_partial_exits_fill_beyond_every_mark_is_the_trades_most_adverse_price() {
    // D-65's second reading: the stop that sells one of the long's 2 lots at 4999.00 fills a
    // tick below it on trades, 4998.75 (F-STP-03), below every price the run marks, so the
    // trade's MAE is 6 ticks from its entry at 5000.25, not the 5 of its lowest mark, 4999.00;
    // its fall from its peak, 5000.25 at its entry, is the same 6 ticks.
    let reader = trades(&[
        (200, 500_000, 5),
        (10_000, 499_900, 5),
        (20_000, 500_050, 5),
        (30_000, 500_075, 5),
    ]);
    let orders = vec![
        ScenarioOrder {
            lots: Qty(2),
            ..order(1, Side::Buy, OrderKind::Market)
        },
        order(2, Side::Sell, stop(499_900)),
        ScenarioOrder {
            placed_at: at(25_000),
            ..order(3, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    let prices: Vec<i64> = outputs
        .fills
        .iter()
        .map(|booked| booked.fill.price.0 / 10_000_000)
        .collect();
    assert_eq!(prices, [500_025, 499_875, 500_050]);
    assert_eq!(trade.exits, 2);
    assert_eq!(
        (trade.mae_ticks, trade.mfe_ticks, trade.max_drawdown_ticks),
        (6, 1, 6)
    );
}

/// `orders` on 1-minute `bars` from flat, under `limit_fill`.
fn run_on_minutes(
    bars: &[(i64, [i64; 4], i64)],
    orders: Vec<ScenarioOrder>,
    limit_fill: LimitFill,
) -> RunOutputs {
    let reader = minutes(bars);
    let settings = RunSettings {
        limit_fill,
        ..RunSettings::defaults_for(minute())
    };
    let hours = TradingHours::always();
    let mut strategy = ScenarioOrders::new(orders);
    let run = TickRun::new(
        &reader,
        minute(),
        Replay::Full,
        &hours,
        settings,
        flat(),
        &mut strategy,
    );
    run.unwrap().run().unwrap()
}

#[test]
fn a_target_that_fills_at_a_bars_new_high_flags_the_bars_low_after_it() {
    // The engine-accuracy review, §15: the long of 2 lots meets the second bar's low, 5000.00,
    // first (F-BAR-02), then its limit at 5002.00 sells a lot at the bar's high (F-LMT-02, touch),
    // which restarts the tracking there, so the high itself is no new extreme. The position still
    // reached a new high while the low lies below the close, 5001.00, so the low follows as a
    // possible adverse extreme, while the trade's fall from its peak follows the bar path, 5 ticks
    // from 5002.00 to the last lot's sale at 5000.75.
    let bars = [
        (0, [500_000, 500_050, 499_975, 500_025], 10),
        (1, [500_025, 500_200, 500_000, 500_100], 10),
        (2, [500_100, 500_125, 500_075, 500_100], 10),
    ];
    let orders = vec![
        ScenarioOrder {
            lots: Qty(2),
            ..order(1, Side::Buy, OrderKind::Market)
        },
        order(2, Side::Sell, limit(500_200)),
        ScenarioOrder {
            placed_at: at(120_000),
            ..order(3, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_on_minutes(&bars, orders, LimitFill::Touch);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!(
        points(path),
        [
            (60_000, 500_025, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 499_975, Adverse),
            (60_000, 500_050, Favourable),
            (60_000, 499_975, PossibleAdverse),
            (60_000, 500_025, Adverse),
            (60_000, 500_025, Minute),
            (120_000, 500_000, Adverse),
            (120_000, 500_200, fill(2)),
            (120_000, 500_000, PossibleAdverse),
            (120_000, 500_100, Adverse),
            (120_000, 500_100, Minute),
            (180_000, 500_075, fill(3)),
        ]
    );
    assert_eq!(trade.max_drawdown_ticks, 5);
}

#[test]
fn an_addition_that_fills_past_a_bars_high_flags_the_bars_low_after_the_high() {
    // The engine-accuracy review, §15: the long's buy stop at 5001.50 adds a lot on the way to
    // the second bar's high and fills a tick past it, 5001.75 (F-STP-04), so the high, 5001.50,
    // is below the tracking's restart. It is still the bar's new high since the minute, and the
    // low, 5000.00, lies below the close, 5000.75, so the low follows it as a possible adverse
    // extreme. An addition moves no excursion, and the trade's fall from its peak follows the
    // bar path, 4 ticks from 5001.50 to the sale at 5000.50.
    let bars = [
        (0, [500_000, 500_050, 499_975, 500_025], 10),
        (1, [500_050, 500_150, 500_000, 500_075], 10),
        (2, [500_075, 500_100, 500_050, 500_075], 10),
    ];
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        order(2, Side::Buy, stop(500_150)),
        ScenarioOrder {
            placed_at: at(120_000),
            lots: Qty(2),
            ..order(3, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_on_minutes(&bars, orders, LimitFill::Through);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!(
        points(path),
        [
            (60_000, 500_025, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 499_975, Adverse),
            (60_000, 500_050, Favourable),
            (60_000, 499_975, PossibleAdverse),
            (60_000, 500_025, Adverse),
            (60_000, 500_025, Minute),
            (120_000, 500_050, Favourable),
            (120_000, 500_000, Adverse),
            (120_000, 500_175, fill(2)),
            (120_000, 500_150, Adverse),
            (120_000, 500_000, PossibleAdverse),
            (120_000, 500_075, Adverse),
            (120_000, 500_075, Minute),
            (180_000, 500_050, fill(3)),
        ]
    );
    assert_eq!(
        (trade.mae_ticks, trade.mfe_ticks, trade.max_drawdown_ticks),
        (2, 5, 4)
    );
}

#[test]
fn a_bar_whose_new_high_beats_an_addition_inside_it_flags_its_low_after_the_high() {
    // The ponytail review, §15: the long's first bar takes it to 5002.25, its best before the
    // second bar. The second bar opens at 5001.75, where a buy limit adds 3 lots (F-LMT-02,
    // touch), which restarts the tracking there, below that best; its high, 5002.00, is a new
    // favourable extreme since the addition while its low, 5001.00, lies below its close, 5001.50,
    // so the low follows the high as a possible adverse extreme, as it does after a new best.
    let bars = [
        (0, [500_000, 500_225, 500_000, 500_225], 10),
        (1, [500_175, 500_200, 500_100, 500_150], 10),
        (2, [500_150, 500_175, 500_125, 500_150], 10),
    ];
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(60_000),
            lots: Qty(3),
            ..order(2, Side::Buy, limit(500_175))
        },
        ScenarioOrder {
            placed_at: at(120_000),
            lots: Qty(4),
            ..order(3, Side::Sell, OrderKind::Market)
        },
    ];

    let outputs = run_on_minutes(&bars, orders, LimitFill::Touch);

    let ([trade], [path]) = (outputs.trades.as_slice(), outputs.trade_paths.as_slice()) else {
        panic!("Expected one trade and its path, got {outputs:?}");
    };
    assert_eq!(
        points(path),
        [
            (60_000, 500_025, fill(1)),
            (60_000, 500_000, Adverse),
            (60_000, 500_225, Favourable),
            (60_000, 500_000, PossibleAdverse),
            (60_000, 500_225, Minute),
            (120_000, 500_175, fill(2)),
            (120_000, 500_100, Adverse),
            (120_000, 500_200, Favourable),
            (120_000, 500_100, PossibleAdverse),
            (120_000, 500_150, Adverse),
            (120_000, 500_150, Minute),
            (180_000, 500_125, fill(3)),
        ]
    );
    assert_eq!(
        (trade.mae_ticks, trade.mfe_ticks, trade.max_drawdown_ticks),
        (1, 8, 5)
    );
}
