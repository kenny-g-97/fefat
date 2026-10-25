//! A contract's cache mapped into memory and served as a [`MarketDataReader`] (`02` §1.6): each
//! month's files mapped once and read in place, so that the threads and processes that map them
//! share their pages.

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::vec::IntoIter;

use arrow_array::{Int64Array, RecordBatch, UInt32Array};
use arrow_buffer::Buffer;
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::{
    BarColumns, MarketDataError, MarketDataReader, TbboColumns, TradeColumns,
};

use crate::columns::{int64_array, require_columns, uint32_array};
use crate::error::{CacheError, io_error};
use crate::layout::{
    CacheMonthIndex, INDEX_FILE_NAME, LAYOUT_VERSION, Month, OFFSET_COLUMN, PARTIAL_SUFFIX,
    descent_file_name, descents, level_columns, level_file_name,
};
use crate::mapped::{MappedFile, as_newtypes};

/// One contract's cache, every month of it, mapped into memory.
pub struct MappedContract {
    contract: Contract,
    trade_dates: Vec<TradeDate>,
    first: TradeDate,
    last: TradeDate,
    days: BTreeMap<TradeDate, MappedDay>,
    maps: Vec<Buffer>,
}

impl MappedContract {
    /// The cache in `contract_folder`, named after its contract: each month folder `YYYY-MM` in
    /// it, with its index. A folder `<month>.partial` is a month being built and is passed over;
    /// anything else is refused.
    pub fn open(contract_folder: &Path) -> Result<Self, CacheError> {
        let context = contract_folder.display().to_string();
        let name = contract_folder.file_name().and_then(|name| name.to_str());
        let contract = Contract(
            name.ok_or_else(|| CacheError::refused("a contract folder", "no name", &context))?
                .to_owned(),
        );
        let mut months = Vec::new();
        for (folder_month, folder) in month_folders(contract_folder)? {
            let month = MappedMonth::open(&folder, &contract)?;
            if month.month != folder_month {
                let (expected, actual) = (folder_month.to_string(), month.month.to_string());
                return Err(CacheError::refused(
                    expected,
                    actual,
                    folder.display().to_string(),
                ));
            }
            months.push(month);
        }
        Self::of_months(contract, months)
    }

    /// The cache of `contract` in the given month folders, whatever their names.
    pub(crate) fn open_months<'a>(
        contract: Contract,
        month_folders: impl IntoIterator<Item = &'a Path>,
    ) -> Result<Self, CacheError> {
        let months = month_folders
            .into_iter()
            .map(|folder| MappedMonth::open(folder, &contract))
            .collect::<Result<Vec<_>, _>>()?;
        Self::of_months(contract, months)
    }

    fn of_months(contract: Contract, months: Vec<MappedMonth>) -> Result<Self, CacheError> {
        let mut days = BTreeMap::new();
        let mut maps = Vec::new();
        for month in months {
            maps.extend(month.maps);
            for (trade_date, day) in month.days {
                if days.insert(trade_date, day).is_some() {
                    let context = format!("the cache of {}", contract.0);
                    let actual = format!("{trade_date} twice");
                    return Err(CacheError::refused("each trade date once", actual, context));
                }
            }
        }
        let trade_dates: Vec<TradeDate> = days.keys().copied().collect();
        let (Some(&first), Some(&last)) = (trade_dates.first(), trade_dates.last()) else {
            let context = format!("the cache of {}", contract.0);
            return Err(CacheError::refused(
                "a cached month or more",
                "none",
                context,
            ));
        };
        Ok(Self {
            contract,
            trade_dates,
            first,
            last,
            days,
            maps,
        })
    }

    fn day(&self, trade_date: TradeDate) -> Result<&MappedDay, MarketDataError> {
        self.days
            .get(&trade_date)
            .ok_or_else(|| MarketDataError::UnknownTradeDate {
                contract: self.contract.clone(),
                trade_date,
                first: self.first,
                last: self.last,
            })
    }

    fn missing(&self, trade_date: TradeDate, level: Fidelity, day: &MappedDay) -> MarketDataError {
        MarketDataError::LevelMissing {
            contract: self.contract.clone(),
            trade_date,
            level,
            present: day.levels.clone(),
        }
    }

    /// Whether `address` lies inside one of the files the reader maps.
    #[cfg(test)]
    pub(crate) fn maps_hold(&self, address: usize) -> bool {
        self.maps.iter().any(|bytes| {
            let start = bytes.as_ptr().addr();
            (start..start + bytes.len()).contains(&address)
        })
    }
}

impl fmt::Debug for MappedContract {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mapped: usize = self.maps.iter().map(Buffer::len).sum();
        formatter
            .debug_struct("MappedContract")
            .field("contract", &self.contract.0)
            .field("first", &self.first.to_string())
            .field("last", &self.last.to_string())
            .field("trade_dates", &self.trade_dates.len())
            .field("mapped_bytes", &mapped)
            .finish()
    }
}

impl MarketDataReader for MappedContract {
    fn contract(&self) -> &Contract {
        &self.contract
    }

    fn trade_dates(&self) -> &[TradeDate] {
        &self.trade_dates
    }

    fn levels(&self, trade_date: TradeDate) -> Result<&[Fidelity], MarketDataError> {
        Ok(&self.day(trade_date)?.levels)
    }

    fn bars(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
    ) -> Result<BarColumns<'_>, MarketDataError> {
        let day = self.day(trade_date)?;
        let bars = day.bars.get(&timeframe);
        bars.map(BarArrays::columns)
            .ok_or_else(|| self.missing(trade_date, Fidelity::Bars(timeframe), day))
    }

    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError> {
        let day = self.day(trade_date)?;
        let trades = day.trades.as_ref();
        trades
            .map(TradeArrays::columns)
            .ok_or_else(|| self.missing(trade_date, Fidelity::Trades, day))
    }

    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError> {
        let day = self.day(trade_date)?;
        let tbbo = day.tbbo.as_ref();
        tbbo.map(TbboArrays::columns)
            .ok_or_else(|| self.missing(trade_date, Fidelity::Tbbo, day))
    }

    fn offsets(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
        finer: Fidelity,
    ) -> Result<&[u32], MarketDataError> {
        let day = self.day(trade_date)?;
        if finer >= Fidelity::Bars(timeframe) {
            return Err(MarketDataError::NotFiner { timeframe, finer });
        }
        day.offsets
            .get(&(timeframe, finer))
            .map(|offsets| offsets.values().as_ref())
            .ok_or_else(|| {
                let absent = if day.bars.contains_key(&timeframe) {
                    finer
                } else {
                    Fidelity::Bars(timeframe)
                };
                self.missing(trade_date, absent, day)
            })
    }
}

/// The month folders of a contract's folder, by month, passing over the months being built.
fn month_folders(contract_folder: &Path) -> Result<Vec<(Month, PathBuf)>, CacheError> {
    let entries = fs::read_dir(contract_folder).map_err(io_error("list", contract_folder))?;
    let mut months = Vec::new();
    for entry in entries {
        let entry = entry.map_err(io_error("list", contract_folder))?;
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.ends_with(PARTIAL_SUFFIX) {
            continue;
        }
        months.push((name.parse::<Month>()?, entry.path()));
    }
    months.sort();
    Ok(months)
}

/// One month folder's trade dates, read from its mapped files.
struct MappedMonth {
    month: Month,
    days: Vec<(TradeDate, MappedDay)>,
    maps: Vec<Buffer>,
}

impl MappedMonth {
    fn open(folder: &Path, contract: &Contract) -> Result<Self, CacheError> {
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
        let month: Month = index.month.parse()?;
        let listed = listed_trade_dates(&index, month, &context)?;
        let mut files = BTreeMap::new();
        let mut maps = Vec::new();
        for name in index.files.keys() {
            let mapped = MappedFile::open(&folder.join(name))?;
            maps.push(mapped.bytes);
            files.insert(name.clone(), mapped.batches.into_iter());
        }
        let mut days = Vec::new();
        for (trade_date, levels) in listed {
            let day = MappedDay::read(trade_date, levels, &mut files, &context)?;
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
        Ok(Self { month, days, maps })
    }
}

/// The index's trade dates with their levels: dates of its month, ascending, each with one or
/// more levels, finest first.
fn listed_trade_dates(
    index: &CacheMonthIndex,
    month: Month,
    context: &str,
) -> Result<Vec<(TradeDate, Vec<Fidelity>)>, CacheError> {
    let mut listed: Vec<(TradeDate, Vec<Fidelity>)> = Vec::new();
    for cached in &index.trade_dates {
        let trade_date: TradeDate = cached
            .trade_date
            .parse()
            .map_err(|error| CacheError::refused("a trade date", format!("{error}"), context))?;
        let after_the_last = listed.last().is_none_or(|(last, _)| *last < trade_date);
        if Month::of(trade_date) != month || !after_the_last {
            let expected = format!("trade dates of {month}, ascending");
            return Err(CacheError::refused(
                expected,
                trade_date.to_string(),
                context,
            ));
        }
        let levels = cached
            .levels
            .iter()
            .map(|level| level.parse::<Fidelity>())
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| CacheError::refused("a level", error.to_string(), context))?;
        if levels.is_empty() || !levels.is_sorted_by(|finer, coarser| finer < coarser) {
            let actual = format!("{:?} on {trade_date}", cached.levels);
            return Err(CacheError::refused("levels finest first", actual, context));
        }
        listed.push((trade_date, levels));
    }
    Ok(listed)
}

/// One trade date's columns, read in place from the month's mapped files.
struct MappedDay {
    levels: Vec<Fidelity>,
    tbbo: Option<TbboArrays>,
    trades: Option<TradeArrays>,
    bars: BTreeMap<Timeframe, BarArrays>,
    offsets: BTreeMap<(Timeframe, Fidelity), UInt32Array>,
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

    /// The descent's offsets, one per bar and one more, the last counting the finer records.
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
        let bars = self
            .bars
            .get(&timeframe)
            .map_or(0, |bars| bars.ts_open.len());
        let records = self.record_count(finer);
        let last = offsets.values().last().map(|last| *last as usize);
        if offsets.len() != bars + 1 || last != Some(records) {
            let expected = format!("{} offsets ending in {records}", bars + 1);
            let actual = format!("{} ending in {last:?}", offsets.len());
            return Err(CacheError::refused(expected, actual, what));
        }
        Ok(offsets)
    }

    fn record_count(&self, level: Fidelity) -> usize {
        match level {
            Fidelity::Tbbo => self
                .tbbo
                .as_ref()
                .map_or(0, |tbbo| tbbo.trades.ts_recv.len()),
            Fidelity::Trades => self
                .trades
                .as_ref()
                .map_or(0, |trades| trades.ts_recv.len()),
            Fidelity::Bars(timeframe) => self
                .bars
                .get(&timeframe)
                .map_or(0, |bars| bars.ts_open.len()),
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

fn column(batch: &RecordBatch, name: &str, what: &str) -> Result<Int64Array, CacheError> {
    let array = batch.column_by_name(name);
    let array =
        array.ok_or_else(|| CacheError::refused(format!("the column {name}"), "none", what))?;
    Ok(int64_array(array, name, what)?.clone())
}

struct TradeArrays {
    ts_recv: Int64Array,
    price: Int64Array,
    size: Int64Array,
}

impl TradeArrays {
    fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
        Ok(Self {
            ts_recv: column(batch, "ts_recv", what)?,
            price: column(batch, "price", what)?,
            size: column(batch, "size", what)?,
        })
    }

    fn columns(&self) -> TradeColumns<'_> {
        TradeColumns {
            ts_recv: as_newtypes(self.ts_recv.values()),
            price: as_newtypes(self.price.values()),
            size: as_newtypes(self.size.values()),
        }
    }
}

struct TbboArrays {
    trades: TradeArrays,
    bid: Int64Array,
    ask: Int64Array,
    bid_size: Int64Array,
    ask_size: Int64Array,
}

impl TbboArrays {
    fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
        Ok(Self {
            trades: TradeArrays::of(batch, what)?,
            bid: column(batch, "bid", what)?,
            ask: column(batch, "ask", what)?,
            bid_size: column(batch, "bid_size", what)?,
            ask_size: column(batch, "ask_size", what)?,
        })
    }

    fn columns(&self) -> TbboColumns<'_> {
        let trades = self.trades.columns();
        TbboColumns {
            ts_recv: trades.ts_recv,
            price: trades.price,
            size: trades.size,
            bid: as_newtypes(self.bid.values()),
            ask: as_newtypes(self.ask.values()),
            bid_size: as_newtypes(self.bid_size.values()),
            ask_size: as_newtypes(self.ask_size.values()),
        }
    }
}

struct BarArrays {
    ts_open: Int64Array,
    ts_close: Int64Array,
    open: Int64Array,
    high: Int64Array,
    low: Int64Array,
    close: Int64Array,
    volume: Int64Array,
}

impl BarArrays {
    fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
        Ok(Self {
            ts_open: column(batch, "ts_open", what)?,
            ts_close: column(batch, "ts_close", what)?,
            open: column(batch, "open", what)?,
            high: column(batch, "high", what)?,
            low: column(batch, "low", what)?,
            close: column(batch, "close", what)?,
            volume: column(batch, "volume", what)?,
        })
    }

    fn columns(&self) -> BarColumns<'_> {
        BarColumns {
            ts_open: as_newtypes(self.ts_open.values()),
            ts_close: as_newtypes(self.ts_close.values()),
            open: as_newtypes(self.open.values()),
            high: as_newtypes(self.high.values()),
            low: as_newtypes(self.low.values()),
            close: as_newtypes(self.close.values()),
            volume: as_newtypes(self.volume.values()),
        }
    }
}
