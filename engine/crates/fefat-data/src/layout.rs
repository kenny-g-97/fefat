//! Where the cache keeps a contract-month and what its files and index hold (D-56).

use std::collections::BTreeMap;
use std::fmt;
use std::fs::{self, File};
use std::io::{ErrorKind, Write};
use std::path::Path;
use std::str::FromStr;
use std::sync::Arc;

use arrow_schema::{DataType, Field, Schema, SchemaRef};
use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use serde::{Deserialize, Serialize};

use crate::error::{CacheError, io_error};

/// The version of the cache's files, columns, and index; a month of another version is rebuilt.
pub const LAYOUT_VERSION: u32 = 1;
/// A month's index, written last: a month folder without it holds no cache.
pub const INDEX_FILE_NAME: &str = "index.json";
/// The suffix of a month folder being built, which a reader passes over.
pub(crate) const PARTIAL_SUFFIX: &str = ".partial";

/// The column of a descent file: entry `i` counts the finer rows before bar `i` opens, and one
/// more entry their count (`MarketDataReader::offsets`).
pub(crate) const OFFSET_COLUMN: &str = "offset";
/// A trade's columns, each int64: nanoseconds UTC, 1e-9 units, and lots.
pub(crate) const TRADE_COLUMNS: [&str; 3] = ["ts_recv", "price", "size"];
/// A TBBO record's columns, each int64: a trade's, then the quote just before it.
pub(crate) const TBBO_COLUMNS: [&str; 7] = [
    "ts_recv", "price", "size", "bid", "ask", "bid_size", "ask_size",
];
/// A bar's columns, each int64.
pub(crate) const BAR_COLUMNS: [&str; 7] = [
    "ts_open", "ts_close", "open", "high", "low", "close", "volume",
];

/// The columns of a level's file.
pub const fn level_columns(level: Fidelity) -> &'static [&'static str] {
    match level {
        Fidelity::Tbbo => &TBBO_COLUMNS,
        Fidelity::Trades => &TRADE_COLUMNS,
        Fidelity::Bars(_) => &BAR_COLUMNS,
    }
}

/// The schema of a level's file: its columns as int64 without nulls.
pub(crate) fn level_schema(level: Fidelity) -> SchemaRef {
    let fields = level_columns(level)
        .iter()
        .map(|name| Field::new(*name, DataType::Int64, false));
    Arc::new(Schema::new(fields.collect::<Vec<_>>()))
}

/// The schema of a descent file: one uint32 column without nulls.
pub(crate) fn descent_schema() -> SchemaRef {
    let field = Field::new(OFFSET_COLUMN, DataType::UInt32, false);
    Arc::new(Schema::new(vec![field]))
}

/// The file of a level, named by its fidelity: `trades.arrow`, `1m.arrow`.
pub(crate) fn level_file_name(level: Fidelity) -> String {
    format!("{level}.arrow")
}

/// The file of the descent from `timeframe`'s bars to `finer`: `1m-to-trades.arrow`.
pub(crate) fn descent_file_name(timeframe: Timeframe, finer: Fidelity) -> String {
    format!("{timeframe}-to-{finer}.arrow")
}

/// Each descent a trade date with `levels` serves, from each timeframe's bars to every finer
/// level, coarser bars first, as the in-memory reader serves them.
pub(crate) fn descents(levels: &[Fidelity]) -> Vec<(Timeframe, Fidelity)> {
    let timeframes = levels.iter().filter_map(|level| match level {
        Fidelity::Bars(timeframe) => Some(*timeframe),
        Fidelity::Tbbo | Fidelity::Trades => None,
    });
    timeframes
        .flat_map(|timeframe| {
            let finer = levels
                .iter()
                .filter(move |level| **level < Fidelity::Bars(timeframe));
            finer.map(move |level| (timeframe, *level))
        })
        .collect()
}

/// A month of trade dates, written `2026-03`: the folder of a contract's cache that holds the
/// trade dates of that month, and its text in the month's index.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct Month {
    year: i64,
    month: i64,
}

impl Month {
    /// The month a trade date belongs to.
    pub fn of(trade_date: TradeDate) -> Self {
        let (year, month, _) = trade_date.year_month_day();
        Self { year, month }
    }
}

impl fmt::Display for Month {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:04}-{:02}", self.year, self.month)
    }
}

impl FromStr for Month {
    type Err = CacheError;

    /// A month written `YYYY-MM`, as its folder is named.
    fn from_str(text: &str) -> Result<Self, Self::Err> {
        let refused = || {
            CacheError::refused(
                "a month written YYYY-MM, such as 2026-03",
                format!("{text:?}"),
                "the name of a cache month",
            )
        };
        let digits = |part: &str, width: usize| {
            let all_digits = part.len() == width && part.bytes().all(|byte| byte.is_ascii_digit());
            all_digits.then(|| part.parse::<i64>().ok()).flatten()
        };
        let (year, month) = text.split_once('-').ok_or_else(refused)?;
        let (Some(year), Some(month)) = (digits(year, 4), digits(month, 2)) else {
            return Err(refused());
        };
        if !(1..=12).contains(&month) {
            return Err(refused());
        }
        Ok(Self { year, month })
    }
}

impl TryFrom<String> for Month {
    type Error = CacheError;

    fn try_from(text: String) -> Result<Self, Self::Error> {
        text.parse()
    }
}

impl From<Month> for String {
    fn from(month: Month) -> Self {
        month.to_string()
    }
}

/// A store partition a month was built from: its path in the store and its SHA-256, the hashes
/// a snapshot pins (ADR-0019) and the cache's key.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceFile {
    /// The partition's path, relative to the store's folder, written with `/`.
    pub path: String,
    /// The partition's SHA-256, as 64 lowercase hex digits.
    pub sha256: String,
}

/// One trade date of a month: the levels it serves, finest first, the records cut at and after
/// the close of the last bar that holds them, and the levels left out, each with its reason.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CachedTradeDate {
    /// The trade date, written `2026-03-05`.
    pub trade_date: TradeDate,
    /// The levels it serves, finest first, written as the fidelity type spells them.
    pub levels: Vec<Fidelity>,
    /// The records cut, by level.
    pub cut: BTreeMap<Fidelity, u64>,
    /// The levels left out, each with its reason.
    pub left_out: BTreeMap<Fidelity, String>,
}

/// A file of a month: its rows and its size.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CachedFile {
    /// The rows of all its batches.
    pub rows: u64,
    /// Its size in bytes.
    pub bytes: u64,
}

/// A contract-month's index, `index.json`: the layout version, the contract and month, the
/// store partitions it was built from, its trade dates, and its files.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CacheMonthIndex {
    /// The [`LAYOUT_VERSION`] it was written with.
    pub layout_version: u32,
    /// The contract, such as `ESH2026`.
    pub contract: String,
    /// The month, written `2026-03`.
    pub month: Month,
    /// The store partitions it was built from, sorted by path.
    pub sources: Vec<SourceFile>,
    /// Its trade dates, ascending.
    pub trade_dates: Vec<CachedTradeDate>,
    /// Its files by name.
    pub files: BTreeMap<String, CachedFile>,
}

impl CacheMonthIndex {
    /// The index of the month in `month_folder`, or `None` while the folder holds none.
    pub fn read(month_folder: &Path) -> Result<Option<Self>, CacheError> {
        let path = month_folder.join(INDEX_FILE_NAME);
        let content = match fs::read(&path) {
            Ok(content) => content,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(io_error("read", &path)(error)),
        };
        serde_json::from_slice(&content)
            .map(Some)
            .map_err(|source| CacheError::Index { path, source })
    }

    /// Write the index into `month_folder` and flush it to disk, as the month's other files are.
    pub(crate) fn write(&self, month_folder: &Path) -> Result<(), CacheError> {
        let path = month_folder.join(INDEX_FILE_NAME);
        let mut content = serde_json::to_vec_pretty(self).map_err(|source| CacheError::Index {
            path: path.clone(),
            source,
        })?;
        content.push(b'\n');
        let mut file = File::create(&path).map_err(io_error("create", &path))?;
        file.write_all(&content).map_err(io_error("write", &path))?;
        file.sync_all().map_err(io_error("flush", &path))
    }
}
