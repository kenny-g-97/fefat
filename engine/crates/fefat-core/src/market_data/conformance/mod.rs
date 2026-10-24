//! The checks every [`MarketDataReader`] passes (step 2.4's Done means 4): a reader of the
//! hand-written [`sample_tape`] serves it back exactly, with the levels and offsets written out
//! below, and any reader's offsets take each bar to the finer records of its time. Step 2.5's
//! cache, built from the same tape, runs both checks unchanged.

mod sample;

use std::fmt;

use thiserror::Error;

pub use sample::{FIRST_DAY, SAMPLE_CONTRACT, SECOND_DAY, sample_tape};

use super::{
    BarColumns, BarRow, MarketDataError, MarketDataReader, TapeDay, TbboColumns, TbboRow,
    TradeColumns, TradeRow,
};
use crate::fidelity::{Fidelity, Timeframe};
use crate::instants::{TradeDate, Ts};

/// The offsets of the first day, written out by hand: the 1-minute bar of 14:30 holds the first
/// three 1-second bars and the first four trades, and the fourth trade, received as its second
/// opens, belongs to that second.
const FIRST_DAY_OFFSETS: [(Timeframe, Fidelity, &[u32]); 5] = [
    (
        Timeframe::ONE_MINUTE,
        Fidelity::Bars(Timeframe::ONE_SECOND),
        &[0, 3, 5],
    ),
    (Timeframe::ONE_MINUTE, Fidelity::Trades, &[0, 4, 6]),
    (Timeframe::ONE_MINUTE, Fidelity::Tbbo, &[0, 4, 6]),
    (Timeframe::ONE_SECOND, Fidelity::Trades, &[0, 2, 3, 4, 5, 6]),
    (Timeframe::ONE_SECOND, Fidelity::Tbbo, &[0, 2, 3, 4, 5, 6]),
];

/// What a reader served that a check did not expect.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("Expected {expected} for {what}, got {actual}")]
pub struct Mismatch {
    /// What was checked.
    pub what: String,
    /// What the check expected, as Rust's debug format writes it.
    pub expected: String,
    /// What the reader served.
    pub actual: String,
}

/// Checks that `reader` serves the sample tape exactly: its contract and trade dates, each day's
/// levels, every record of every level, the first day's offsets as written out above, and the
/// refusals of a date, a level, and a descent the tape lacks.
pub fn check_sample_tape(reader: &impl MarketDataReader) -> Result<(), Mismatch> {
    expect(
        "the contract",
        SAMPLE_CONTRACT,
        reader.contract().0.as_str(),
    )?;
    expect(
        "the trade dates",
        [FIRST_DAY, SECOND_DAY].as_slice(),
        reader.trade_dates(),
    )?;
    let first_levels = [
        Fidelity::Tbbo,
        Fidelity::Trades,
        Fidelity::Bars(Timeframe::ONE_SECOND),
        Fidelity::Bars(Timeframe::ONE_MINUTE),
    ];
    let what = "the levels of 2026-03-05";
    expect(
        what,
        first_levels.as_slice(),
        served(reader.levels(FIRST_DAY), what)?,
    )?;
    let what = "the levels of 2026-03-06";
    let second_levels = [Fidelity::Bars(Timeframe::FIVE_MINUTES)];
    expect(
        what,
        second_levels.as_slice(),
        served(reader.levels(SECOND_DAY), what)?,
    )?;
    for day in sample_tape() {
        check_records(reader, &day)?;
    }
    for (timeframe, finer, offsets) in FIRST_DAY_OFFSETS {
        let what = format!("the offsets from {timeframe} bars to {finer} on {FIRST_DAY}");
        expect(
            &what,
            offsets,
            served(reader.offsets(FIRST_DAY, timeframe, finer), &what)?,
        )?;
    }
    check_refusals(reader)
}

/// Checks that every offsets table `reader` serves takes each bar to the finer records of its
/// time: on each trade date, from each timeframe's bars to each finer level, the bars are in time
/// order without overlaps, the finer records are in time order, entry `i` counts those before bar
/// `i` opens and the last counts them all, and, where the levels nest, every record of bar `i`'s
/// range lies inside bar `i`.
pub fn check_offsets(reader: &impl MarketDataReader) -> Result<(), Mismatch> {
    for &trade_date in reader.trade_dates() {
        let levels = served(reader.levels(trade_date), "the levels of a trade date")?;
        for &coarser in levels {
            let Fidelity::Bars(timeframe) = coarser else {
                continue;
            };
            for &finer in levels.iter().filter(|level| **level < coarser) {
                check_descent(reader, trade_date, timeframe, finer)?;
            }
        }
    }
    Ok(())
}

fn check_descent(
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    timeframe: Timeframe,
    finer: Fidelity,
) -> Result<(), Mismatch> {
    let what = format!("the offsets from {timeframe} bars to {finer} on {trade_date}");
    let bars = served(reader.bars(trade_date, timeframe), &what)?;
    check_bar_order(&bars, &format!("the {timeframe} bars of {trade_date}"))?;
    let records = record_spans(reader, trade_date, finer, &what)?;
    if !records.iter().map(|(first, _)| first).is_sorted() {
        let what = format!("the {finer} records of {trade_date}");
        return Err(mismatch(
            &what,
            "records in time order",
            "records out of order",
        ));
    }
    let mut starts: Vec<usize> = bars
        .ts_open
        .iter()
        .map(|open| records.partition_point(|(first, _)| first < open))
        .collect();
    starts.push(records.len());
    let expected: Vec<u64> = starts.iter().map(|start| *start as u64).collect();
    let offsets = served(reader.offsets(trade_date, timeframe, finer), &what)?;
    let offsets: Vec<u64> = offsets.iter().map(|offset| u64::from(*offset)).collect();
    expect(&what, expected.as_slice(), offsets.as_slice())?;
    if !finer.nests_in(timeframe) {
        return Ok(());
    }
    let what = format!("the {finer} records of {trade_date} in the {timeframe} bars");
    check_held(&what, &records, &starts, bars.ts_close)
}

/// Refuses bars out of time order: each opens before it closes and at or after the close before.
fn check_bar_order(bars: &BarColumns<'_>, what: &str) -> Result<(), Mismatch> {
    let each_opens_first = bars
        .ts_open
        .iter()
        .zip(bars.ts_close)
        .all(|(open, close)| open < close);
    let mut closes_and_next_opens = bars.ts_close.iter().zip(bars.ts_open.iter().skip(1));
    if each_opens_first && closes_and_next_opens.all(|(close, next)| close <= next) {
        return Ok(());
    }
    let expected =
        "bars in time order, each opening before it closes and at or after the last close";
    Err(mismatch(what, expected, "bars out of order or overlapping"))
}

/// Refuses a record outside the bar whose range holds it: before the first bar opens, or lasting
/// to or past its bar's close.
fn check_held(
    what: &str,
    records: &[(Ts, Ts)],
    starts: &[usize],
    closes: &[Ts],
) -> Result<(), Mismatch> {
    let expected = "each record inside the bar whose range holds it";
    if let (Some(&before_the_first_bar), Some((first, _))) = (starts.first(), records.first())
        && before_the_first_bar > 0
    {
        let actual = format!("record 1 at {first}, before the first bar");
        return Err(mismatch(what, expected, actual));
    }
    let ranges = starts.iter().zip(starts.iter().skip(1)).zip(closes);
    for ((start, end), close) in ranges {
        let mut held = records.iter().enumerate().skip(*start).take(end - start);
        if let Some((index, (first, _))) = held.find(|(_, (_, last))| last >= close) {
            let actual = format!(
                "record {} at {first}, in the bar closing {close}",
                index + 1
            );
            return Err(mismatch(what, expected, actual));
        }
    }
    Ok(())
}

/// Each record of `level` as the first and the last instant it covers: a tick its `ts_recv`, a
/// bar every instant from its open to just before its close.
fn record_spans(
    reader: &impl MarketDataReader,
    trade_date: TradeDate,
    level: Fidelity,
    what: &str,
) -> Result<Vec<(Ts, Ts)>, Mismatch> {
    let ticks = |ts_recv: &[Ts]| ts_recv.iter().map(|ts| (*ts, *ts)).collect();
    match level {
        Fidelity::Tbbo => Ok(ticks(served(reader.tbbo(trade_date), what)?.ts_recv)),
        Fidelity::Trades => Ok(ticks(served(reader.trades(trade_date), what)?.ts_recv)),
        Fidelity::Bars(timeframe) => {
            let bars = served(reader.bars(trade_date, timeframe), what)?;
            let spans = bars.ts_open.iter().zip(bars.ts_close);
            Ok(spans
                .map(|(open, close)| (*open, Ts(close.0.saturating_sub(1))))
                .collect())
        }
    }
}

fn check_records(reader: &impl MarketDataReader, day: &TapeDay) -> Result<(), Mismatch> {
    let date = day.trade_date;
    if !day.tbbo.is_empty() {
        let what = format!("the TBBO records of {date}");
        check_tbbo(&what, &day.tbbo, served(reader.tbbo(date), &what)?)?;
    }
    if !day.trades.is_empty() {
        let what = format!("the trades of {date}");
        check_trades(&what, &day.trades, served(reader.trades(date), &what)?)?;
    }
    for (timeframe, bars) in day.bars.iter().filter(|(_, bars)| !bars.is_empty()) {
        let what = format!("the {timeframe} bars of {date}");
        check_bars(&what, bars, served(reader.bars(date, *timeframe), &what)?)?;
    }
    Ok(())
}

fn check_trades(what: &str, rows: &[TradeRow], served: TradeColumns<'_>) -> Result<(), Mismatch> {
    expect_column(
        &format!("{what} ts_recv"),
        rows,
        |row| row.ts_recv,
        served.ts_recv,
    )?;
    expect_column(
        &format!("{what} price"),
        rows,
        |row| row.price,
        served.price,
    )?;
    expect_column(&format!("{what} size"), rows, |row| row.size, served.size)
}

fn check_tbbo(what: &str, rows: &[TbboRow], served: TbboColumns<'_>) -> Result<(), Mismatch> {
    expect_column(
        &format!("{what} ts_recv"),
        rows,
        |row| row.ts_recv,
        served.ts_recv,
    )?;
    expect_column(
        &format!("{what} price"),
        rows,
        |row| row.price,
        served.price,
    )?;
    expect_column(&format!("{what} size"), rows, |row| row.size, served.size)?;
    expect_column(&format!("{what} bid"), rows, |row| row.bid, served.bid)?;
    expect_column(&format!("{what} ask"), rows, |row| row.ask, served.ask)?;
    expect_column(
        &format!("{what} bid_size"),
        rows,
        |row| row.bid_size,
        served.bid_size,
    )?;
    expect_column(
        &format!("{what} ask_size"),
        rows,
        |row| row.ask_size,
        served.ask_size,
    )
}

fn check_bars(what: &str, rows: &[BarRow], served: BarColumns<'_>) -> Result<(), Mismatch> {
    expect_column(
        &format!("{what} ts_open"),
        rows,
        |row| row.ts_open,
        served.ts_open,
    )?;
    expect_column(
        &format!("{what} ts_close"),
        rows,
        |row| row.ts_close,
        served.ts_close,
    )?;
    expect_column(&format!("{what} open"), rows, |row| row.open, served.open)?;
    expect_column(&format!("{what} high"), rows, |row| row.high, served.high)?;
    expect_column(&format!("{what} low"), rows, |row| row.low, served.low)?;
    expect_column(
        &format!("{what} close"),
        rows,
        |row| row.close,
        served.close,
    )?;
    expect_column(
        &format!("{what} volume"),
        rows,
        |row| row.volume,
        served.volume,
    )
}

fn check_refusals(reader: &impl MarketDataReader) -> Result<(), Mismatch> {
    let unknown = refusal(reader.levels(TradeDate(20_519)));
    expect(
        "the levels of 2026-03-07, which the tape lacks",
        "an unknown trade date",
        unknown,
    )?;
    let trades = refusal(reader.trades(SECOND_DAY));
    expect(
        "the trades of 2026-03-06, which holds 5-minute bars alone",
        "a missing level",
        trades,
    )?;
    let bars = refusal(reader.bars(FIRST_DAY, Timeframe::FIVE_MINUTES));
    expect("the 5-minute bars of 2026-03-05", "a missing level", bars)?;
    let descent = refusal(reader.offsets(SECOND_DAY, Timeframe::FIVE_MINUTES, Fidelity::Trades));
    expect(
        "the offsets from 5m bars to trades on 2026-03-06",
        "a missing level",
        descent,
    )?;
    let minute = Fidelity::Bars(Timeframe::ONE_MINUTE);
    let ascent = refusal(reader.offsets(FIRST_DAY, Timeframe::ONE_SECOND, minute));
    expect(
        "the offsets from 1s bars to 1m bars",
        "a level that is not finer",
        ascent,
    )
}

fn refusal<T>(result: Result<T, MarketDataError>) -> &'static str {
    match result {
        Ok(_) => "data",
        Err(MarketDataError::UnknownTradeDate { .. }) => "an unknown trade date",
        Err(MarketDataError::LevelMissing { .. }) => "a missing level",
        Err(MarketDataError::NotFiner { .. }) => "a level that is not finer",
    }
}

fn expect_column<Row, Value: PartialEq + fmt::Debug>(
    what: &str,
    rows: &[Row],
    value: impl Fn(&Row) -> Value,
    served: &[Value],
) -> Result<(), Mismatch> {
    let expected: Vec<Value> = rows.iter().map(value).collect();
    expect(what, expected.as_slice(), served)
}

fn expect<T: PartialEq + fmt::Debug + ?Sized>(
    what: &str,
    expected: &T,
    actual: &T,
) -> Result<(), Mismatch> {
    if expected == actual {
        return Ok(());
    }
    Err(mismatch(
        what,
        format!("{expected:?}"),
        format!("{actual:?}"),
    ))
}

fn served<T>(result: Result<T, MarketDataError>, what: &str) -> Result<T, Mismatch> {
    result.map_err(|error| mismatch(what, "data", error.to_string()))
}

fn mismatch(what: &str, expected: impl Into<String>, actual: impl Into<String>) -> Mismatch {
    Mismatch {
        what: what.to_owned(),
        expected: expected.into(),
        actual: actual.into(),
    }
}
