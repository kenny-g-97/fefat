//! The rules the writer applies to a trade date (D-56): a level is left out where its records
//! within a bar of a coarser level it nests in do not add up to the bar's volume, or where one of
//! them lies outside every such bar, and the bucket a dataset ends in is cut; any other record the
//! engine cannot read refuses the date.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, Ts};
use fefat_core::market_data::conformance::{
    FIRST_DAY, SAMPLE_CONTRACT, check_offsets, sample_tape,
};
use fefat_core::market_data::{BarRow, MarketDataReader, TapeDay, TbboRow, TradeRow};
use fefat_core::units::Qty;

use super::{TemporaryFolder, write_month};
use crate::{CacheError, MappedContract};

const SECOND: i64 = NANOSECONDS_PER_SECOND;

fn first_day() -> TapeDay {
    sample_tape().remove(0)
}

fn minute_bars(day: &TapeDay) -> &[BarRow] {
    &day.bars[&Timeframe::ONE_MINUTE]
}

#[test]
fn records_at_and_after_the_close_of_the_last_minute_bar_are_cut_and_counted() {
    // The sample's last 1-minute bar closes at 14:32:00: a dataset that ends in the bucket after
    // it holds that bucket's ticks and seconds but not its bar (D-43, D-45).
    let mut day = first_day();
    let close = minute_bars(&day).last().unwrap().ts_close;
    let at_the_close = TradeRow {
        ts_recv: close,
        ..day.trades[5]
    };
    let later = TradeRow {
        ts_recv: Ts(close.0 + SECOND / 2),
        ..at_the_close
    };
    day.trades.extend([at_the_close, later]);
    let quoted = |trade: TradeRow| TbboRow {
        ts_recv: trade.ts_recv,
        ..day.tbbo[5]
    };
    let late_quotes = [quoted(at_the_close), quoted(later)];
    day.tbbo.extend(late_quotes);
    let second = BarRow {
        ts_open: close,
        ts_close: Ts(close.0 + SECOND),
        volume: Qty(4),
        ..day.bars[&Timeframe::ONE_SECOND][4]
    };
    day.bars
        .get_mut(&Timeframe::ONE_SECOND)
        .unwrap()
        .push(second);
    let folder = TemporaryFolder::new();

    let index = write_month(folder.path(), SAMPLE_CONTRACT, vec![day]).unwrap();
    let reader = MappedContract::open(&folder.path().join(SAMPLE_CONTRACT)).unwrap();

    let cut = BTreeMap::from([("1s".into(), 1), ("tbbo".into(), 2), ("trades".into(), 2)]);
    assert_eq!(index.trade_dates[0].cut, cut);
    let sample: Vec<Ts> = first_day()
        .trades
        .iter()
        .map(|trade| trade.ts_recv)
        .collect();
    assert_eq!(reader.trades(FIRST_DAY).unwrap().ts_recv, sample.as_slice());
    assert_eq!(reader.levels(FIRST_DAY).unwrap().len(), 4);
    assert_eq!(check_offsets(&reader), Ok(()));
}

/// The first day with its 1-minute bars and trades alone, the trades kept by `keep`.
fn minutes_and_trades(keep: impl Fn(&TradeRow) -> bool) -> TapeDay {
    let mut day = first_day();
    day.tbbo.clear();
    day.bars.remove(&Timeframe::ONE_SECOND);
    day.trades.retain(keep);
    day
}

fn written(day: TapeDay) -> (BTreeMap<String, String>, Vec<Fidelity>) {
    let folder = TemporaryFolder::new();
    let index = write_month(folder.path(), SAMPLE_CONTRACT, vec![day]).unwrap();
    let reader = MappedContract::open(&folder.path().join(SAMPLE_CONTRACT)).unwrap();
    let left_out = index.trade_dates[0].left_out.clone();
    (left_out, reader.levels(FIRST_DAY).unwrap().to_vec())
}

/// The sample's first trade, received `seconds` after 14:30.
fn trade_after_14_30(seconds: i64) -> TradeRow {
    let first = first_day().trades[0];
    TradeRow {
        ts_recv: Ts(minute_bars(&first_day())[0].ts_open.0 + seconds * SECOND),
        ..first
    }
}

/// A 1-minute bar of one trade at the sample's first price, opening `seconds` after 14:30.
fn minute_after_14_30(seconds: i64) -> BarRow {
    let (first, open) = (first_day().trades[0], minute_bars(&first_day())[0].ts_open);
    BarRow {
        ts_open: Ts(open.0 + seconds * SECOND),
        ts_close: Ts(open.0 + (seconds + 60) * SECOND),
        open: first.price,
        high: first.price,
        low: first.price,
        close: first.price,
        volume: first.size,
    }
}

fn left_out_because(level: &str, reason: &str) -> BTreeMap<String, String> {
    BTreeMap::from([(level.into(), reason.into())])
}

#[test]
fn a_level_without_records_in_the_first_bar_of_a_coarser_level_is_left_out() {
    let second_minute = minute_bars(&first_day())[1].ts_open;
    let day = minutes_and_trades(|trade| trade.ts_recv >= second_minute);

    let (left_out, levels) = written(day);

    let reason = "its records in the 1m bar opening at 2026-03-05T14:30:00Z add up to 0 lots, \
                  not the bar's 10";
    assert_eq!(left_out, left_out_because("trades", reason));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn a_level_without_records_in_the_last_bar_of_a_coarser_level_is_left_out() {
    let second_minute = minute_bars(&first_day())[1].ts_open;
    let day = minutes_and_trades(|trade| trade.ts_recv < second_minute);

    let (left_out, levels) = written(day);

    let reason = "its records in the 1m bar opening at 2026-03-05T14:31:00Z add up to 0 lots, \
                  not the bar's 3";
    assert_eq!(left_out, left_out_because("trades", reason));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn a_level_without_records_in_a_bar_inside_the_day_is_left_out() {
    // Trades at 14:30:10 and 14:32:10 under 1-minute bars of 14:30, 14:31, and 14:32: the bar
    // of 14:31 would descend to no trade and fill nothing.
    let mut day = minutes_and_trades(|_| true);
    day.trades = vec![trade_after_14_30(10), trade_after_14_30(130)];
    let minutes = [0, 60, 120].map(minute_after_14_30);
    day.bars.insert(Timeframe::ONE_MINUTE, minutes.to_vec());

    let (left_out, levels) = written(day);

    let reason = "its records in the 1m bar opening at 2026-03-05T14:31:00Z add up to 0 lots, \
                  not the bar's 3";
    assert_eq!(left_out, left_out_because("trades", reason));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn only_the_level_that_a_bar_finds_none_of_is_left_out() {
    let mut day = first_day();
    day.tbbo.clear();
    let second_minute = minute_bars(&day)[1].ts_open;
    let seconds = day.bars.get_mut(&Timeframe::ONE_SECOND).unwrap();
    seconds.retain(|bar| bar.ts_open < second_minute);

    let (left_out, levels) = written(day);

    let reason = "its records in the 1m bar opening at 2026-03-05T14:31:00Z add up to 0 lots, \
                  not the bar's 3";
    assert_eq!(left_out, left_out_because("1s", reason));
    assert_eq!(
        levels,
        [Fidelity::Trades, Fidelity::Bars(Timeframe::ONE_MINUTE)]
    );
}

#[test]
fn a_level_missing_part_of_a_bar_is_left_out_and_the_levels_it_does_not_bound_kept() {
    // The trade of 14:30:01.2 is missing from the trades, while the TBBO records hold it.
    let mut day = first_day();
    day.trades.remove(2);

    let (left_out, levels) = written(day);

    let reason = "its records in the 1m bar opening at 2026-03-05T14:30:00Z add up to 8 lots, \
                  not the bar's 10";
    assert_eq!(left_out, left_out_because("trades", reason));
    let seconds_and_minutes = [Timeframe::ONE_SECOND, Timeframe::ONE_MINUTE].map(Fidelity::Bars);
    assert_eq!(
        levels,
        [[Fidelity::Tbbo].as_slice(), &seconds_and_minutes].concat()
    );
}

#[test]
fn a_level_with_a_record_between_two_bars_is_left_out_with_its_reason() {
    // Bars of 14:30 and 14:32 with a trade at 14:31:10 that neither holds.
    let mut day = minutes_and_trades(|_| true);
    day.trades = [10, 70, 130].map(trade_after_14_30).to_vec();
    let minutes = [0, 120].map(minute_after_14_30);
    day.bars.insert(Timeframe::ONE_MINUTE, minutes.to_vec());

    let (left_out, levels) = written(day);

    let reason = "its record 2 lies outside every 1m bar";
    assert_eq!(left_out, left_out_because("trades", reason));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn a_record_the_engine_cannot_read_refuses_its_trade_date() {
    let mut day = first_day();
    day.trades[1].size = Qty(0);
    let folder = TemporaryFolder::new();

    let refused = write_month(folder.path(), SAMPLE_CONTRACT, vec![day]).unwrap_err();

    assert!(matches!(refused, CacheError::Tape { trade_date, .. } if trade_date == FIRST_DAY));
    assert_eq!(
        refused.to_string(),
        "Expected records the engine can read on 2026-03-05, got: Expected a size of one lot or \
         more, got 0 lots in trades record 2 on 2026-03-05"
    );
}
