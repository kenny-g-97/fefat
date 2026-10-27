//! What a fill records (F-TAG-01): the order, when and at what price it filled, the rule that
//! priced it, the fidelity of the data it filled on, its liquidity, its slippage in ticks, its
//! flags, and its fee, as `fefat.reference.ledger.Fill` holds them. The money its value moves is
//! what [`crate::ledger::Ledger::book`] returns.

use std::fmt;

use crate::fidelity::Fidelity;
use crate::instants::Ts;
use crate::orders::{OrderId, OrderRole, Side};
use crate::units::{Money, Price, Qty};

/// The rule of `docs/spec/fill-semantics.md` that priced a fill, one of those F-TAG-01 names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PricingRule {
    /// F-MKT-01: a market order at the quote of the first TBBO record it sees.
    MarketAtQuote,
    /// F-MKT-02: a market order at the price of the first trade it sees.
    MarketAtTrade,
    /// F-MKT-03: a market order at the open of the first bar it sees.
    MarketAtBarOpen,
    /// F-STP-02: a triggered stop at the next tradeable TBBO record's quote.
    StopAtNextQuote,
    /// F-STP-03: a stop on trades, at the worse of its price plus the ticks and the trigger's.
    StopOnTrades,
    /// F-STP-04: a stop on bars, at its price plus the ticks, or the open past it.
    StopOnBars,
    /// F-STP-05: a stop at or through the market when it became active, filled as a market order.
    StopThroughMarket,
    /// F-LMT-03: a limit at its own price, never better.
    LimitAtItsPrice,
}

impl PricingRule {
    /// The rule's identifier in the specification, such as `F-MKT-01`.
    pub const fn id(self) -> &'static str {
        match self {
            Self::MarketAtQuote => "F-MKT-01",
            Self::MarketAtTrade => "F-MKT-02",
            Self::MarketAtBarOpen => "F-MKT-03",
            Self::StopAtNextQuote => "F-STP-02",
            Self::StopOnTrades => "F-STP-03",
            Self::StopOnBars => "F-STP-04",
            Self::StopThroughMarket => "F-STP-05",
            Self::LimitAtItsPrice => "F-LMT-03",
        }
    }
}

impl fmt::Display for PricingRule {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.id())
    }
}

/// Whether a fill rested on the book or took liquidity (F-LMT-04).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Liquidity {
    /// A limit that rested before it filled.
    Maker,
    /// A market or stop fill, or a limit filled on the first price it saw.
    Taker,
}

impl fmt::Display for Liquidity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Maker => "maker",
            Self::Taker => "taker",
        })
    }
}

/// What a fill is flagged with.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct FillFlags {
    /// Its bar's fills depend on the order of the bar's extremes (F-BAR-05).
    pub ambiguous: bool,
    /// Its lots exceed the size its record shows (F-QTY-01).
    pub size_exceeded: bool,
}

/// One fill, as F-TAG-01 has it recorded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Fill {
    /// The order that filled.
    pub order: OrderId,
    /// What the order did for the position.
    pub role: OrderRole,
    /// Buy or sell.
    pub side: Side,
    /// The lots filled, the order's whole quantity.
    pub lots: Qty,
    /// When: a record's `ts_recv`, or a bar's `ts_close` (F-BAR-06).
    pub ts: Ts,
    /// The price it filled at.
    pub price: Price,
    /// The rule that priced it.
    pub rule: PricingRule,
    /// The fidelity of the data it filled on.
    pub fidelity: Fidelity,
    /// Maker or taker.
    pub liquidity: Liquidity,
    /// How many ticks worse than its reference price it is (F-TAG-01).
    pub slippage_ticks: i64,
    /// Its flags.
    pub flags: FillFlags,
    /// The fee the trader pays for it, already rounded against the trader (F-FEE-03): negative
    /// for a maker rebate, which a crypto fee table may give (F-FEE-02).
    pub fee: Money,
}
