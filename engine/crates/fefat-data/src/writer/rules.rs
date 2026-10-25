//! What the cache keeps of a trade date's records (D-56), so that a descent from a bar never
//! meets a record that no stored bar holds and never finds nothing where the bars say there was
//! trading:
//!
//! - records at or after the close of the last bar that holds them are cut: the bucket a dataset
//!   ends in keeps its ticks while its bar is held back (D-43, D-45);
//! - a level that covers part of the date is left out: its first record outside the first bar of
//!   a coarser level it nests in, or its last before that level's last bar opens;
//! - a level with a record outside every bar of a level it nests in is left out too.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::Ts;
use fefat_core::instrument::Contract;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TapeError};

use crate::error::CacheError;

/// The records cut from each level.
pub(super) type Cut = BTreeMap<Fidelity, u64>;
/// The levels left out, each with its reason.
pub(super) type LeftOut = BTreeMap<Fidelity, String>;

/// The day without its records at or after the close of the last bar of any coarser intraday
/// level they nest in, and the count cut from each level.
pub(super) fn cut_after_the_last_bars(mut day: TapeDay) -> (TapeDay, Cut) {
    let ends: Vec<(Fidelity, Ts)> = levels_of(&day)
        .into_iter()
        .filter_map(|level| {
            let closes = holding_bars(&day, level).map(|(_, _, last)| last.ts_close);
            closes.min().map(|end| (level, end))
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

/// The day without the levels that cover part of it, coarsest first, so that a level left out
/// bounds no finer level, and each one left out with its reason.
pub(super) fn leave_out_partial_levels(mut day: TapeDay) -> (TapeDay, LeftOut) {
    let mut left_out = LeftOut::new();
    for level in levels_of(&day).into_iter().rev() {
        if let Some(reason) = partial_cover(&day, level) {
            remove_level(&mut day, level);
            left_out.insert(level, reason);
        }
    }
    (day, left_out)
}

/// The in-memory reader of the day, leaving out each level with a record outside every bar of a
/// level it nests in; any other record the engine could not read refuses the day.
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

/// Why a level covers part of the day, or `None` while it covers each coarser level it nests in
/// from that level's first bar to its last.
fn partial_cover(day: &TapeDay, level: Fidelity) -> Option<String> {
    let (first, last) = record_span(day, level)?;
    for (timeframe, first_bar, last_bar) in holding_bars(day, level) {
        if first < first_bar.ts_open || first >= first_bar.ts_close {
            return Some(format!(
                "its first record, at {first}, lies outside the first {timeframe} bar"
            ));
        }
        if last < last_bar.ts_open {
            return Some(format!(
                "its last record, at {last}, comes before the last {timeframe} bar opens"
            ));
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

/// Each coarser intraday bar level of the day that `level` nests in, with its first and last
/// bar.
fn holding_bars(
    day: &TapeDay,
    level: Fidelity,
) -> impl Iterator<Item = (Timeframe, &BarRow, &BarRow)> {
    day.bars.iter().filter_map(move |(timeframe, rows)| {
        let holds = Fidelity::Bars(*timeframe) > level && level.nests_in(*timeframe);
        let (first, last) = (rows.first()?, rows.last()?);
        holds.then_some((*timeframe, first, last))
    })
}

/// The instants the level's first and last records start at: a tick its `ts_recv`, a bar its
/// `ts_open`.
fn record_span(day: &TapeDay, level: Fidelity) -> Option<(Ts, Ts)> {
    match level {
        Fidelity::Tbbo => Some((day.tbbo.first()?.ts_recv, day.tbbo.last()?.ts_recv)),
        Fidelity::Trades => Some((day.trades.first()?.ts_recv, day.trades.last()?.ts_recv)),
        Fidelity::Bars(timeframe) => {
            let bars = day.bars.get(&timeframe)?;
            Some((bars.first()?.ts_open, bars.last()?.ts_open))
        }
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
