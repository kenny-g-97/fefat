//! The offsets that take each bar of a trade date down to the records of a finer level
//! ([`super::MarketDataReader::offsets`]), worked out from a tape, which refuses a finer record
//! that no coarser bar holds whole.

use std::collections::BTreeMap;

use super::tape::{BarRow, TapeDay, TapeError};
use crate::fidelity::{Fidelity, Timeframe};
use crate::instants::{TradeDate, Ts};

/// The first and the last instant a record covers: a tick its receive instant, a bar every
/// instant from its open to just before its close.
#[derive(Debug, Clone, Copy)]
pub(super) struct Span {
    first: Ts,
    last: Ts,
}

/// Each level the day holds, finest first, with the spans of its records; `bars` are the day's
/// bars of each timeframe that has any.
pub(super) fn spans_by_level(
    day: &TapeDay,
    bars: &BTreeMap<Timeframe, &[BarRow]>,
) -> Vec<(Fidelity, Vec<Span>)> {
    let tick = |ts_recv: Ts| Span {
        first: ts_recv,
        last: ts_recv,
    };
    let mut levels = Vec::new();
    if !day.tbbo.is_empty() {
        levels.push((
            Fidelity::Tbbo,
            day.tbbo.iter().map(|row| tick(row.ts_recv)).collect(),
        ));
    }
    if !day.trades.is_empty() {
        levels.push((
            Fidelity::Trades,
            day.trades.iter().map(|row| tick(row.ts_recv)).collect(),
        ));
    }
    for (timeframe, rows) in bars {
        let spans = rows.iter().map(|bar| Span {
            first: bar.ts_open,
            last: Ts(bar.ts_close.0 - 1),
        });
        levels.push((Fidelity::Bars(*timeframe), spans.collect()));
    }
    levels
}

/// The offsets from each timeframe's bars to every finer level of the day.
pub(super) fn offsets_between_levels(
    trade_date: TradeDate,
    bars: &BTreeMap<Timeframe, &[BarRow]>,
    spans: &[(Fidelity, Vec<Span>)],
) -> Result<BTreeMap<(Timeframe, Fidelity), Vec<u32>>, TapeError> {
    let mut offsets = BTreeMap::new();
    for (timeframe, coarser) in bars {
        let finer_levels = spans
            .iter()
            .filter(|(level, _)| *level < Fidelity::Bars(*timeframe));
        for (finer, finer_spans) in finer_levels {
            let descent = Descent {
                trade_date,
                timeframe: *timeframe,
                finer: *finer,
            };
            if finer.nests_in(*timeframe) {
                descent.check_held_whole(coarser, finer_spans)?;
            }
            offsets.insert((*timeframe, *finer), descent.offsets(coarser, finer_spans)?);
        }
    }
    Ok(offsets)
}

/// The descent from one day's bars of a timeframe to the records of a finer level.
struct Descent {
    trade_date: TradeDate,
    timeframe: Timeframe,
    finer: Fidelity,
}

impl Descent {
    /// Refuses a finer record that no bar holds whole: one before the first bar, between two
    /// bars, after the last, or one that lasts past its bar's close.
    fn check_held_whole(&self, bars: &[BarRow], spans: &[Span]) -> Result<(), TapeError> {
        let mut held_until = 0;
        for bar in bars {
            let start = spans.partition_point(|span| span.first < bar.ts_open);
            if start > held_until {
                return Err(self.outside(held_until));
            }
            let mut held = spans
                .iter()
                .skip(start)
                .take_while(|span| span.first < bar.ts_close);
            if let Some(sticking_out) = held.position(|span| span.last >= bar.ts_close) {
                return Err(self.outside(start + sticking_out));
            }
            held_until = spans.partition_point(|span| span.first < bar.ts_close);
        }
        if held_until < spans.len() {
            return Err(self.outside(held_until));
        }
        Ok(())
    }

    /// For each bar, the count of finer records before it opens, then their whole count.
    fn offsets(&self, bars: &[BarRow], spans: &[Span]) -> Result<Vec<u32>, TapeError> {
        let starts = bars
            .iter()
            .map(|bar| spans.partition_point(|span| span.first < bar.ts_open));
        let mut offsets: Vec<u32> = starts
            .map(|start| self.count(start))
            .collect::<Result<_, _>>()?;
        offsets.push(self.count(spans.len())?);
        Ok(offsets)
    }

    const fn outside(&self, index: usize) -> TapeError {
        TapeError::RecordOutsideBars {
            trade_date: self.trade_date,
            timeframe: self.timeframe,
            finer: self.finer,
            record: index + 1,
        }
    }

    fn count(&self, records: usize) -> Result<u32, TapeError> {
        u32::try_from(records).map_err(|_| TapeError::TooManyRecords {
            trade_date: self.trade_date,
            level: self.finer,
            records,
        })
    }
}
