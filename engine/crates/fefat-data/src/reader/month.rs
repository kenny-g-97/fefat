//! One month folder of a contract's cache: its index, its files mapped once, and each trade
//! date's columns read in place from them.

use std::collections::BTreeMap;
use std::path::Path;
use std::vec::IntoIter;

use arrow_array::{RecordBatch, UInt32Array};
use arrow_buffer::Buffer;
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;

use super::arrays::{BarArrays, TbboArrays, TradeArrays};
use crate::columns::{require_columns, uint32_array};
use crate::error::CacheError;
use crate::layout::{
    CacheMonthIndex, INDEX_FILE_NAME, LAYOUT_VERSION, Month, OFFSET_COLUMN, descent_file_name,
    descents, level_columns, level_file_name,
};
use crate::mapped::MappedFile;

/// One month folder's trade dates, read from its mapped files.
pub(super) struct MappedMonth {
    pub(super) month: Month,
    pub(super) days: Vec<(TradeDate, MappedDay)>,
    pub(super) maps: Vec<Buffer>,
}

impl MappedMonth {
    /// The month in `folder`, of `contract`'s cache, its files held to its index.
    pub(super) fn open(folder: &Path, contract: &Contract) -> Result<Self, CacheError> {
        let context = folder.display().to_string();
        let index = CacheMonthIndex::read(folder)?;
        let index = index.ok_or_else(|| {
            CacheError::refused(format!("the month's {INDEX_FILE_NAME}"), "none", &context)
        })?;
        if index.layout_version != LAYOUT_VERSION {
            let expected = format!("layout version {LAYOUT_VERSION}; rebuild the month");
            let actual = format!("version {}", index.layout_version);
            return Err(CacheError::refused(expected, actual, &context));
        }
        if index.contract != contract.0 {
            let expected = format!("the cache of {}", contract.0);
            return Err(CacheError::refused(expected, index.contract, &context));
        }
        require_listed_in_order(&index, &context)?;
        let mut files = BTreeMap::new();
        let mut maps = Vec::new();
        for name in index.files.keys() {
            let mapped = MappedFile::open(&folder.join(name))?;
            maps.push(mapped.bytes);
            files.insert(name.clone(), mapped.batches.into_iter());
        }
        let mut days = Vec::new();
        for cached in index.trade_dates {
            let trade_date = cached.trade_date;
            let day = MappedDay::read(trade_date, cached.levels, &mut files, &context)?;
            days.push((trade_date, day));
        }
        if let Some((name, _)) = files.iter().find(|(_, left)| !left.as_slice().is_empty()) {
            let actual = format!("more batches in {name}");
            return Err(CacheError::refused(
                "a batch per trade date",
                actual,
                &context,
            ));
        }
        Ok(Self {
            month: index.month,
            days,
            maps,
        })
    }
}

/// Refuses an index whose trade dates are not of its month and ascending, each with one or more
/// levels, finest first.
fn require_listed_in_order(index: &CacheMonthIndex, context: &str) -> Result<(), CacheError> {
    let month = index.month;
    let dates = index.trade_dates.iter().map(|cached| cached.trade_date);
    let in_order = dates.clone().all(|date| Month::of(date) == month)
        && dates
            .clone()
            .zip(dates.skip(1))
            .all(|(earlier, later)| earlier < later);
    if !in_order {
        let expected = format!("trade dates of {month}, ascending");
        let listed: Vec<String> = index
            .trade_dates
            .iter()
            .map(|cached| cached.trade_date.to_string())
            .collect();
        return Err(CacheError::refused(expected, listed.join(", "), context));
    }
    for cached in &index.trade_dates {
        let levels = &cached.levels;
        if levels.is_empty() || !levels.is_sorted_by(|finer, coarser| finer < coarser) {
            let actual = format!("{levels:?} on {}", cached.trade_date);
            return Err(CacheError::refused("levels finest first", actual, context));
        }
    }
    Ok(())
}

/// One trade date's columns, read in place from the month's mapped files.
pub(super) struct MappedDay {
    pub(super) levels: Vec<Fidelity>,
    pub(super) tbbo: Option<TbboArrays>,
    pub(super) trades: Option<TradeArrays>,
    pub(super) bars: BTreeMap<Timeframe, BarArrays>,
    pub(super) offsets: BTreeMap<(Timeframe, Fidelity), UInt32Array>,
}

impl MappedDay {
    fn read(
        trade_date: TradeDate,
        levels: Vec<Fidelity>,
        files: &mut BTreeMap<String, IntoIter<RecordBatch>>,
        context: &str,
    ) -> Result<Self, CacheError> {
        let mut day = Self {
            levels: Vec::new(),
            tbbo: None,
            trades: None,
            bars: BTreeMap::new(),
            offsets: BTreeMap::new(),
        };
        for &level in &levels {
            let name = level_file_name(level);
            let batch = next_batch(files, &name, trade_date, context)?;
            let what = format!("the batch of {trade_date} in {name} of {context}");
            require_columns(&batch, level_columns(level), &what)?;
            match level {
                Fidelity::Tbbo => day.tbbo = Some(TbboArrays::of(&batch, &what)?),
                Fidelity::Trades => day.trades = Some(TradeArrays::of(&batch, &what)?),
                Fidelity::Bars(timeframe) => {
                    day.bars.insert(timeframe, BarArrays::of(&batch, &what)?);
                }
            }
        }
        for (timeframe, finer) in descents(&levels) {
            let name = descent_file_name(timeframe, finer);
            let batch = next_batch(files, &name, trade_date, context)?;
            let what = format!("the batch of {trade_date} in {name} of {context}");
            let offsets = day.checked_offsets(&batch, timeframe, finer, &what)?;
            day.offsets.insert((timeframe, finer), offsets);
        }
        day.levels = levels;
        Ok(day)
    }

    /// The descent's offsets, one per bar and one more, in order, the last counting the finer
    /// records.
    fn checked_offsets(
        &self,
        batch: &RecordBatch,
        timeframe: Timeframe,
        finer: Fidelity,
        what: &str,
    ) -> Result<UInt32Array, CacheError> {
        require_columns(batch, &[OFFSET_COLUMN], what)?;
        let column = batch.columns().first();
        let column = column.ok_or_else(|| CacheError::refused("one column", "none", what))?;
        let offsets = uint32_array(column, what)?.clone();
        let bars = self.record_count(Fidelity::Bars(timeframe));
        let records = self.record_count(finer);
        let last = offsets.values().last().map(|last| *last as usize);
        let in_order = offsets.values().is_sorted();
        if offsets.len() != bars + 1 || last != Some(records) || !in_order {
            let expected = format!("{} offsets in order, ending in {records}", bars + 1);
            let actual = format!("{} ending in {last:?}", offsets.len());
            return Err(CacheError::refused(expected, actual, what));
        }
        Ok(offsets)
    }

    fn record_count(&self, level: Fidelity) -> usize {
        match level {
            Fidelity::Tbbo => self.tbbo.as_ref().map_or(0, TbboArrays::len),
            Fidelity::Trades => self.trades.as_ref().map_or(0, TradeArrays::len),
            Fidelity::Bars(timeframe) => self.bars.get(&timeframe).map_or(0, BarArrays::len),
        }
    }
}

fn next_batch(
    files: &mut BTreeMap<String, IntoIter<RecordBatch>>,
    name: &str,
    trade_date: TradeDate,
    context: &str,
) -> Result<RecordBatch, CacheError> {
    let batch = files.get_mut(name).and_then(Iterator::next);
    batch.ok_or_else(|| {
        let expected = format!("a batch of {trade_date} in {name}");
        CacheError::refused(expected, "none", context)
    })
}
