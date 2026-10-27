//! The engine's market-data cache (`02` §1.6, D-56): each contract-month of one provider's data
//! as uncompressed Arrow IPC files, one per level and one per descent from a timeframe's bars to
//! a finer level, with an `index.json`, under
//! `<FEFAT_HOME>/cache/engine/<provider>/<root>/<contract>/<YYYY-MM>/`.
//!
//! [`CacheMonthWriter`] builds a month from tape days that [`tape_day`] reads from Arrow, and
//! [`MappedContract`] maps a contract's months into memory and serves them as a
//! [`fefat_core::market_data::MarketDataReader`]. This is the only engine crate that opens files
//! and the only one with `unsafe`, which its module `mapped` holds.

mod columns;
mod error;
mod layout;
mod mapped;
mod reader;
mod writer;

#[cfg(test)]
mod tests;

pub use columns::tape_day;
pub use error::CacheError;
pub use layout::{
    CacheMonthIndex, CachedFile, CachedTradeDate, INDEX_FILE_NAME, LAYOUT_VERSION, Month,
    SourceFile, level_columns,
};
pub use reader::MappedContract;
pub use writer::CacheMonthWriter;
