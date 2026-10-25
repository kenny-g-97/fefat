//! The rules the writer applies to a trade date (D-56): the bucket a dataset ends in is cut, a
//! level that covers part of the date is left out, and so is a level with a record outside every
//! bar; any other record the engine cannot read refuses the date.

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
    day.tbbo.push(TbboRow {
        ts_recv: close,
        ..day.tbbo[5]
    });
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

    let cut = BTreeMap::from([("1s".into(), 1), ("tbbo".into(), 1), ("trades".into(), 2)]);
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

#[test]
fn a_level_whose_first_record_follows_the_first_bar_is_left_out_with_its_reason() {
    let second_minute = minute_bars(&first_day())[1].ts_open;
    let day = minutes_and_trades(|trade| trade.ts_recv >= second_minute);

    let (left_out, levels) = written(day);

    let reason = "its first record, at 2026-03-05T14:31:00.5Z, lies outside the first 1m bar";
    assert_eq!(left_out, BTreeMap::from([("trades".into(), reason.into())]));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn a_level_whose_last_record_precedes_the_last_bar_is_left_out_with_its_reason() {
    let second_minute = minute_bars(&first_day())[1].ts_open;
    let day = minutes_and_trades(|trade| trade.ts_recv < second_minute);

    let (left_out, levels) = written(day);

    let reason = "its last record, at 2026-03-05T14:30:02Z, comes before the last 1m bar opens";
    assert_eq!(left_out, BTreeMap::from([("trades".into(), reason.into())]));
    assert_eq!(levels, [Fidelity::Bars(Timeframe::ONE_MINUTE)]);
}

#[test]
fn a_level_with_a_record_between_two_bars_is_left_out_with_its_reason() {
    // Bars of 14:30 and 14:32 with a trade at 14:31:10 that neither holds.
    let mut day = minutes_and_trades(|_| true);
    let first = day.trades[0];
    let at = |seconds: i64| TradeRow {
        ts_recv: Ts(minute_bars(&first_day())[0].ts_open.0 + seconds * SECOND),
        ..first
    };
    day.trades = vec![at(10), at(70), at(130)];
    let bar = |seconds: i64| BarRow {
        ts_open: Ts(minute_bars(&first_day())[0].ts_open.0 + seconds * SECOND),
        ts_close: Ts(minute_bars(&first_day())[0].ts_open.0 + (seconds + 60) * SECOND),
        open: first.price,
        high: first.price,
        low: first.price,
        close: first.price,
        volume: first.size,
    };
    day.bars
        .insert(Timeframe::ONE_MINUTE, vec![bar(0), bar(120)]);

    let (left_out, levels) = written(day);

    let reason = "its record 2 lies outside every 1m bar";
    assert_eq!(left_out, BTreeMap::from([("trades".into(), reason.into())]));
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
