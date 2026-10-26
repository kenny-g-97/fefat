//! Building one contract-month of the cache (D-56): each trade date's records, after the rules
//! of [`rules`], are checked as the in-memory reader checks a tape and written as one batch per
//! level and per descent into `<month>.partial`, which takes the month's name once its files,
//! its index, and a check of its offsets through the mapped reader are done.

mod rules;

use std::collections::BTreeMap;
use std::collections::btree_map::Entry;
use std::fs::{self, File};
use std::io::BufWriter;
use std::path::{Path, PathBuf};

use arrow_array::RecordBatch;
use arrow_ipc::writer::FileWriter;
use arrow_schema::SchemaRef;
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::conformance::check_offsets;
use fefat_core::market_data::{MarketDataReader, TapeDay};

use crate::columns::{descent_batch, level_batch};
use crate::error::{CacheError, arrow_error, io_error};
use crate::layout::{
    CacheMonthIndex, CachedFile, CachedTradeDate, LAYOUT_VERSION, Month, PARTIAL_SUFFIX,
    SourceFile, descent_file_name, descent_schema, descents, level_file_name, level_schema,
};
use crate::reader::MappedContract;

/// A writer of one contract-month of the cache, its trade dates written in ascending order.
pub struct CacheMonthWriter {
    contract: Contract,
    month: Month,
    month_folder: PathBuf,
    partial: PathBuf,
    sources: Vec<SourceFile>,
    trade_dates: Vec<CachedTradeDate>,
    last: Option<TradeDate>,
    files: BTreeMap<String, OpenFile>,
}

impl CacheMonthWriter {
    /// A writer of `contract`'s `month` into `contract_folder`, built from the store partitions
    /// `sources`. It writes into `<month>.partial` and renames that folder `<month>` at
    /// [`Self::finish`], so that a month folder holds a whole cache; either folder already there
    /// is refused, since the caller removes a stale month first.
    pub fn create(
        contract_folder: &Path,
        contract: Contract,
        month: Month,
        mut sources: Vec<SourceFile>,
    ) -> Result<Self, CacheError> {
        let month_folder = contract_folder.join(month.to_string());
        let partial = contract_folder.join(format!("{month}{PARTIAL_SUFFIX}"));
        for folder in [&month_folder, &partial] {
            if folder.exists() {
                let actual = format!("{} already there", folder.display());
                return Err(CacheError::refused(
                    "no such folder",
                    actual,
                    "a new cache month",
                ));
            }
        }
        fs::create_dir_all(contract_folder).map_err(io_error("create", contract_folder))?;
        fs::create_dir(&partial).map_err(io_error("create", &partial))?;
        sources.sort();
        Ok(Self {
            contract,
            month,
            month_folder,
            partial,
            sources,
            trade_dates: Vec::new(),
            last: None,
            files: BTreeMap::new(),
        })
    }

    /// Writes one trade date of the month, after the dates written before it, with the records
    /// and levels the rules of the module `rules` keep, and returns what was kept.
    pub fn write_trade_date(&mut self, day: TapeDay) -> Result<CachedTradeDate, CacheError> {
        let trade_date = day.trade_date;
        self.require_next(trade_date)?;
        let readable = rules::readable(&self.contract, day)?;
        let (day, mut left_out) = rules::leave_out_incomplete_levels(readable.day);
        let day = rules::leave_out_short_levels(day, &mut left_out);
        let (day, cut) = rules::cut_after_the_last_bars(day);
        let reader = match readable.reader {
            Some(reader) if left_out.is_empty() && cut.is_empty() => reader,
            _ => rules::served(&self.contract, day, &mut left_out)?,
        };
        let levels = reader.levels(trade_date)?.to_vec();
        for &level in &levels {
            let batch = level_batch(&reader, trade_date, level)?;
            self.append(level_file_name(level), level_schema(level), &batch)?;
        }
        for (timeframe, finer) in descents(&levels) {
            let batch = descent_batch(&reader, trade_date, timeframe, finer)?;
            self.append(
                descent_file_name(timeframe, finer),
                descent_schema(),
                &batch,
            )?;
        }
        let written = CachedTradeDate {
            trade_date,
            levels,
            cut,
            left_out,
        };
        self.trade_dates.push(written.clone());
        self.last = Some(trade_date);
        Ok(written)
    }

    /// Drops the month: closes its files and removes its `<month>.partial` folder.
    pub fn abandon(self) -> Result<(), CacheError> {
        let partial = self.partial.clone();
        drop(self);
        fs::remove_dir_all(&partial).map_err(io_error("remove", &partial))
    }

    /// Closes the files, writes the index, checks every descent through the mapped reader
    /// (`check_offsets`), and gives the folder the month's name; a month refused on the way is
    /// removed.
    pub fn finish(self) -> Result<CacheMonthIndex, CacheError> {
        let partial = self.partial.clone();
        self.finished()
            .map_err(|refusal| match fs::remove_dir_all(&partial) {
                Ok(()) => refusal,
                Err(source) => CacheError::NotRemoved {
                    refusal: Box::new(refusal),
                    path: partial,
                    source,
                },
            })
    }

    fn finished(self) -> Result<CacheMonthIndex, CacheError> {
        if self.trade_dates.is_empty() {
            let context = format!("the cache of {} for {}", self.contract.0, self.month);
            return Err(CacheError::refused("a trade date or more", "none", context));
        }
        let mut files = BTreeMap::new();
        for (name, file) in self.files {
            let path = self.partial.join(&name);
            files.insert(name, file.finish(&path)?);
        }
        let index = CacheMonthIndex {
            layout_version: LAYOUT_VERSION,
            contract: self.contract.0.clone(),
            month: self.month,
            sources: self.sources,
            trade_dates: self.trade_dates,
            files,
        };
        index.write(&self.partial)?;
        check_through_the_maps(&self.partial, self.contract)?;
        fs::rename(&self.partial, &self.month_folder).map_err(io_error("rename", &self.partial))?;
        Ok(index)
    }

    fn require_next(&self, trade_date: TradeDate) -> Result<(), CacheError> {
        let context = format!("the cache of {} for {}", self.contract.0, self.month);
        if Month::of(trade_date) != self.month {
            let expected = format!("a trade date of {}", self.month);
            return Err(CacheError::refused(
                expected,
                trade_date.to_string(),
                context,
            ));
        }
        if let Some(last) = self.last.filter(|last| trade_date <= *last) {
            let expected = format!("a trade date after {last}");
            return Err(CacheError::refused(
                expected,
                trade_date.to_string(),
                context,
            ));
        }
        Ok(())
    }

    fn append(
        &mut self,
        name: String,
        schema: SchemaRef,
        batch: &RecordBatch,
    ) -> Result<(), CacheError> {
        let path = self.partial.join(&name);
        let file = match self.files.entry(name) {
            Entry::Occupied(entry) => entry.into_mut(),
            Entry::Vacant(entry) => entry.insert(OpenFile::create(&path, &schema)?),
        };
        file.append(&path, batch)
    }
}

/// Opens the month as the engine will and holds every descent to the conformance check.
fn check_through_the_maps(month_folder: &Path, contract: Contract) -> Result<(), CacheError> {
    let reader = MappedContract::open_months(contract, [month_folder])?;
    check_offsets(&reader).map_err(|mismatch| {
        let context = format!("{} in the cache {}", mismatch.what, month_folder.display());
        CacheError::refused(mismatch.expected, mismatch.actual, context)
    })
}

/// A level's or a descent's Arrow IPC file, open for one batch per trade date.
struct OpenFile {
    writer: FileWriter<BufWriter<File>>,
    rows: u64,
}

impl OpenFile {
    fn create(path: &Path, schema: &SchemaRef) -> Result<Self, CacheError> {
        let file = File::create(path).map_err(io_error("create", path))?;
        let writer =
            FileWriter::try_new(BufWriter::new(file), schema).map_err(arrow_error(path))?;
        Ok(Self { writer, rows: 0 })
    }

    fn append(&mut self, path: &Path, batch: &RecordBatch) -> Result<(), CacheError> {
        self.writer.write(batch).map_err(arrow_error(path))?;
        self.rows += batch.num_rows() as u64;
        Ok(())
    }

    fn finish(mut self, path: &Path) -> Result<CachedFile, CacheError> {
        self.writer.finish().map_err(arrow_error(path))?;
        let buffered = self.writer.into_inner().map_err(arrow_error(path))?;
        let file = buffered
            .into_inner()
            .map_err(|error| io_error("write", path)(error.into_error()))?;
        file.sync_all().map_err(io_error("flush", path))?;
        let bytes = file.metadata().map_err(io_error("measure", path))?.len();
        Ok(CachedFile {
            rows: self.rows,
            bytes,
        })
    }
}
