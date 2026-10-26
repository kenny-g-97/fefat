//! What the cache could not build or read.

use std::io;
use std::path::{Path, PathBuf};

use arrow_schema::ArrowError;
use fefat_core::instants::TradeDate;
use fefat_core::market_data::{MarketDataError, TapeError};
use thiserror::Error;

/// What the cache could not build or read, with the file, folder, or trade date it concerns.
#[derive(Debug, Error)]
pub enum CacheError {
    /// A file or folder the file system refused.
    #[error("Expected to {action} {path}, got: {source}")]
    Io {
        /// What was being done.
        action: &'static str,
        /// The file or folder.
        path: PathBuf,
        /// What the file system said.
        #[source]
        source: io::Error,
    },
    /// An Arrow IPC file that could not be written or read.
    #[error("Expected Arrow IPC in {path}, got: {source}")]
    Arrow {
        /// The file.
        path: PathBuf,
        /// What Arrow said.
        #[source]
        source: ArrowError,
    },
    /// A month's index that could not be written or read.
    #[error("Expected a cache index in {path}, got: {source}")]
    Index {
        /// The index file.
        path: PathBuf,
        /// What the JSON parser said.
        #[source]
        source: serde_json::Error,
    },
    /// A trade date whose records the engine could not read as the specification says.
    #[error("Expected records the engine can read on {trade_date}, got: {source}")]
    Tape {
        /// The trade date.
        trade_date: TradeDate,
        /// What the in-memory reader refused.
        #[source]
        source: TapeError,
    },
    /// A month refused part way whose folder could not be removed after.
    #[error("{refusal}; removing {path} failed too: {source}")]
    NotRemoved {
        /// Why the month was refused.
        refusal: Box<CacheError>,
        /// The folder left behind, which the next build removes.
        path: PathBuf,
        /// What the file system said.
        #[source]
        source: io::Error,
    },
    /// A level a trade date's reader could not serve.
    #[error(transparent)]
    MarketData(#[from] MarketDataError),
    /// Anything else the cache refuses: what it expected, what it got, and where.
    #[error("Expected {expected}, got {actual} in {context}")]
    Refused {
        /// What the cache expected.
        expected: String,
        /// What it found.
        actual: String,
        /// The file, folder, or trade date.
        context: String,
    },
}

impl CacheError {
    /// A refusal of `actual` where `expected` was due, in `context`.
    pub(crate) fn refused(
        expected: impl Into<String>,
        actual: impl Into<String>,
        context: impl Into<String>,
    ) -> Self {
        Self::Refused {
            expected: expected.into(),
            actual: actual.into(),
            context: context.into(),
        }
    }
}

/// The error of the file system refusing to `action` `path`.
pub(crate) fn io_error(action: &'static str, path: &Path) -> impl FnOnce(io::Error) -> CacheError {
    let path = path.to_path_buf();
    move |source| CacheError::Io {
        action,
        path,
        source,
    }
}

/// The error of Arrow refusing the file at `path`.
pub(crate) fn arrow_error(path: &Path) -> impl FnOnce(ArrowError) -> CacheError {
    let path = path.to_path_buf();
    move |source| CacheError::Arrow { path, source }
}
