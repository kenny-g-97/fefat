//! A trade date's columns of one level, as the mapped file's arrays, served as the newtypes they
//! hold.

use arrow_array::{Int64Array, RecordBatch};
use fefat_core::market_data::{BarColumns, TbboColumns, TradeColumns};

use crate::columns::int64_array;
use crate::error::CacheError;
use crate::mapped::as_newtypes;

fn column(batch: &RecordBatch, name: &str, what: &str) -> Result<Int64Array, CacheError> {
    let array = batch.column_by_name(name);
    let array =
        array.ok_or_else(|| CacheError::refused(format!("the column {name}"), "none", what))?;
    Ok(int64_array(array, name, what)?.clone())
}

/// A trade date's trades.
pub(super) struct TradeArrays {
    ts_recv: Int64Array,
    price: Int64Array,
    size: Int64Array,
}

impl TradeArrays {
    pub(super) fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
        Ok(Self {
            ts_recv: column(batch, "ts_recv", what)?,
            price: column(batch, "price", what)?,
            size: column(batch, "size", what)?,
        })
    }

    pub(super) fn len(&self) -> usize {
        self.ts_recv.len()
    }

    pub(super) fn columns(&self) -> TradeColumns<'_> {
        TradeColumns {
            ts_recv: as_newtypes(self.ts_recv.values()),
            price: as_newtypes(self.price.values()),
            size: as_newtypes(self.size.values()),
        }
    }
}

/// A trade date's TBBO records: trades, each with the quote just before it.
pub(super) struct TbboArrays {
    trades: TradeArrays,
    bid: Int64Array,
    ask: Int64Array,
    bid_size: Int64Array,
    ask_size: Int64Array,
}

impl TbboArrays {
    pub(super) fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
        Ok(Self {
            trades: TradeArrays::of(batch, what)?,
            bid: column(batch, "bid", what)?,
            ask: column(batch, "ask", what)?,
            bid_size: column(batch, "bid_size", what)?,
            ask_size: column(batch, "ask_size", what)?,
        })
    }

    pub(super) fn len(&self) -> usize {
        self.trades.len()
    }

    pub(super) fn columns(&self) -> TbboColumns<'_> {
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

/// A trade date's bars of one timeframe.
pub(super) struct BarArrays {
    ts_open: Int64Array,
    ts_close: Int64Array,
    open: Int64Array,
    high: Int64Array,
    low: Int64Array,
    close: Int64Array,
    volume: Int64Array,
}

impl BarArrays {
    pub(super) fn of(batch: &RecordBatch, what: &str) -> Result<Self, CacheError> {
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

    pub(super) fn len(&self) -> usize {
        self.ts_open.len()
    }

    pub(super) fn columns(&self) -> BarColumns<'_> {
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
