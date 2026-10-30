//! Orders as the engine places them (`docs/spec/fill-semantics.md` §2, F-ACT-01, F-OCO-01,
//! F-SES-01): market, stop-market, and limit orders with their side, lots, time in force,
//! activation, and OCO group, as `fefat.reference.orders` holds them. The book that moves orders
//! from one state to the next is the loop's (step 2.6).

use std::fmt;
use std::num::NonZeroU32;
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use thiserror::Error;

use crate::instants::Ts;
use crate::rolls::RollReason;
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

    /// The price further in the favour of a position this side opened: the higher for a long,
    /// the lower for a short.
    pub fn better(self, first: Price, second: Price) -> Price {
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

/// What an order does for a position, which its fill records (F-TAG-01): open it, protect it (an
/// exit plan's stop), take its profit (one of the plan's targets), close it at the market on the
/// strategy's word, for a reason, or carry it across a roll, a leg of the roll (F-ROL-02). Roles
/// order as they are declared, which is the order a run's breakdowns list them in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OrderRole {
    /// Opens or adds to a position.
    Entry,
    /// An exit plan's stop, or a bracket's.
    Stop,
    /// An exit plan's target, or a bracket's, the first.
    Target(TargetNumber),
    /// Closes the position at the market on the strategy's word.
    Exit(ExitReason),
    /// A leg of a roll for this reason, which closes the position on the contract rolled from or
    /// opens it on the new front.
    Roll(RollReason),
}

/// Which of an exit plan's three targets (F-PLN-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TargetNumber {
    /// Target 1.
    First,
    /// Target 2.
    Second,
    /// Target 3.
    Third,
}

impl OrderRole {
    /// Every role, in their order.
    pub const ALL: [Self; 17] = [
        Self::Entry,
        Self::Stop,
        Self::Target(TargetNumber::First),
        Self::Target(TargetNumber::Second),
        Self::Target(TargetNumber::Third),
        Self::Exit(ExitReason::Strategy),
        Self::Exit(ExitReason::FlatBy),
        Self::Exit(ExitReason::NoOvernight),
        Self::Exit(ExitReason::NoWeekend),
        Self::Exit(ExitReason::MaxBars),
        Self::Exit(ExitReason::MaxMinutes),
        Self::Exit(ExitReason::OppositeSignal),
        Self::Exit(ExitReason::SignalExit),
        Self::Roll(RollReason::Volume),
        Self::Roll(RollReason::OpenInterest),
        Self::Roll(RollReason::Calendar),
        Self::Roll(RollReason::Expiry),
    ];
}

/// Text that spells no order role.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("Expected an order role as a fill records it, such as stop or target_1, got {text:?}")]
pub struct UnreadableOrderRole {
    /// The text given.
    pub text: String,
}

/// A role as it displays, `stop` or `roll_open_interest`, the inverse of its `Display`.
impl FromStr for OrderRole {
    type Err = UnreadableOrderRole;

    fn from_str(text: &str) -> Result<Self, Self::Err> {
        let known = Self::ALL.into_iter().find(|role| role.to_string() == text);
        known.ok_or_else(|| UnreadableOrderRole {
            text: text.to_owned(),
        })
    }
}

/// A role serializes as its text, as the fills and the trades artifacts write it.
impl Serialize for OrderRole {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for OrderRole {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        text.parse().map_err(serde::de::Error::custom)
    }
}

impl TargetNumber {
    /// The targets in order.
    pub const ALL: [Self; 3] = [Self::First, Self::Second, Self::Third];

    /// The target's number, from 1.
    pub const fn number(self) -> u8 {
        match self {
            Self::First => 1,
            Self::Second => 2,
            Self::Third => 3,
        }
    }
}

/// Why a market order closes the position (`docs/spec/fill-semantics.md` §20): the strategy's own
/// word, outside an execution template, or one of the template's time rules or signals.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExitReason {
    /// A strategy's own exit, outside the template.
    Strategy,
    /// The flat-by time (F-TIM-01).
    FlatBy,
    /// A stop of trading (F-TIM-03).
    NoOvernight,
    /// A stop of trading over a weekend (F-TIM-03).
    NoWeekend,
    /// The bars a position may stay open (F-TIM-02).
    MaxBars,
    /// The minutes a position may stay open (F-TIM-02).
    MaxMinutes,
    /// An entry signal against the position (F-ENT-04).
    OppositeSignal,
    /// `long_exit` or `short_exit` (F-ENT-04).
    SignalExit,
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

/// The words of `fefat.reference.orders`, which the event log and the run's artifacts write.
impl fmt::Display for Side {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Buy => "buy",
            Self::Sell => "sell",
        })
    }
}

/// The order's class, `market`, `stop`, or `limit`, as a scenario writes its `kind`.
impl fmt::Display for OrderKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Market => "market",
            Self::StopMarket { .. } => "stop",
            Self::Limit { .. } => "limit",
        })
    }
}

/// The role as a fill records it: `entry`, `stop`, `target_1` to `target_3`, an exit's reason,
/// `exit` for a strategy's own, or a roll's leg's, `roll_` and the roll's reason, such as
/// `roll_open_interest`.
impl fmt::Display for OrderRole {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Entry => formatter.write_str("entry"),
            Self::Stop => formatter.write_str("stop"),
            Self::Target(target) => write!(formatter, "target_{}", target.number()),
            Self::Roll(reason) => write!(formatter, "roll_{}", reason.word().replace('-', "_")),
            Self::Exit(reason) => formatter.write_str(match reason {
                ExitReason::Strategy => "exit",
                ExitReason::FlatBy => "flat_by",
                ExitReason::NoOvernight => "no_overnight",
                ExitReason::NoWeekend => "no_weekend",
                ExitReason::MaxBars => "max_bars",
                ExitReason::MaxMinutes => "max_minutes",
                ExitReason::OppositeSignal => "opposite_signal",
                ExitReason::SignalExit => "signal_exit",
            }),
        }
    }
}

impl fmt::Display for OrderState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Waiting => "waiting",
            Self::Working => "working",
            Self::Triggered => "triggered",
            Self::Filled => "filled",
            Self::Cancelled => "cancelled",
        })
    }
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
    fn every_role_reads_back_from_its_text() {
        for role in OrderRole::ALL {
            assert_eq!(role.to_string().parse(), Ok(role));
        }
        let texts: Vec<String> = OrderRole::ALL.iter().map(ToString::to_string).collect();
        assert_eq!(texts.first().map(String::as_str), Some("entry"));
        assert_eq!(texts.get(4).map(String::as_str), Some("target_3"));
        assert_eq!(texts.last().map(String::as_str), Some("roll_expiry"));
        assert!(OrderRole::ALL.windows(2).all(|pair| pair[0] < pair[1]));
        let unknown = "take_profit".parse::<OrderRole>().unwrap_err();
        assert_eq!(
            unknown.to_string(),
            "Expected an order role as a fill records it, such as stop or target_1, got \"take_profit\""
        );
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
