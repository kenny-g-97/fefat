//! The units the loop reads, one trade date's records of the finest level it fills on: a trade
//! print, with its quote on TBBO, or a stored bar.

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::Ts;
use fefat_core::market_data::{BarColumns, BarRow, TbboColumns, TradeColumns};
use fefat_core::orders::Side;
use fefat_core::units::{Price, Qty};

/// A TBBO record's quote: the best bid and ask just before its trade, with their sizes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Quote {
    /// The best bid.
    pub bid: Price,
    /// The best ask.
    pub ask: Price,
    /// The lots bid.
    pub bid_size: Qty,
    /// The lots offered.
    pub ask_size: Qty,
}

impl Quote {
    /// The quote an order of `side` takes, the ask for a buy, and its size.
    pub(super) const fn of(self, side: Side) -> (Price, Qty) {
        match side {
            Side::Buy => (self.ask, self.ask_size),
            Side::Sell => (self.bid, self.bid_size),
        }
    }
}

/// One record of the tick level: a trade print, with its quote on TBBO.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickRecord {
    /// When it was received (F-CLK-01).
    pub ts: Ts,
    /// The trade's price.
    pub price: Price,
    /// The trade's size in lots.
    pub size: Qty,
    /// The quote, on TBBO.
    pub quote: Option<Quote>,
}

impl TickRecord {
    /// On TBBO, the quote an order of `side` takes and its size, read no better than the trade
    /// (F-SLP-01): the later prints of a sweep carry the quote from before the sweep, so an ask
    /// below the trade counts as that trade, its price and its size, as does a bid above it.
    pub(super) fn quoted(&self, side: Side) -> Option<(Price, Qty)> {
        let (quoted, size) = self.quote?.of(side);
        if side.worse(quoted, self.price) == quoted {
            return Some((quoted, size));
        }
        Some((self.price, self.size))
    }
}

/// One unit of the finest level a trade date is filled on: a tick, or a stored bar.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Unit {
    /// A trade print, with its quote on TBBO.
    Tick(TickRecord),
    /// A stored bar, replayed as its pseudo-ticks (F-BAR-01).
    Bar(BarRow),
}

impl Unit {
    /// When it becomes available, the loop's clock (F-CLK-01): a tick's `ts_recv`, a bar's
    /// `ts_close`.
    pub const fn ts(&self) -> Ts {
        match self {
            Self::Tick(record) => record.ts,
            Self::Bar(bar) => bar.ts_close,
        }
    }

    /// The last price it shows, which marks the position (F-MRK-01): a tick's trade, a bar's
    /// close.
    pub const fn last_price(&self) -> Price {
        match self {
            Self::Tick(record) => record.price,
            Self::Bar(bar) => bar.close,
        }
    }
}

/// One trade date's records of the level the run fills on, as the reader serves them.
pub(super) enum DayRecords<'run> {
    Trades(TradeColumns<'run>),
    Tbbo(TbboColumns<'run>),
    Bars(BarColumns<'run>, Timeframe),
}

impl<'run> DayRecords<'run> {
    pub(super) fn get(&self, index: usize) -> Option<Unit> {
        match self {
            Self::Trades(trades) => Some(Unit::Tick(TickRecord {
                ts: *trades.ts_recv.get(index)?,
                price: *trades.price.get(index)?,
                size: *trades.size.get(index)?,
                quote: None,
            })),
            Self::Tbbo(tbbo) => Some(Unit::Tick(TickRecord {
                ts: *tbbo.ts_recv.get(index)?,
                price: *tbbo.price.get(index)?,
                size: *tbbo.size.get(index)?,
                quote: Some(Quote {
                    bid: *tbbo.bid.get(index)?,
                    ask: *tbbo.ask.get(index)?,
                    bid_size: *tbbo.bid_size.get(index)?,
                    ask_size: *tbbo.ask_size.get(index)?,
                }),
            })),
            Self::Bars(bars, _) => bar_row(bars, index).map(Unit::Bar),
        }
    }

    /// The fidelity of the records, which their fills record (F-TAG-01).
    pub(super) const fn fidelity(&self) -> Fidelity {
        match self {
            Self::Trades(_) => Fidelity::Trades,
            Self::Tbbo(_) => Fidelity::Tbbo,
            Self::Bars(_, timeframe) => Fidelity::Bars(*timeframe),
        }
    }

    /// When each record becomes available, in their order: a tick's `ts_recv`, a bar's
    /// `ts_close` (F-CLK-01).
    pub(super) const fn instants(&self) -> &'run [Ts] {
        match self {
            Self::Trades(trades) => trades.ts_recv,
            Self::Tbbo(tbbo) => tbbo.ts_recv,
            Self::Bars(bars, _) => bars.ts_close,
        }
    }

    /// Whether the records are bars, which an order sees from the first closing after its
    /// activation (F-ACT-02), rather than ticks, seen from the first at or after it (F-ACT-01).
    pub(super) const fn are_bars(&self) -> bool {
        matches!(self, Self::Bars(..))
    }
}

/// Bar `index` of `bars`, or none past the last.
pub(super) fn bar_row(bars: &BarColumns<'_>, index: usize) -> Option<BarRow> {
    Some(BarRow {
        ts_open: *bars.ts_open.get(index)?,
        ts_close: *bars.ts_close.get(index)?,
        open: *bars.open.get(index)?,
        high: *bars.high.get(index)?,
        low: *bars.low.get(index)?,
        close: *bars.close.get(index)?,
        volume: *bars.volume.get(index)?,
    })
}
