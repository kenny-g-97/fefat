//! The records the tick loop reads: a trade print, with its quote on TBBO, from one trade date's
//! columns of the run's level, `tbbo` or `trades`.

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::Ts;
use fefat_core::market_data::{TbboColumns, TradeColumns};
use fefat_core::orders::Side;
use fefat_core::units::{Price, Qty};

use super::RunError;

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

/// The tick level a run reads: TBBO records or trade prints; bars are step 2.7's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TickFidelity {
    /// Trades, each with the best bid and ask just before it.
    Tbbo,
    /// Trade prints alone.
    Trades,
}

impl TickFidelity {
    /// The fidelity its fills record (F-TAG-01).
    pub const fn fidelity(self) -> Fidelity {
        match self {
            Self::Tbbo => Fidelity::Tbbo,
            Self::Trades => Fidelity::Trades,
        }
    }
}

impl TryFrom<Fidelity> for TickFidelity {
    type Error = RunError;

    /// The tick level `fidelity` names, bars refused until step 2.7 replays them.
    fn try_from(fidelity: Fidelity) -> Result<Self, RunError> {
        match fidelity {
            Fidelity::Tbbo => Ok(Self::Tbbo),
            Fidelity::Trades => Ok(Self::Trades),
            Fidelity::Bars(_) => Err(RunError::BarFidelity { fidelity }),
        }
    }
}

/// One trade date's records of the run's level, as the reader serves them.
pub(super) enum DayRecords<'run> {
    Trades(TradeColumns<'run>),
    Tbbo(TbboColumns<'run>),
}

impl DayRecords<'_> {
    pub(super) fn get(&self, index: usize) -> Option<TickRecord> {
        match self {
            Self::Trades(trades) => Some(TickRecord {
                ts: *trades.ts_recv.get(index)?,
                price: *trades.price.get(index)?,
                size: *trades.size.get(index)?,
                quote: None,
            }),
            Self::Tbbo(tbbo) => Some(TickRecord {
                ts: *tbbo.ts_recv.get(index)?,
                price: *tbbo.price.get(index)?,
                size: *tbbo.size.get(index)?,
                quote: Some(Quote {
                    bid: *tbbo.bid.get(index)?,
                    ask: *tbbo.ask.get(index)?,
                    bid_size: *tbbo.bid_size.get(index)?,
                    ask_size: *tbbo.ask_size.get(index)?,
                }),
            }),
        }
    }
}
