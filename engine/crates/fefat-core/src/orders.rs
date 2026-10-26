//! Orders as the engine places them (`docs/spec/fill-semantics.md` §2, F-ACT-01, F-OCO-01,
//! F-SES-01): market, stop-market, and limit orders with their side, lots, time in force,
//! activation, and OCO group, as `fefat.reference.orders` holds them. The book that moves orders
//! from one state to the next is the loop's (step 2.6).

use std::num::NonZeroU32;

use crate::instants::Ts;
use crate::units::{Overflow, Price, Qty};

/// An order's identity within a run; among orders placed at one instant, the lower id comes first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OrderId(pub u64);

/// An OCO group: of its orders one at most fills, and the first fill cancels the others
/// (F-OCO-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OcoGroupId(pub u64);

/// An order's side. Each rule of the specification is written for a buy, and a sell mirrors it
/// (`fill-semantics.md` §1).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Side {
    /// Opens or adds to a long; reduces, closes, or reverses a short.
    Buy,
    /// Opens or adds to a short; reduces, closes, or reverses a long.
    Sell,
}

impl Side {
    /// 1 for a buy and -1 for a sell: the sign of the lots a fill adds to the position.
    pub const fn sign(self) -> i64 {
        match self {
            Self::Buy => 1,
            Self::Sell => -1,
        }
    }

    /// The other side.
    pub const fn opposite(self) -> Self {
        match self {
            Self::Buy => Self::Sell,
            Self::Sell => Self::Buy,
        }
    }

    /// `price` moved `ticks` ticks of `tick` against the trader, up for a buy and down for a sell
    /// (F-SLP-01), or [`Overflow`] when it leaves 64 bits.
    pub fn moved(self, price: Price, ticks: u32, tick: Price) -> Result<Price, Overflow> {
        let distance = tick.0.checked_mul(i64::from(ticks)).ok_or(Overflow {
            operation: "a distance in ticks",
            left: tick.0.into(),
            right: ticks.into(),
        })?;
        match self {
            Self::Buy => price.checked_add(Price(distance)),
            Self::Sell => price.checked_sub(Price(distance)),
        }
    }

    /// The costlier of two prices for this side: the higher for a buy, the lower for a sell.
    pub fn worse(self, first: Price, second: Price) -> Price {
        match self {
            Self::Buy => first.max(second),
            Self::Sell => first.min(second),
        }
    }
}

/// An order's class, with the price it names (`fill-semantics.md` §2): a market order names none.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderKind {
    /// At the market (F-MKT).
    Market,
    /// A stop-market order, a market order once the market trades at or through `stop` (F-STP).
    StopMarket {
        /// The stop's trigger price.
        stop: Price,
    },
    /// A limit order, filled at `limit` when the market trades through it (F-LMT).
    Limit {
        /// The limit price.
        limit: Price,
    },
}

/// What an order does for a position: open it, protect it (a bracket's stop), take its profit (a
/// bracket's target), or close it when the strategy says so.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum OrderRole {
    /// Opens or adds to a position.
    Entry,
    /// A bracket's stop.
    Stop,
    /// A bracket's target.
    Target,
    /// Closes the position on the strategy's word: a signal exit or a time rule.
    Exit,
}

/// How long an order works.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeInForce {
    /// Until it fills, an order of its OCO group fills, or its strategy cancels it, through
    /// breaks, halts, and weekends (F-SES-01).
    GoodTillCancelled,
    /// For this many signal bars, then cancelled: a resting entry's `time_to_live_bars` (`02`
    /// §2.1, from step 2.8).
    Bars(NonZeroU32),
}

/// An order as a decision places it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Order {
    /// Its identity within the run.
    pub id: OrderId,
    /// Buy or sell.
    pub side: Side,
    /// How many lots, one or more; orders fill whole (F-QTY-01).
    pub lots: Qty,
    /// Market, stop-market, or limit, with its price.
    pub kind: OrderKind,
    /// What it does for the position.
    pub role: OrderRole,
    /// How long it works.
    pub time_in_force: TimeInForce,
    /// The decision's instant, a bar close, or the fill that placed a bracket's leg.
    pub placed_at: Ts,
    /// The instant from which it can fill: the decision's close plus the run's latency
    /// (F-ACT-01), or its entry's fill for a bracket's leg, which takes no latency (F-OCO-02).
    pub activation: Ts,
    /// The OCO group it belongs to, if any.
    pub oco: Option<OcoGroupId>,
}

/// Where an order stands: placed and waiting for the first record or bar it sees (F-ACT-01,
/// F-ACT-02), working, triggered (a stop on TBBO, which fills at the next record's quote,
/// F-STP-02), filled, or cancelled.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum OrderState {
    /// Placed, not yet active.
    Waiting,
    /// Active, and able to fill.
    Working,
    /// A stop on TBBO that a trade triggered, filled at the next tradeable record's quote.
    Triggered,
    /// Filled whole.
    Filled,
    /// Cancelled by an OCO fill, a time rule, or its strategy.
    Cancelled,
}

#[cfg(test)]
mod tests {
    use super::*;

    const TICK: Price = Price(250_000_000);

    #[test]
    fn a_buy_moves_up_and_a_sell_down_and_each_takes_its_costlier_price() {
        let price = Price(4_995_000_000_000);
        assert_eq!(
            Side::Buy.moved(price, 1, TICK),
            Ok(Price(4_995_250_000_000))
        );
        assert_eq!(
            Side::Sell.moved(price, 2, TICK),
            Ok(Price(4_994_500_000_000))
        );
        assert_eq!(Side::Sell.moved(price, 0, TICK), Ok(price));
        assert_eq!(Side::Buy.worse(price, Price(1)), price);
        assert_eq!(Side::Sell.worse(price, Price(1)), Price(1));
    }

    #[test]
    fn a_move_beyond_64_bits_is_an_error_not_a_wrap() {
        assert!(Side::Buy.moved(Price(i64::MAX), 1, TICK).is_err());
        assert!(
            Side::Sell
                .moved(Price(0), u32::MAX, Price(i64::MAX))
                .is_err()
        );
    }
}
