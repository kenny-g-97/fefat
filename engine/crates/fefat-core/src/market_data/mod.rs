//! The engine's port to market data (`08-code-design.md` §1, `02` §1.6 and §4): the trade dates
//! one contract has, the levels each date holds, the columns of its bars, trades, and TBBO
//! records, and the offsets that take a bar down to its finer rows. Step 2.5's cache reader
//! implements it over memory-mapped files and [`InMemoryMarketData`] over a tape held in memory;
//! [`conformance`] holds the checks both pass.

pub mod conformance;
mod descent;
mod in_memory;
mod tape;
#[cfg(test)]
mod tests;

use thiserror::Error;

pub use in_memory::InMemoryMarketData;
pub use tape::{BarRow, TapeDay, TapeError, TbboRow, TradeRow};

use crate::fidelity::{Fidelity, Timeframe};
use crate::instants::{TradeDate, Ts};
use crate::instrument::Contract;
use crate::units::{Price, Qty};

/// One trade date's stored bars of one timeframe, in time order, as columns of one length.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BarColumns<'a> {
    /// The instant each bar opens.
    pub ts_open: &'a [Ts],
    /// The instant each bar closes and becomes available (F-CLK-01).
    pub ts_close: &'a [Ts],
    /// Each bar's first price.
    pub open: &'a [Price],
    /// Each bar's highest price.
    pub high: &'a [Price],
    /// Each bar's lowest price.
    pub low: &'a [Price],
    /// Each bar's last price.
    pub close: &'a [Price],
    /// The lots each bar traded, one or more (F-BAR-07).
    pub volume: &'a [Qty],
}

/// One trade date's trade prints, by `ts_recv` and, at one instant, in the vendor's order
/// (F-CLK-01, F-CLK-03), as columns of one length.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TradeColumns<'a> {
    /// The instant each trade was received, the engine's clock.
    pub ts_recv: &'a [Ts],
    /// Each trade's price.
    pub price: &'a [Price],
    /// Each trade's size in lots.
    pub size: &'a [Qty],
}

/// One trade date's TBBO records, each a trade with the best bid and ask just before it, in the
/// order of trades, as columns of one length.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TbboColumns<'a> {
    /// The instant each record was received, the engine's clock.
    pub ts_recv: &'a [Ts],
    /// Each trade's price.
    pub price: &'a [Price],
    /// Each trade's size in lots.
    pub size: &'a [Qty],
    /// The best bid before each trade.
    pub bid: &'a [Price],
    /// The best ask before each trade.
    pub ask: &'a [Price],
    /// The lots bid at the best bid (F-QTY-01).
    pub bid_size: &'a [Qty],
    /// The lots offered at the best ask (F-QTY-01).
    pub ask_size: &'a [Qty],
}

/// The engine's port to one contract's market data.
pub trait MarketDataReader {
    /// The contract whose data this reader serves.
    fn contract(&self) -> &Contract;

    /// The trade dates it has data for, ascending, never none.
    fn trade_dates(&self) -> &[TradeDate];

    /// The levels a trade date holds, finest first: TBBO, trades, then bars from the shortest
    /// timeframe up; a date with an import's coarser bars alone has that one level (D-49).
    fn levels(&self, trade_date: TradeDate) -> Result<&[Fidelity], MarketDataError>;

    /// A trade date's bars of `timeframe`.
    fn bars(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
    ) -> Result<BarColumns<'_>, MarketDataError>;

    /// A trade date's trade prints.
    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError>;

    /// A trade date's TBBO records.
    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError>;

    /// Where each bar of `timeframe` starts among the rows of the `finer` level on `trade_date`:
    /// entry `i` counts the finer rows before bar `i` opens (a tick by its `ts_recv`, a bar by its
    /// `ts_open`), and one more entry, the finer rows' count, closes the last bar's range, so that
    /// bar `i` descends to rows `offsets[i]..offsets[i + 1]` (step 2.7).
    fn offsets(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
        finer: Fidelity,
    ) -> Result<&[u32], MarketDataError>;
}

/// What a reader could not serve.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum MarketDataError {
    /// A trade date the reader has no data for.
    #[error("Expected a trade date of {contract} from {first} to {last}, got {trade_date}")]
    UnknownTradeDate {
        /// The reader's contract.
        contract: Contract,
        /// The date asked for.
        trade_date: TradeDate,
        /// The reader's first trade date.
        first: TradeDate,
        /// The reader's last trade date.
        last: TradeDate,
    },
    /// A level the trade date does not hold.
    #[error("Expected {level} data of {contract} on {trade_date}, which holds {}", listed(.present))]
    LevelMissing {
        /// The reader's contract.
        contract: Contract,
        /// The date asked for.
        trade_date: TradeDate,
        /// The level asked for.
        level: Fidelity,
        /// The levels the date holds, finest first.
        present: Vec<Fidelity>,
    },
    /// Offsets asked from bars to a level that is not finer than them.
    #[error("Expected a level finer than {timeframe} bars to descend to, got {finer}")]
    NotFiner {
        /// The bars descended from.
        timeframe: Timeframe,
        /// The level asked for.
        finer: Fidelity,
    },
}

fn listed(levels: &[Fidelity]) -> String {
    let names: Vec<String> = levels.iter().map(ToString::to_string).collect();
    names.join(", ")
}
