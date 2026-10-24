//! A [`MarketDataReader`] over a tape held in memory, for tests and, from step 2.6, the tapes
//! `fefat-cli run` reads. The tape is checked once, when the reader is built, and the offsets
//! between its levels are worked out then.

use std::collections::BTreeMap;

use super::descent::{offsets_between_levels, spans_by_level};
use super::tape::{
    BarRow, TapeDay, TapeError, TbboRow, TradeRow, check_bars, check_quotes, check_ticks,
};
use super::{BarColumns, MarketDataError, MarketDataReader, TbboColumns, TradeColumns};
use crate::fidelity::{Fidelity, Timeframe};
use crate::instants::{TradeDate, Ts};
use crate::instrument::Contract;
use crate::units::{Price, Qty};

/// A [`MarketDataReader`] over one contract's tape, held in memory.
#[derive(Debug, Clone)]
pub struct InMemoryMarketData {
    contract: Contract,
    trade_dates: Vec<TradeDate>,
    first: TradeDate,
    last: TradeDate,
    days: BTreeMap<TradeDate, StoredDay>,
}

impl InMemoryMarketData {
    /// The reader of `contract`'s tape, `days` in ascending order. It refuses a tape that the
    /// engine could not read as the specification says, as `fefat.reference.tape` does: no days,
    /// dates out of order, a day without records, ticks out of `ts_recv` order, sizes or quotes
    /// below one lot, a bid at or above its ask, a bar that does not open before it closes, that
    /// lasts longer than its timeframe, whose low and high miss its open or close, or that
    /// overlaps the bar before, and a finer record that no coarser bar holds whole where the
    /// levels nest (ticks in any bars, finer bars in bars of a whole multiple of their length).
    pub fn new(contract: Contract, days: Vec<TapeDay>) -> Result<Self, TapeError> {
        let (Some(first), Some(last)) = (days.first(), days.last()) else {
            return Err(TapeError::Empty);
        };
        let (first, last) = (first.trade_date, last.trade_date);
        if let Some((previous, next)) = days
            .iter()
            .zip(days.iter().skip(1))
            .find(|(previous, next)| next.trade_date <= previous.trade_date)
        {
            return Err(TapeError::DatesNotAscending {
                previous: previous.trade_date,
                next: next.trade_date,
            });
        }
        let trade_dates = days.iter().map(|day| day.trade_date).collect();
        let days = days
            .iter()
            .map(|day| Ok((day.trade_date, StoredDay::checked(day)?)))
            .collect::<Result<_, TapeError>>()?;
        Ok(Self {
            contract,
            trade_dates,
            first,
            last,
            days,
        })
    }

    fn day(&self, trade_date: TradeDate) -> Result<&StoredDay, MarketDataError> {
        self.days
            .get(&trade_date)
            .ok_or_else(|| MarketDataError::UnknownTradeDate {
                contract: self.contract.clone(),
                trade_date,
                first: self.first,
                last: self.last,
            })
    }

    fn missing(&self, trade_date: TradeDate, level: Fidelity, day: &StoredDay) -> MarketDataError {
        MarketDataError::LevelMissing {
            contract: self.contract.clone(),
            trade_date,
            level,
            present: day.levels.clone(),
        }
    }
}

impl MarketDataReader for InMemoryMarketData {
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
        bars.map(BarTable::columns)
            .ok_or_else(|| self.missing(trade_date, Fidelity::Bars(timeframe), day))
    }

    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError> {
        let day = self.day(trade_date)?;
        let trades = day.trades.as_ref();
        trades
            .map(TradeTable::columns)
            .ok_or_else(|| self.missing(trade_date, Fidelity::Trades, day))
    }

    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError> {
        let day = self.day(trade_date)?;
        let tbbo = day.tbbo.as_ref();
        tbbo.map(TbboTable::columns)
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
            .map(Vec::as_slice)
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

/// One checked trade date, as columns, with the offsets between its levels.
#[derive(Debug, Clone)]
struct StoredDay {
    levels: Vec<Fidelity>,
    tbbo: Option<TbboTable>,
    trades: Option<TradeTable>,
    bars: BTreeMap<Timeframe, BarTable>,
    offsets: BTreeMap<(Timeframe, Fidelity), Vec<u32>>,
}

impl StoredDay {
    fn checked(day: &TapeDay) -> Result<Self, TapeError> {
        let trade_date = day.trade_date;
        let tbbo = day.tbbo.iter().map(|row| (row.ts_recv, row.size));
        check_ticks(trade_date, Fidelity::Tbbo, tbbo)?;
        check_quotes(trade_date, &day.tbbo)?;
        let trades = day.trades.iter().map(|row| (row.ts_recv, row.size));
        check_ticks(trade_date, Fidelity::Trades, trades)?;
        let bars: BTreeMap<Timeframe, &[BarRow]> = day
            .bars
            .iter()
            .filter(|(_, rows)| !rows.is_empty())
            .map(|(timeframe, rows)| (*timeframe, rows.as_slice()))
            .collect();
        for (timeframe, rows) in &bars {
            check_bars(trade_date, *timeframe, rows)?;
        }
        let spans = spans_by_level(day, &bars);
        if spans.is_empty() {
            return Err(TapeError::DayWithoutRecords { trade_date });
        }
        Ok(Self {
            levels: spans.iter().map(|(level, _)| *level).collect(),
            tbbo: (!day.tbbo.is_empty()).then(|| TbboTable::of(&day.tbbo)),
            trades: (!day.trades.is_empty()).then(|| TradeTable::of(&day.trades)),
            bars: bars
                .iter()
                .map(|(timeframe, rows)| (*timeframe, BarTable::of(rows)))
                .collect(),
            offsets: offsets_between_levels(trade_date, &bars, &spans)?,
        })
    }
}

#[derive(Debug, Clone)]
struct TradeTable {
    ts_recv: Vec<Ts>,
    price: Vec<Price>,
    size: Vec<Qty>,
}

impl TradeTable {
    fn of(rows: &[TradeRow]) -> Self {
        Self {
            ts_recv: rows.iter().map(|row| row.ts_recv).collect(),
            price: rows.iter().map(|row| row.price).collect(),
            size: rows.iter().map(|row| row.size).collect(),
        }
    }

    fn columns(&self) -> TradeColumns<'_> {
        TradeColumns {
            ts_recv: &self.ts_recv,
            price: &self.price,
            size: &self.size,
        }
    }
}

#[derive(Debug, Clone)]
struct TbboTable {
    trades: TradeTable,
    bid: Vec<Price>,
    ask: Vec<Price>,
    bid_size: Vec<Qty>,
    ask_size: Vec<Qty>,
}

impl TbboTable {
    fn of(rows: &[TbboRow]) -> Self {
        let trades = TradeTable {
            ts_recv: rows.iter().map(|row| row.ts_recv).collect(),
            price: rows.iter().map(|row| row.price).collect(),
            size: rows.iter().map(|row| row.size).collect(),
        };
        Self {
            trades,
            bid: rows.iter().map(|row| row.bid).collect(),
            ask: rows.iter().map(|row| row.ask).collect(),
            bid_size: rows.iter().map(|row| row.bid_size).collect(),
            ask_size: rows.iter().map(|row| row.ask_size).collect(),
        }
    }

    fn columns(&self) -> TbboColumns<'_> {
        let trades = self.trades.columns();
        TbboColumns {
            ts_recv: trades.ts_recv,
            price: trades.price,
            size: trades.size,
            bid: &self.bid,
            ask: &self.ask,
            bid_size: &self.bid_size,
            ask_size: &self.ask_size,
        }
    }
}

#[derive(Debug, Clone)]
struct BarTable {
    ts_open: Vec<Ts>,
    ts_close: Vec<Ts>,
    open: Vec<Price>,
    high: Vec<Price>,
    low: Vec<Price>,
    close: Vec<Price>,
    volume: Vec<Qty>,
}

impl BarTable {
    fn of(rows: &[BarRow]) -> Self {
        Self {
            ts_open: rows.iter().map(|row| row.ts_open).collect(),
            ts_close: rows.iter().map(|row| row.ts_close).collect(),
            open: rows.iter().map(|row| row.open).collect(),
            high: rows.iter().map(|row| row.high).collect(),
            low: rows.iter().map(|row| row.low).collect(),
            close: rows.iter().map(|row| row.close).collect(),
            volume: rows.iter().map(|row| row.volume).collect(),
        }
    }

    fn columns(&self) -> BarColumns<'_> {
        BarColumns {
            ts_open: &self.ts_open,
            ts_close: &self.ts_close,
            open: &self.open,
            high: &self.high,
            low: &self.low,
            close: &self.close,
            volume: &self.volume,
        }
    }
}
