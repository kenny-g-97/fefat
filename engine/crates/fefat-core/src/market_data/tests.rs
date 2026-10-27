//! The in-memory reader against the conformance checks, the checks against a reader that serves
//! wrong offsets, and the tapes the in-memory reader refuses.

use std::collections::BTreeMap;

use super::conformance::{
    FIRST_DAY, SAMPLE_CONTRACT, SECOND_DAY, check_offsets, check_sample_tape, sample_tape,
};
use super::*;
use crate::fidelity::TimeUnit;
use crate::instants::NANOSECONDS_PER_SECOND;

fn sample_reader(days: Vec<TapeDay>) -> Result<InMemoryMarketData, TapeError> {
    InMemoryMarketData::new(Contract(SAMPLE_CONTRACT.to_owned()), days)
}

#[test]
fn the_in_memory_reader_serves_the_sample_tape() {
    let reader = sample_reader(sample_tape()).unwrap();
    assert_eq!(check_sample_tape(&reader), Ok(()));
    assert_eq!(check_offsets(&reader), Ok(()));
}

#[test]
fn the_checks_refuse_a_reader_whose_offsets_are_a_bar_late() {
    let late = OneBarLate::of(sample_reader(sample_tape()).unwrap());
    let refused = check_sample_tape(&late).unwrap_err();
    assert_eq!(refused.what, "the offsets from 1m bars to 1s on 2026-03-05");
    assert_eq!(
        (refused.expected.as_str(), refused.actual.as_str()),
        ("[0, 3, 5]", "[3, 5, 5]")
    );
    assert!(check_offsets(&late).is_err());
}

#[test]
fn the_checks_refuse_a_reader_of_another_tape() {
    let mut tape = sample_tape();
    tape[0].trades[1].size = Qty(2);
    let refused = check_sample_tape(&sample_reader(tape).unwrap()).unwrap_err();
    assert_eq!(refused.what, "the trades of 2026-03-05 size");
}

#[test]
fn the_reader_names_what_a_tape_lacks() {
    let reader = sample_reader(sample_tape()).unwrap();
    assert_eq!(
        reader.levels(TradeDate(20_519)).unwrap_err().to_string(),
        "Expected a trade date of ESH2026 from 2026-03-05 to 2026-03-06, got 2026-03-07"
    );
    assert_eq!(
        reader.trades(SECOND_DAY).unwrap_err().to_string(),
        "Expected trades data of ESH2026 on 2026-03-06, which holds 5m"
    );
}

#[test]
fn a_tape_without_trade_dates_is_refused() {
    assert_eq!(sample_reader(Vec::new()).unwrap_err(), TapeError::Empty);
}

#[test]
fn trade_dates_out_of_order_are_refused() {
    let mut tape = sample_tape();
    tape.reverse();
    assert_eq!(
        sample_reader(tape).unwrap_err(),
        TapeError::DatesNotAscending {
            previous: SECOND_DAY,
            next: FIRST_DAY
        }
    );
}

#[test]
fn a_day_without_records_is_refused() {
    let mut tape = sample_tape();
    tape[1].bars.clear();
    assert_eq!(
        sample_reader(tape).unwrap_err(),
        TapeError::DayWithoutRecords {
            trade_date: SECOND_DAY
        }
    );
}

#[test]
fn trades_out_of_time_order_are_refused() {
    let mut tape = sample_tape();
    tape[0].trades.swap(0, 1);
    assert_eq!(
        sample_reader(tape).unwrap_err().to_string(),
        "Expected records in the order of their ts_recv, got ts_recv 2026-03-05T14:30:00.1Z after \
         2026-03-05T14:30:00.6Z in trades record 2 on 2026-03-05"
    );
}

#[test]
fn a_record_of_no_lots_and_a_crossed_quote_are_refused() {
    let mut no_lots = sample_tape();
    no_lots[0].trades[0].size = Qty(0);
    let refused = sample_reader(no_lots).unwrap_err();
    assert!(matches!(
        refused,
        TapeError::InvalidRecord {
            expected: "a size of one lot or more",
            ..
        }
    ));
    let mut crossed = sample_tape();
    crossed[0].tbbo[2].bid = crossed[0].tbbo[2].ask;
    let refused = sample_reader(crossed).unwrap_err();
    assert!(matches!(
        refused,
        TapeError::InvalidRecord {
            record: 3,
            expected: "a bid below the ask",
            ..
        }
    ));
}

#[test]
fn a_bar_whose_low_and_high_miss_its_close_is_refused() {
    let mut tape = sample_tape();
    let bars = tape[1].bars.get_mut(&Timeframe::FIVE_MINUTES).unwrap();
    bars[0].close = Price(bars[0].high.0 + 1);
    let refused = sample_reader(tape).unwrap_err();
    assert_eq!(
        refused.to_string(),
        "Expected a bar whose low and high hold its open and close, got open 5010, high 5012.5, \
         low 5008.25, close 5012.500000001 in 5m record 1 on 2026-03-06"
    );
}

#[test]
fn overlapping_bars_are_refused() {
    let mut tape = sample_tape();
    let bars = tape[1].bars.get_mut(&Timeframe::FIVE_MINUTES).unwrap();
    bars[1].ts_open = Ts(bars[0].ts_close.0 - 1);
    bars[1].ts_close = Ts(bars[1].ts_close.0 - 1);
    let refused = sample_reader(tape).unwrap_err();
    let expected = "bars that do not overlap, each opening at or after the close before it";
    assert!(
        matches!(refused, TapeError::InvalidRecord { record: 2, expected: rule, .. } if rule == expected)
    );
}

#[test]
fn a_trade_after_every_bar_is_refused() {
    let mut tape = sample_tape();
    tape[0].trades[5].ts_recv = Ts(tape[0].trades[5].ts_recv.0 + 60 * NANOSECONDS_PER_SECOND);
    assert_eq!(
        sample_reader(tape).unwrap_err(),
        TapeError::RecordOutsideBars {
            trade_date: FIRST_DAY,
            timeframe: Timeframe::ONE_SECOND,
            finer: Fidelity::Trades,
            record: 6,
        }
    );
}

#[test]
fn a_second_bar_across_its_minute_close_is_refused() {
    let mut tape = sample_tape();
    let minute_close = tape[0].bars[&Timeframe::ONE_MINUTE][1].ts_close;
    let half_a_second = NANOSECONDS_PER_SECOND / 2;
    let seconds = tape[0].bars.get_mut(&Timeframe::ONE_SECOND).unwrap();
    seconds[4].ts_open = Ts(minute_close.0 - half_a_second);
    seconds[4].ts_close = Ts(minute_close.0 + half_a_second);
    tape[0].trades[5].ts_recv = Ts(minute_close.0 - half_a_second / 2);
    tape[0].tbbo[5].ts_recv = tape[0].trades[5].ts_recv;
    assert_eq!(
        sample_reader(tape).unwrap_err(),
        TapeError::RecordOutsideBars {
            trade_date: FIRST_DAY,
            timeframe: Timeframe::ONE_MINUTE,
            finer: Fidelity::Bars(Timeframe::ONE_SECOND),
            record: 5,
        }
    );
}

#[test]
fn a_record_traded_outside_the_range_of_the_bar_holding_it_is_refused() {
    // A descent trusts a bar's high and low to bound the trading it holds (`02` §4).
    let tick = Price(250_000_000);
    let mut above_its_second = sample_tape();
    above_its_second[0].trades[4].price = Price(above_its_second[0].trades[4].price.0 + tick.0);
    assert_eq!(
        sample_reader(above_its_second).unwrap_err(),
        TapeError::RecordOutsideRange {
            trade_date: FIRST_DAY,
            timeframe: Timeframe::ONE_SECOND,
            finer: Fidelity::Trades,
            record: 5,
        }
    );
    let mut above_its_minute = sample_tape();
    let seconds = above_its_minute[0]
        .bars
        .get_mut(&Timeframe::ONE_SECOND)
        .unwrap();
    seconds[3].high = Price(seconds[3].high.0 + tick.0);
    assert_eq!(
        sample_reader(above_its_minute).unwrap_err().to_string(),
        "Expected every 1s record of 2026-03-05 inside the range of the 1m bar that holds it, got \
         record 4 outside it"
    );
}

#[test]
fn a_quote_of_no_lots_is_refused() {
    let mut tape = sample_tape();
    tape[0].tbbo[0].ask_size = Qty(0);
    assert!(sample_reader(tape).is_err());
}

#[test]
fn a_bar_longer_than_its_timeframe_is_refused() {
    let mut tape = sample_tape();
    let bars = tape[1].bars.get_mut(&Timeframe::FIVE_MINUTES).unwrap();
    bars[1].ts_close = Ts(bars[1].ts_close.0 + 600 * NANOSECONDS_PER_SECOND);
    assert!(sample_reader(tape).is_err());
}

#[test]
fn bars_of_timeframes_that_do_not_nest_are_served_side_by_side() {
    let mut tape = sample_tape();
    let two_minutes = Timeframe::new(2, TimeUnit::Minute).unwrap();
    let first_open = tape[1].bars[&Timeframe::FIVE_MINUTES][0].ts_open;
    let two_minute_bars = (0..5)
        .map(|bar| {
            let ts_open = Ts(first_open.0 + bar * 120 * NANOSECONDS_PER_SECOND);
            let price = Price(5_010 * crate::units::PRICE_UNITS);
            let (open, high, low, close) = (price, price, price, price);
            let ts_close = Ts(ts_open.0 + 120 * NANOSECONDS_PER_SECOND);
            BarRow {
                ts_open,
                ts_close,
                open,
                high,
                low,
                close,
                volume: Qty(10),
            }
        })
        .collect();
    tape[1].bars.insert(two_minutes, two_minute_bars);
    let reader = sample_reader(tape).unwrap();
    let descent = reader.offsets(
        SECOND_DAY,
        Timeframe::FIVE_MINUTES,
        Fidelity::Bars(two_minutes),
    );
    assert_eq!(descent.unwrap(), [0, 3, 5]);
    assert_eq!(check_offsets(&reader), Ok(()));
}

#[test]
fn the_offsets_check_refuses_a_trade_received_after_its_bar_closed() {
    let reader = sample_reader(sample_tape()).unwrap();
    let trades = reader.trades(FIRST_DAY).unwrap();
    let mut ts_recv = trades.ts_recv.to_vec();
    let (mut price, mut size) = (trades.price.to_vec(), trades.size.to_vec());
    ts_recv.push(Ts(ts_recv[0].0 + 15 * 60 * NANOSECONDS_PER_SECOND));
    price.push(price[0]);
    size.push(Qty(1));
    let outside = TradeAfterTheBars {
        reader,
        ts_recv,
        price,
        size,
    };
    let refused = check_offsets(&outside).unwrap_err();
    assert_eq!(
        refused.what,
        "the trades records of 2026-03-05 in the 1s bars"
    );
}

#[test]
fn a_print_in_the_break_after_the_close_is_served_beside_the_daily_bar() {
    let second = NANOSECONDS_PER_SECOND;
    let close = Ts((i64::from(SECOND_DAY.0) * 86_400 + 22 * 3_600) * second);
    let open = Ts(close.0 - 23 * 3_600 * second);
    let price = Price(5_000 * crate::units::PRICE_UNITS);
    let bar = |ts_open, ts_close| BarRow {
        ts_open,
        ts_close,
        open: price,
        high: price,
        low: price,
        close: price,
        volume: Qty(1),
    };
    let trade = |ts_recv| TradeRow {
        ts_recv,
        price,
        size: Qty(1),
    };
    let after_the_close = Ts(close.0 + 400_000_000);
    let minute_bars = vec![
        bar(Ts(close.0 - 60 * second), close),
        bar(close, Ts(close.0 + 60 * second)),
    ];
    let day = TapeDay {
        trade_date: SECOND_DAY,
        tbbo: Vec::new(),
        trades: vec![trade(Ts(close.0 - 30 * second)), trade(after_the_close)],
        bars: BTreeMap::from([
            (Timeframe::ONE_MINUTE, minute_bars),
            (
                Timeframe::new(1, TimeUnit::Day).unwrap(),
                vec![bar(open, close)],
            ),
        ]),
    };
    assert_eq!(check_offsets(&sample_reader(vec![day]).unwrap()), Ok(()));
}

/// The in-memory reader of the sample tape with a seventh trade, received at 14:45:00.1 after
/// every bar has closed, served with the offsets a cache that kept it would give: inside the
/// last bar's range.
struct TradeAfterTheBars {
    reader: InMemoryMarketData,
    ts_recv: Vec<Ts>,
    price: Vec<Price>,
    size: Vec<Qty>,
}

impl MarketDataReader for TradeAfterTheBars {
    fn contract(&self) -> &Contract {
        self.reader.contract()
    }

    fn trade_dates(&self) -> &[TradeDate] {
        self.reader.trade_dates()
    }

    fn levels(&self, trade_date: TradeDate) -> Result<&[Fidelity], MarketDataError> {
        self.reader.levels(trade_date)
    }

    fn bars(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
    ) -> Result<BarColumns<'_>, MarketDataError> {
        self.reader.bars(trade_date, timeframe)
    }

    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError> {
        if trade_date != FIRST_DAY {
            return self.reader.trades(trade_date);
        }
        Ok(TradeColumns {
            ts_recv: &self.ts_recv,
            price: &self.price,
            size: &self.size,
        })
    }

    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError> {
        self.reader.tbbo(trade_date)
    }

    fn offsets(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
        finer: Fidelity,
    ) -> Result<&[u32], MarketDataError> {
        match (trade_date == FIRST_DAY, timeframe, finer) {
            (true, Timeframe::ONE_MINUTE, Fidelity::Trades) => Ok(&[0, 4, 7]),
            (true, Timeframe::ONE_SECOND, Fidelity::Trades) => Ok(&[0, 2, 3, 4, 5, 7]),
            _ => self.reader.offsets(trade_date, timeframe, finer),
        }
    }
}

/// The in-memory reader with every offsets table served one bar late, each bar descending to
/// the records of the bar after it, as a cache whose index skipped a bar would serve them.
struct OneBarLate {
    reader: InMemoryMarketData,
    late: BTreeMap<(TradeDate, Timeframe, Fidelity), Vec<u32>>,
}

impl OneBarLate {
    fn of(reader: InMemoryMarketData) -> Self {
        let mut late = BTreeMap::new();
        for &trade_date in reader.trade_dates() {
            let levels = reader.levels(trade_date).unwrap();
            for &coarser in levels {
                let Fidelity::Bars(timeframe) = coarser else {
                    continue;
                };
                for &finer in levels.iter().filter(|level| **level < coarser) {
                    let offsets = reader.offsets(trade_date, timeframe, finer).unwrap();
                    let mut shifted = offsets[1..].to_vec();
                    shifted.push(offsets[offsets.len() - 1]);
                    late.insert((trade_date, timeframe, finer), shifted);
                }
            }
        }
        Self { reader, late }
    }
}

impl MarketDataReader for OneBarLate {
    fn contract(&self) -> &Contract {
        self.reader.contract()
    }

    fn trade_dates(&self) -> &[TradeDate] {
        self.reader.trade_dates()
    }

    fn levels(&self, trade_date: TradeDate) -> Result<&[Fidelity], MarketDataError> {
        self.reader.levels(trade_date)
    }

    fn bars(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
    ) -> Result<BarColumns<'_>, MarketDataError> {
        self.reader.bars(trade_date, timeframe)
    }

    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError> {
        self.reader.trades(trade_date)
    }

    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError> {
        self.reader.tbbo(trade_date)
    }

    fn offsets(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
        finer: Fidelity,
    ) -> Result<&[u32], MarketDataError> {
        match self.late.get(&(trade_date, timeframe, finer)) {
            Some(late) => Ok(late),
            None => self.reader.offsets(trade_date, timeframe, finer),
        }
    }
}
