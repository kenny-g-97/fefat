//! What the cache keeps of a trade date's records (D-56), so that a descent from a bar finds the
//! bar's whole trading in the finer records and never meets a record that no stored bar holds:
//!
//! - a level is left out where its records within a bar of a coarser intraday level it nests in
//!   do not add up to that bar's volume: it covers part of the date, from a file that starts,
//!   ends, or skips inside a session (checked coarsest first, so a level left out bounds no
//!   finer one);
//! - a coarser level is left out where a finer one runs on before its first bar or past the
//!   bucket after its last: its own file covers part of the date;
//! - records in that bucket after the last bar are cut: the bucket a dataset ends in keeps its
//!   ticks while its bar is held back (D-43, D-45);
//! - a level with a record outside every bar of a coarser level it nests in, inside that
//!   level's span, is left out too.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::{NANOSECONDS_PER_SECOND, Ts};
use fefat_core::instrument::Contract;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TapeError};

use crate::error::CacheError;

/// The records cut from each level.
pub(super) type Cut = BTreeMap<Fidelity, u64>;
/// The levels left out, each with its reason.
pub(super) type LeftOut = BTreeMap<Fidelity, String>;

/// The day, once every record of it is one the engine can read, by the in-memory reader's checks
/// of each record, which run before it holds the levels to each other: a record outside the bars
/// of a coarser level is left to the rules below, and any other refuses the day.
pub(super) fn readable(contract: &Contract, day: TapeDay) -> Result<TapeDay, CacheError> {
    match InMemoryMarketData::new(contract.clone(), vec![day.clone()]) {
        Ok(_) | Err(TapeError::RecordOutsideBars { .. }) => Ok(day),
        Err(refusal) => Err(tape_error(&day, refusal)),
    }
}

/// The day without each level whose records within some bar of a coarser intraday level it
/// nests in do not add up to that bar's volume, coarsest first, and each one left out with its
/// reason.
pub(super) fn leave_out_incomplete_levels(mut day: TapeDay) -> (TapeDay, LeftOut) {
    let mut left_out = LeftOut::new();
    for level in levels_of(&day).into_iter().rev() {
        if let Some(reason) = unmatched_volume(&day, level) {
            remove_level(&mut day, level);
            left_out.insert(level, reason);
        }
    }
    (day, left_out)
}

/// The day without each intraday bar level whose bars stop short of a finer level that nests in
/// them, coarsest first: a finer record before its first bar opens, or after the bucket that
/// follows its last bar, which a dataset ending there holds back (D-43, D-45), shows that its
/// file covers part of the date while the finer one runs on.
pub(super) fn leave_out_short_levels(mut day: TapeDay, left_out: &mut LeftOut) -> TapeDay {
    let timeframes: Vec<Timeframe> = day.bars.keys().rev().copied().collect();
    for timeframe in timeframes {
        if let Some(reason) = short_of(&day, timeframe) {
            let level = Fidelity::Bars(timeframe);
            remove_level(&mut day, level);
            left_out.insert(level, reason);
        }
    }
    day
}

/// Why `timeframe`'s bars stop short of a finer level that nests in them, or `None` while every
/// such level starts inside its first bar and ends by the bucket after its last.
fn short_of(day: &TapeDay, timeframe: Timeframe) -> Option<String> {
    let bars = day.bars.get(&timeframe)?;
    let (first, last) = (bars.first()?, bars.last()?);
    let length = i64::try_from(timeframe.nominal_seconds())
        .ok()?
        .checked_mul(NANOSECONDS_PER_SECOND)?;
    let coarser = Fidelity::Bars(timeframe);
    let finer_levels = levels_of(day)
        .into_iter()
        .filter(|level| *level < coarser && level.nests_in(timeframe));
    for finer in finer_levels {
        let starts: Vec<Ts> = lots_by_start(day, finer)
            .into_iter()
            .map(|(start, _)| start)
            .collect();
        if let Some(early) = starts.first().filter(|start| **start < first.ts_open) {
            return Some(format!(
                "the {finer} records start at {early}, before its first bar opens at {}",
                first.ts_open
            ));
        }
        let Some(after) = starts.iter().find(|start| **start >= last.ts_close) else {
            continue;
        };
        let buckets = (after.0 - last.ts_close.0) / length + 1;
        let held_back_until = last
            .ts_close
            .checked_add_nanoseconds(buckets.checked_mul(length)?)
            .ok()?;
        if let Some(end) = starts.last().filter(|end| **end >= held_back_until) {
            return Some(format!(
                "the {finer} records run on to {end}, past the bucket after its last bar, which \
                 closes at {}",
                last.ts_close
            ));
        }
    }
    None
}

/// The day without its records at or after the close of the last bar of any coarser intraday
/// level they nest in, and the count cut from each level.
pub(super) fn cut_after_the_last_bars(mut day: TapeDay) -> (TapeDay, Cut) {
    let ends: Vec<(Fidelity, Ts)> = levels_of(&day)
        .into_iter()
        .filter_map(|level| {
            let closes = holding_levels(&day, level).filter_map(|(_, bars)| bars.last());
            closes
                .map(|last| last.ts_close)
                .min()
                .map(|end| (level, end))
        })
        .collect();
    let mut cut = Cut::new();
    for (level, end) in ends {
        let removed = keep_before(&mut day, level, end);
        if removed > 0 {
            cut.insert(level, removed);
        }
    }
    (day, cut)
}

/// The in-memory reader of the day, leaving out each level with a record outside every bar of a
/// coarser level it nests in; any other record the engine could not read refuses the day.
pub(super) fn served(
    contract: &Contract,
    mut day: TapeDay,
    left_out: &mut LeftOut,
) -> Result<InMemoryMarketData, CacheError> {
    loop {
        let refusal = match InMemoryMarketData::new(contract.clone(), vec![day.clone()]) {
            Ok(reader) => return Ok(reader),
            Err(refusal) => refusal,
        };
        let TapeError::RecordOutsideBars {
            timeframe,
            finer,
            record,
            ..
        } = refusal
        else {
            return Err(tape_error(&day, refusal));
        };
        if left_out.contains_key(&finer) {
            return Err(tape_error(&day, refusal));
        }
        remove_level(&mut day, finer);
        let reason = format!("its record {record} lies outside every {timeframe} bar");
        left_out.insert(finer, reason);
    }
}

const fn tape_error(day: &TapeDay, source: TapeError) -> CacheError {
    CacheError::Tape {
        trade_date: day.trade_date,
        source,
    }
}

/// Why the level's records within some bar of a coarser intraday level it nests in do not add
/// up to that bar's volume, or `None` while they do in every bar. Records out of time order are
/// left to the in-memory reader, which refuses them.
fn unmatched_volume(day: &TapeDay, level: Fidelity) -> Option<String> {
    let records = lots_by_start(day, level);
    if !records.is_sorted_by_key(|(start, _)| *start) {
        return None;
    }
    for (timeframe, bars) in holding_levels(day, level) {
        for bar in bars {
            let first = records.partition_point(|(start, _)| *start < bar.ts_open);
            let end = records.partition_point(|(start, _)| *start < bar.ts_close);
            let held = end.saturating_sub(first);
            let lots: i128 = records
                .iter()
                .skip(first)
                .take(held)
                .map(|(_, lots)| lots)
                .sum();
            if lots != i128::from(bar.volume.0) {
                return Some(format!(
                    "its records in the {timeframe} bar opening at {} add up to {lots} lots, \
                     not the bar's {}",
                    bar.ts_open, bar.volume
                ));
            }
        }
    }
    None
}

/// The levels the day holds, finest first.
fn levels_of(day: &TapeDay) -> Vec<Fidelity> {
    let ticks = [
        (!day.tbbo.is_empty()).then_some(Fidelity::Tbbo),
        (!day.trades.is_empty()).then_some(Fidelity::Trades),
    ];
    let bars = day
        .bars
        .iter()
        .filter(|(_, rows)| !rows.is_empty())
        .map(|(timeframe, _)| Fidelity::Bars(*timeframe));
    ticks.into_iter().flatten().chain(bars).collect()
}

/// Each coarser intraday bar level of the day that `level` nests in, coarsest first.
fn holding_levels(day: &TapeDay, level: Fidelity) -> impl Iterator<Item = (Timeframe, &[BarRow])> {
    day.bars
        .iter()
        .rev()
        .filter(move |(timeframe, _)| {
            Fidelity::Bars(**timeframe) > level && level.nests_in(**timeframe)
        })
        .map(|(timeframe, bars)| (*timeframe, bars.as_slice()))
}

/// Each record of the level as the instant it starts at, a tick's `ts_recv` or a bar's
/// `ts_open`, and the lots it traded.
fn lots_by_start(day: &TapeDay, level: Fidelity) -> Vec<(Ts, i128)> {
    match level {
        Fidelity::Tbbo => day
            .tbbo
            .iter()
            .map(|row| (row.ts_recv, i128::from(row.size.0)))
            .collect(),
        Fidelity::Trades => day
            .trades
            .iter()
            .map(|row| (row.ts_recv, i128::from(row.size.0)))
            .collect(),
        Fidelity::Bars(timeframe) => day.bars.get(&timeframe).map_or_else(Vec::new, |bars| {
            bars.iter()
                .map(|bar| (bar.ts_open, i128::from(bar.volume.0)))
                .collect()
        }),
    }
}

/// Keeps the level's records that start before `end`, and returns how many it removed.
fn keep_before(day: &mut TapeDay, level: Fidelity, end: Ts) -> u64 {
    let before = record_count(day, level);
    match level {
        Fidelity::Tbbo => day.tbbo.retain(|row| row.ts_recv < end),
        Fidelity::Trades => day.trades.retain(|row| row.ts_recv < end),
        Fidelity::Bars(timeframe) => {
            if let Some(bars) = day.bars.get_mut(&timeframe) {
                bars.retain(|bar| bar.ts_open < end);
            }
        }
    }
    (before - record_count(day, level)) as u64
}

fn record_count(day: &TapeDay, level: Fidelity) -> usize {
    match level {
        Fidelity::Tbbo => day.tbbo.len(),
        Fidelity::Trades => day.trades.len(),
        Fidelity::Bars(timeframe) => day.bars.get(&timeframe).map_or(0, Vec::len),
    }
}

fn remove_level(day: &mut TapeDay, level: Fidelity) {
    match level {
        Fidelity::Tbbo => day.tbbo.clear(),
        Fidelity::Trades => day.trades.clear(),
        Fidelity::Bars(timeframe) => {
            day.bars.remove(&timeframe);
        }
    }
}
