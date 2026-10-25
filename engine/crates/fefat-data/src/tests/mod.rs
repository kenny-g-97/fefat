//! Tests of the cache: its writer and the rules it applies, its mapped reader, and the
//! conformance checks of step 2.4, which the mapped reader runs unchanged.

mod columns;
mod conformance;
mod offsets;
mod refusals;
mod rules;

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process;
use std::sync::atomic::{AtomicUsize, Ordering};

use fefat_core::instants::{NANOSECONDS_PER_SECOND, SECONDS_PER_DAY, TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::market_data::TapeDay;

use crate::{CacheError, CacheMonthIndex, CacheMonthWriter, MappedContract, Month, SourceFile};

static FOLDERS: AtomicUsize = AtomicUsize::new(0);

/// A folder of its own under the system's temporary folder, removed when dropped.
struct TemporaryFolder(PathBuf);

impl TemporaryFolder {
    fn new() -> Self {
        let number = FOLDERS.fetch_add(1, Ordering::Relaxed);
        let path = env::temp_dir().join(format!("fefat-data-{}-{number}", process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TemporaryFolder {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn sources() -> Vec<SourceFile> {
    vec![SourceFile {
        path: "synthetic/trades/root=ES/contract=ESH2026/date=2026-03-05/part.parquet".into(),
        sha256: "0".repeat(64),
    }]
}

/// Writes `days`, all of one month, as `contract`'s cache in `folder`.
fn write_month(
    folder: &Path,
    contract: &str,
    days: Vec<TapeDay>,
) -> Result<CacheMonthIndex, CacheError> {
    let month = Month::of(days[0].trade_date);
    let contract_folder = folder.join(contract);
    let contract = Contract(contract.to_owned());
    let mut writer = CacheMonthWriter::create(&contract_folder, contract, month, sources())?;
    for day in days {
        writer.write_trade_date(day)?;
    }
    writer.finish()
}

/// `days` written as one month of `contract`'s cache in `folder`, then mapped.
fn cached(folder: &Path, contract: &str, days: Vec<TapeDay>) -> Result<MappedContract, CacheError> {
    write_month(folder, contract, days)?;
    MappedContract::open(&folder.join(contract))
}

/// The day `days` later, every instant moved with it.
fn moved(day: &TapeDay, days: i32) -> TapeDay {
    let by = |ts: Ts| Ts(ts.0 + i64::from(days) * SECONDS_PER_DAY * NANOSECONDS_PER_SECOND);
    let mut later = day.clone();
    later.trade_date = TradeDate(day.trade_date.0 + days);
    later
        .tbbo
        .iter_mut()
        .for_each(|row| row.ts_recv = by(row.ts_recv));
    later
        .trades
        .iter_mut()
        .for_each(|row| row.ts_recv = by(row.ts_recv));
    for bar in later.bars.values_mut().flatten() {
        (bar.ts_open, bar.ts_close) = (by(bar.ts_open), by(bar.ts_close));
    }
    later
}
