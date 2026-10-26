//! A contract's cache mapped into memory and served as a [`MarketDataReader`] (`02` §1.6): each
//! month's files mapped once and read in place, so that the threads and processes that map them
//! share their pages.

mod arrays;
mod month;

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use arrow_buffer::Buffer;
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::{
    BarColumns, MarketDataError, MarketDataReader, TbboColumns, TradeColumns,
};

use crate::error::{CacheError, io_error};
use arrays::{BarArrays, TbboArrays, TradeArrays};
use month::{MappedDay, MappedMonth};

use crate::layout::{Month, PARTIAL_SUFFIX};

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
