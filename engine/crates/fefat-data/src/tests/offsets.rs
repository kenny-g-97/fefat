//! Step 2.5's Done means 1, the engine's half: through the mapped cache, the offsets of any
//! session take each 1-minute bar to the 1-second bars and trades of its time, and each 1-second
//! bar to its trades, as a count bar by bar finds them.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, SECONDS_PER_DAY, Ts};
use fefat_core::market_data::conformance::{FIRST_DAY, check_offsets};
use fefat_core::market_data::{BarRow, MarketDataReader, TapeDay, TradeRow};
use fefat_core::units::{PRICE_UNITS, Price, Qty};
use proptest::prelude::*;

use super::{TemporaryFolder, cached};

/// 14:30 UTC of the sample's first day, the session's first bucket.
const OPEN: Ts =
    Ts((FIRST_DAY.0 as i64 * SECONDS_PER_DAY + 14 * 3_600 + 30 * 60) * NANOSECONDS_PER_SECOND);
/// A quarter point, ES's tick, in 1e-9 units.
const TICK: i64 = PRICE_UNITS / 4;
const HALF_AN_HOUR: i64 = 1_800;

/// Trades in the session's first half hour, in `ts_recv` order, some received as a second
/// opens, so that a trade on a bar's boundary belongs to the bar it opens.
fn session() -> impl Strategy<Value = Vec<TradeRow>> {
    let after_the_open = prop_oneof![
        (0..HALF_AN_HOUR).prop_map(|second| second * NANOSECONDS_PER_SECOND),
        0..HALF_AN_HOUR * NANOSECONDS_PER_SECOND,
    ];
    let trade = (after_the_open, -40..40_i64, 1..5_i64);
    prop::collection::vec(trade, 1..300).prop_map(|trades| {
        let mut trades: Vec<TradeRow> = trades
            .into_iter()
            .map(|(after_the_open, ticks, size)| TradeRow {
                ts_recv: Ts(OPEN.0 + after_the_open),
                price: Price(5_000 * PRICE_UNITS + ticks * TICK),
                size: Qty(size),
            })
            .collect();
        trades.sort_by_key(|trade| trade.ts_recv);
        trades
    })
}

/// The bars of `seconds`, bucketed from the open as `[open + k·Δ, open + (k+1)·Δ)` (`02` §1.4).
fn bars_of(trades: &[TradeRow], seconds: i64) -> Vec<BarRow> {
    let length = seconds * NANOSECONDS_PER_SECOND;
    let mut bars: BTreeMap<i64, BarRow> = BTreeMap::new();
    for trade in trades {
        let bucket = (trade.ts_recv.0 - OPEN.0) / length;
        bars.entry(bucket)
            .and_modify(|bar| {
                bar.high = bar.high.max(trade.price);
                bar.low = bar.low.min(trade.price);
                bar.close = trade.price;
                bar.volume = Qty(bar.volume.0 + trade.size.0);
            })
            .or_insert(BarRow {
                ts_open: Ts(OPEN.0 + bucket * length),
                ts_close: Ts(OPEN.0 + (bucket + 1) * length),
                open: trade.price,
                high: trade.price,
                low: trade.price,
                close: trade.price,
                volume: trade.size,
            });
    }
    bars.into_values().collect()
}

/// For each bar, the finer records of the bars before it, then all of them: counted bar by bar
/// rather than searched.
fn counted(bars: &[BarRow], finer: &[Ts]) -> Vec<u32> {
    let mut offsets = vec![0];
    for bar in bars {
        let held = finer
            .iter()
            .filter(|start| bar.ts_open <= **start && **start < bar.ts_close)
            .count();
        offsets.push(offsets.last().unwrap() + held as u32);
    }
    offsets
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 64, ..ProptestConfig::default() })]

    #[test]
    fn offsets_take_every_bar_to_its_seconds_and_trades(trades in session()) {
        let seconds = bars_of(&trades, 1);
        let minutes = bars_of(&trades, 60);
        let day = TapeDay {
            trade_date: FIRST_DAY,
            tbbo: Vec::new(),
            trades: trades.clone(),
            bars: BTreeMap::from([
                (Timeframe::ONE_SECOND, seconds.clone()),
                (Timeframe::ONE_MINUTE, minutes.clone()),
            ]),
        };
        let folder = TemporaryFolder::new();

        let reader = cached(folder.path(), "ESH2026", vec![day]).unwrap();

        prop_assert_eq!(check_offsets(&reader), Ok(()));
        let trade_starts: Vec<Ts> = trades.iter().map(|trade| trade.ts_recv).collect();
        let second_starts: Vec<Ts> = seconds.iter().map(|bar| bar.ts_open).collect();
        let second_bars = Fidelity::Bars(Timeframe::ONE_SECOND);
        let expected = [
            (Timeframe::ONE_MINUTE, second_bars, counted(&minutes, &second_starts)),
            (Timeframe::ONE_MINUTE, Fidelity::Trades, counted(&minutes, &trade_starts)),
            (Timeframe::ONE_SECOND, Fidelity::Trades, counted(&seconds, &trade_starts)),
        ];
        for (timeframe, finer, offsets) in expected {
            let served = reader.offsets(FIRST_DAY, timeframe, finer).unwrap();
            prop_assert_eq!(served, offsets.as_slice());
        }
        prop_assert_eq!(reader.trades(FIRST_DAY).unwrap().ts_recv, trade_starts.as_slice());
        prop_assert_eq!(reader.bars(FIRST_DAY, Timeframe::ONE_MINUTE).unwrap().ts_open.len(), minutes.len());
    }
}
