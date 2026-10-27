//! A tape held in memory: one contract's records by trade date and level, the form step 2.6's
//! `fefat-cli run` reads its tapes into, and the rules the in-memory reader holds them to.

use std::collections::BTreeMap;

use thiserror::Error;

use crate::fidelity::{Fidelity, Timeframe};
use crate::instants::{TradeDate, Ts};
use crate::units::{Price, Qty};

/// A trade print, received at `ts_recv` (F-CLK-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TradeRow {
    /// The instant it was received.
    pub ts_recv: Ts,
    /// Its price.
    pub price: Price,
    /// Its size in lots, one or more.
    pub size: Qty,
}

/// A TBBO record: a trade with the best bid and ask just before it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TbboRow {
    /// The instant it was received.
    pub ts_recv: Ts,
    /// The trade's price.
    pub price: Price,
    /// The trade's size in lots, one or more.
    pub size: Qty,
    /// The best bid, below the ask.
    pub bid: Price,
    /// The best ask.
    pub ask: Price,
    /// The lots bid.
    pub bid_size: Qty,
    /// The lots offered.
    pub ask_size: Qty,
}

/// A stored bar of the trades received in `[ts_open, ts_close)`, available at `ts_close`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BarRow {
    /// The instant it opens.
    pub ts_open: Ts,
    /// The instant it closes, after it opens.
    pub ts_close: Ts,
    /// Its first price.
    pub open: Price,
    /// Its highest price.
    pub high: Price,
    /// Its lowest price.
    pub low: Price,
    /// Its last price.
    pub close: Price,
    /// The lots it traded, one or more (F-BAR-07).
    pub volume: Qty,
}

/// One trade date's records at each level it has; a level left empty is one the date lacks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TapeDay {
    /// The trade date.
    pub trade_date: TradeDate,
    /// Its TBBO records, by `ts_recv`.
    pub tbbo: Vec<TbboRow>,
    /// Its trade prints, by `ts_recv`.
    pub trades: Vec<TradeRow>,
    /// Its stored bars of each timeframe, by `ts_open`.
    pub bars: BTreeMap<Timeframe, Vec<BarRow>>,
}

/// A tape the in-memory reader refuses.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TapeError {
    /// No trade date at all.
    #[error("Expected a tape of one trade date or more, got none")]
    Empty,
    /// Trade dates out of order, or one twice.
    #[error("Expected trade dates in ascending order, got {next} after {previous}")]
    DatesNotAscending {
        /// The earlier day of the tape.
        previous: TradeDate,
        /// The day that follows it.
        next: TradeDate,
    },
    /// A trade date with no records.
    #[error("Expected records on {trade_date}, got none at any level")]
    DayWithoutRecords {
        /// The empty day.
        trade_date: TradeDate,
    },
    /// A record that breaks a rule of its level.
    #[error("Expected {expected}, got {actual} in {level} record {record} on {trade_date}")]
    InvalidRecord {
        /// Its trade date.
        trade_date: TradeDate,
        /// Its level.
        level: Fidelity,
        /// Its place among the level's records, counting from 1.
        record: usize,
        /// The rule it breaks.
        expected: &'static str,
        /// What it holds instead.
        actual: String,
    },
    /// A finer record that no coarser bar of its day holds whole.
    #[error(
        "Expected every {finer} record of {trade_date} inside a {timeframe} bar, got record \
         {record} outside them"
    )]
    RecordOutsideBars {
        /// Its trade date.
        trade_date: TradeDate,
        /// The coarser bars.
        timeframe: Timeframe,
        /// Its level.
        finer: Fidelity,
        /// Its place among the level's records, counting from 1.
        record: usize,
    },
    /// A finer record that trades outside the range of the coarser bar holding it, whose high
    /// and low a descent trusts (`02` §4).
    #[error(
        "Expected every {finer} record of {trade_date} inside the range of the {timeframe} bar \
         that holds it, got record {record} outside it"
    )]
    RecordOutsideRange {
        /// Its trade date.
        trade_date: TradeDate,
        /// The coarser bars.
        timeframe: Timeframe,
        /// Its level.
        finer: Fidelity,
        /// Its place among the level's records, counting from 1.
        record: usize,
    },
    /// More records of one level than the offsets can count.
    #[error(
        "Expected at most {} {level} records on {trade_date}, got {records}",
        u32::MAX
    )]
    TooManyRecords {
        /// The trade date.
        trade_date: TradeDate,
        /// The level.
        level: Fidelity,
        /// How many there are.
        records: usize,
    },
}

/// Refuses ticks of no lots, or out of `ts_recv` order (F-CLK-03 keeps the vendor's order at one
/// instant).
pub(super) fn check_ticks(
    trade_date: TradeDate,
    level: Fidelity,
    ticks: impl Iterator<Item = (Ts, Qty)>,
) -> Result<(), TapeError> {
    let mut previous: Option<Ts> = None;
    for (index, (ts_recv, size)) in ticks.enumerate() {
        if size.0 <= 0 {
            let actual = format!("{size} lots");
            return Err(invalid(
                trade_date,
                level,
                index,
                "a size of one lot or more",
                actual,
            ));
        }
        if let Some(earlier) = previous.filter(|earlier| ts_recv < *earlier) {
            let actual = format!("ts_recv {ts_recv} after {earlier}");
            let expected = "records in the order of their ts_recv";
            return Err(invalid(trade_date, level, index, expected, actual));
        }
        previous = Some(ts_recv);
    }
    Ok(())
}

/// Refuses a TBBO record whose bid is not below its ask, or whose bid or ask holds no lots, as
/// `fefat.reference.tape.TbboRecord` does.
pub(super) fn check_quotes(trade_date: TradeDate, records: &[TbboRow]) -> Result<(), TapeError> {
    for (index, record) in records.iter().enumerate() {
        if record.bid >= record.ask {
            let actual = format!("bid {} and ask {}", record.bid, record.ask);
            let expected = "a bid below the ask";
            return Err(invalid(trade_date, Fidelity::Tbbo, index, expected, actual));
        }
        if record.bid_size.0 <= 0 || record.ask_size.0 <= 0 {
            let actual = format!(
                "bid size {} and ask size {}",
                record.bid_size, record.ask_size
            );
            let expected = "a bid and an ask of one lot or more";
            return Err(invalid(trade_date, Fidelity::Tbbo, index, expected, actual));
        }
    }
    Ok(())
}

/// Refuses a bar that does not open before it closes, that lasts longer than its timeframe (a
/// daily bar may), whose low and high miss its open or its close, that traded no lots, or that
/// overlaps the bar before it.
pub(super) fn check_bars(
    trade_date: TradeDate,
    timeframe: Timeframe,
    bars: &[BarRow],
) -> Result<(), TapeError> {
    let mut previous_close = None;
    for (index, bar) in bars.iter().enumerate() {
        if let Some((expected, actual)) = bar_problem(timeframe, bar, previous_close) {
            let level = Fidelity::Bars(timeframe);
            return Err(invalid(trade_date, level, index, expected, actual));
        }
        previous_close = Some(bar.ts_close);
    }
    Ok(())
}

fn bar_problem(
    timeframe: Timeframe,
    bar: &BarRow,
    previous_close: Option<Ts>,
) -> Option<(&'static str, String)> {
    let span = || format!("a bar from {} to {}", bar.ts_open, bar.ts_close);
    if bar.ts_open >= bar.ts_close {
        return Some(("a bar that opens before it closes", span()));
    }
    let length = bar.ts_close.0.checked_sub(bar.ts_open.0);
    if !length.is_some_and(|length| timeframe.fits(length)) {
        return Some(("a bar no longer than its timeframe", span()));
    }
    if bar.low > bar.open.min(bar.close) || bar.high < bar.open.max(bar.close) {
        let (open, high, low, close) = (bar.open, bar.high, bar.low, bar.close);
        let prices = format!("open {open}, high {high}, low {low}, close {close}");
        return Some(("a bar whose low and high hold its open and close", prices));
    }
    if bar.volume.0 <= 0 {
        return Some((
            "a bar of one lot or more (F-BAR-07)",
            format!("{} lots", bar.volume),
        ));
    }
    if let Some(close) = previous_close.filter(|close| bar.ts_open < *close) {
        let expected = "bars that do not overlap, each opening at or after the close before it";
        return Some((
            expected,
            format!("a bar opening {} before the close {close}", bar.ts_open),
        ));
    }
    None
}

fn invalid(
    trade_date: TradeDate,
    level: Fidelity,
    index: usize,
    expected: &'static str,
    actual: String,
) -> TapeError {
    TapeError::InvalidRecord {
        trade_date,
        level,
        record: index + 1,
        expected,
        actual,
    }
}
