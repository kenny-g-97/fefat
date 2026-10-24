//! The in-memory reader against the conformance checks, the checks against a reader that serves
//! wrong offsets, and the tapes the in-memory reader refuses.

use std::collections::BTreeMap;

use super::conformance::{
    FIRST_DAY, SAMPLE_CONTRACT, SECOND_DAY, check_offsets, check_sample_tape, sample_tape,
};
use super::*;
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
        "Expected records in the order of their ts_recv, got trades record 2 on 2026-03-05"
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
        "Expected a bar whose low and high hold its open and close, got 5m record 1 on 2026-03-06"
    );
}

#[test]
fn overlapping_bars_are_refused() {
    let mut tape = sample_tape();
    let bars = tape[1].bars.get_mut(&Timeframe::FIVE_MINUTES).unwrap();
    bars[1].ts_open = Ts(bars[0].ts_close.0 - 1);
    let refused = sample_reader(tape).unwrap_err();
    assert!(matches!(
        refused,
        TapeError::InvalidRecord { record: 2, .. }
    ));
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
fn a_second_bar_that_outlasts_its_minute_is_refused() {
    let mut tape = sample_tape();
    let seconds = tape[0].bars.get_mut(&Timeframe::ONE_SECOND).unwrap();
    seconds[4].ts_close = Ts(seconds[4].ts_close.0 + 30 * NANOSECONDS_PER_SECOND);
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
