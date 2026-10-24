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
    #[error("Expected {expected}, got {level} record {record} on {trade_date}")]
    InvalidRecord {
        /// Its trade date.
        trade_date: TradeDate,
        /// Its level.
        level: Fidelity,
        /// Its place among the level's records, counting from 1.
        record: usize,
        /// The rule it breaks.
        expected: &'static str,
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
    let mut previous = None;
    for (index, (ts_recv, size)) in ticks.enumerate() {
        if size.0 <= 0 {
            return Err(invalid(
                trade_date,
                level,
                index,
                "a size of one lot or more",
            ));
        }
        if previous.is_some_and(|earlier| ts_recv < earlier) {
            return Err(invalid(
                trade_date,
                level,
                index,
                "records in the order of their ts_recv",
            ));
        }
        previous = Some(ts_recv);
    }
    Ok(())
}

/// Refuses a TBBO record whose bid is not below its ask.
pub(super) fn check_quotes(trade_date: TradeDate, records: &[TbboRow]) -> Result<(), TapeError> {
    match records.iter().position(|record| record.bid >= record.ask) {
        Some(index) => Err(invalid(
            trade_date,
            Fidelity::Tbbo,
            index,
            "a bid below the ask",
        )),
        None => Ok(()),
    }
}

/// Refuses a bar that does not open before it closes, whose low and high miss its open or its
/// close, that traded no lots, or that overlaps the bar before it.
pub(super) fn check_bars(
    trade_date: TradeDate,
    timeframe: Timeframe,
    bars: &[BarRow],
) -> Result<(), TapeError> {
    let mut previous_close = None;
    for (index, bar) in bars.iter().enumerate() {
        if let Some(expected) = bar_problem(bar, previous_close) {
            return Err(invalid(
                trade_date,
                Fidelity::Bars(timeframe),
                index,
                expected,
            ));
        }
        previous_close = Some(bar.ts_close);
    }
    Ok(())
}

fn bar_problem(bar: &BarRow, previous_close: Option<Ts>) -> Option<&'static str> {
    if bar.ts_open >= bar.ts_close {
        return Some("a bar that opens before it closes");
    }
    if bar.low > bar.open.min(bar.close) || bar.high < bar.open.max(bar.close) {
        return Some("a bar whose low and high hold its open and close");
    }
    if bar.volume.0 <= 0 {
        return Some("a bar of one lot or more (F-BAR-07)");
    }
    if previous_close.is_some_and(|close| bar.ts_open < close) {
        return Some("bars that do not overlap, each opening at or after the close before it");
    }
    None
}

const fn invalid(
    trade_date: TradeDate,
    level: Fidelity,
    index: usize,
    expected: &'static str,
) -> TapeError {
    TapeError::InvalidRecord {
        trade_date,
        level,
        record: index + 1,
        expected,
    }
}
