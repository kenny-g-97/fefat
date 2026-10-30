//! Step 2.13's trade paths on hand-written tapes (`03-prop-simulator.md` §4.2): each fill at its
//! own price, where the tracking restarts; each new favourable extreme, and each new adverse one
//! since the last favourable; the mark at each whole minute from the entry's on, closed hours
//! included; the paths of a fill that reverses a position; and, on a bar, the adverse extreme a
//! favourable one may have come before (`docs/spec/fill-semantics.md` §15). A path across a roll
//! is in `roll_tests`.

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::market_data::InMemoryMarketData;
use fefat_core::orders::{OrderId, OrderKind, Side};
use fefat_core::units::{MONEY_UNITS, Money, Qty};

use super::tests::{
    HALF_PAST_TWO, at, es, flat, limit, minutes, order, price, run_orders, stop, trades,
};
use super::*;
use crate::hours::Session;
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
    // its assumed path falls 1 to the close. All of a bar's points are at its close (F-BAR-06),
    // the minute of the entry's fill among them, and the sell at the next bar's open closes it.
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
