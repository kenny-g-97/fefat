//! The sample tape the conformance checks serve and compare: one contract, two trade dates, and
//! every level, small enough to check each offset by hand.

use std::collections::BTreeMap;

use crate::fidelity::Timeframe;
use crate::instants::{NANOSECONDS_PER_SECOND, SECONDS_PER_DAY, TradeDate, Ts};
use crate::market_data::{BarRow, TapeDay, TbboRow, TradeRow};
use crate::units::{Price, Qty};

/// The contract of the sample tape.
pub const SAMPLE_CONTRACT: &str = "ESH2026";
/// 2026-03-05: six trades, as TBBO records and as trades, with their 1-second and 1-minute bars.
pub const FIRST_DAY: TradeDate = TradeDate(20_517);
/// 2026-03-06: two 5-minute bars and nothing finer, as an import's finest data (D-49).
pub const SECOND_DAY: TradeDate = TradeDate(20_518);

const TRADES: [TradeRow; 6] = [
    trade(at(FIRST_DAY, 14, 30, 0, 100), 500_000, 3),
    trade(at(FIRST_DAY, 14, 30, 0, 600), 500_025, 1),
    trade(at(FIRST_DAY, 14, 30, 1, 200), 499_975, 2),
    trade(at(FIRST_DAY, 14, 30, 2, 0), 500_050, 4),
    trade(at(FIRST_DAY, 14, 31, 0, 500), 500_100, 1),
    trade(at(FIRST_DAY, 14, 31, 30, 0), 500_075, 2),
];

/// The bid, the ask, and their sizes just before each of the trades.
const QUOTES: [(i64, i64, i64, i64); 6] = [
    (499_975, 500_000, 10, 8),
    (500_000, 500_025, 7, 5),
    (499_975, 500_000, 6, 9),
    (500_025, 500_050, 4, 3),
    (500_075, 500_100, 2, 6),
    (500_075, 500_100, 5, 4),
];

#[rustfmt::skip]
const SECOND_BARS: [BarRow; 5] = [
    bar(at(FIRST_DAY, 14, 30, 0, 0), 1, [500_000, 500_025, 500_000, 500_025], 4),
    bar(at(FIRST_DAY, 14, 30, 1, 0), 1, [499_975, 499_975, 499_975, 499_975], 2),
    bar(at(FIRST_DAY, 14, 30, 2, 0), 1, [500_050, 500_050, 500_050, 500_050], 4),
    bar(at(FIRST_DAY, 14, 31, 0, 0), 1, [500_100, 500_100, 500_100, 500_100], 1),
    bar(at(FIRST_DAY, 14, 31, 30, 0), 1, [500_075, 500_075, 500_075, 500_075], 2),
];

#[rustfmt::skip]
const MINUTE_BARS: [BarRow; 2] = [
    bar(at(FIRST_DAY, 14, 30, 0, 0), 60, [500_000, 500_050, 499_975, 500_050], 10),
    bar(at(FIRST_DAY, 14, 31, 0, 0), 60, [500_100, 500_100, 500_075, 500_075], 3),
];

#[rustfmt::skip]
const FIVE_MINUTE_BARS: [BarRow; 2] = [
    bar(at(SECOND_DAY, 14, 30, 0, 0), 300, [501_000, 501_250, 500_825, 501_100], 120),
    bar(at(SECOND_DAY, 14, 35, 0, 0), 300, [501_100, 501_175, 500_650, 500_725], 95),
];

/// The sample tape of [`SAMPLE_CONTRACT`]: on [`FIRST_DAY`], six ES trades from 14:30:00.1 to
/// 14:31:30 UTC as TBBO records with the quotes before them and as trades, with their five
/// 1-second and two 1-minute bars; on [`SECOND_DAY`], two 5-minute bars and nothing finer.
pub fn sample_tape() -> Vec<TapeDay> {
    let tbbo = TRADES
        .iter()
        .zip(QUOTES)
        .map(|(trade, quote)| quoted(*trade, quote));
    let first_day = TapeDay {
        trade_date: FIRST_DAY,
        tbbo: tbbo.collect(),
        trades: TRADES.to_vec(),
        bars: BTreeMap::from([
            (Timeframe::ONE_SECOND, SECOND_BARS.to_vec()),
            (Timeframe::ONE_MINUTE, MINUTE_BARS.to_vec()),
        ]),
    };
    let second_day = TapeDay {
        trade_date: SECOND_DAY,
        tbbo: Vec::new(),
        trades: Vec::new(),
        bars: BTreeMap::from([(Timeframe::FIVE_MINUTES, FIVE_MINUTE_BARS.to_vec())]),
    };
    vec![first_day, second_day]
}

const fn at(day: TradeDate, hour: i64, minute: i64, second: i64, millisecond: i64) -> Ts {
    let seconds = day.0 as i64 * SECONDS_PER_DAY + hour * 3_600 + minute * 60 + second;
    Ts(seconds * NANOSECONDS_PER_SECOND + millisecond * 1_000_000)
}

/// A price written in hundredths of a point: 500_025 is 5000.25.
const fn hundredths(price: i64) -> Price {
    Price(price * 10_000_000)
}

const fn trade(ts_recv: Ts, price: i64, size: i64) -> TradeRow {
    TradeRow {
        ts_recv,
        price: hundredths(price),
        size: Qty(size),
    }
}

const fn quoted(trade: TradeRow, (bid, ask, bid_size, ask_size): (i64, i64, i64, i64)) -> TbboRow {
    TbboRow {
        ts_recv: trade.ts_recv,
        price: trade.price,
        size: trade.size,
        bid: hundredths(bid),
        ask: hundredths(ask),
        bid_size: Qty(bid_size),
        ask_size: Qty(ask_size),
    }
}

/// A bar opening at `ts_open` and lasting `seconds`, its open, high, low, and close in hundredths.
const fn bar(ts_open: Ts, seconds: i64, [open, high, low, close]: [i64; 4], volume: i64) -> BarRow {
    BarRow {
        ts_open,
        ts_close: Ts(ts_open.0 + seconds * NANOSECONDS_PER_SECOND),
        open: hundredths(open),
        high: hundredths(high),
        low: hundredths(low),
        close: hundredths(close),
        volume: Qty(volume),
    }
}
