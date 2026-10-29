//! A run's inputs and outputs, shared by `fefat-cli` and `fefat-py` (step 2.10): the config a run
//! reads beside its specification and its signal frame ([`config`]), the signal rows of an Arrow
//! table ([`signal_rows`]), the run assembled from them and a reader of its records
//! ([`backtest`]), the tables of its outputs ([`artifacts`], [`trade_tables`]), and the hash of
//! an Arrow table, which keys a run's signal frame ([`table_hash`]). It opens no file: its callers
//! read and write them.

pub mod artifacts;
pub mod backtest;
pub mod config;
pub mod signal_rows;
pub mod table_hash;
pub mod trade_tables;

#[cfg(test)]
mod tests;
