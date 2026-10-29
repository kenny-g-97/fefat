//! Rolls of a future's front (`docs/spec/fill-semantics.md` §29, D-44), as the roll calendar
//! gives them (`fefat.market.continuous.RollCalendar.rolls()`): at a session's open the front
//! passes from one contract to the next, whose closes in the latest bar both traded in before
//! that session differ by the gap, for a reason. The engine takes them as given and never works
//! them out again (F-ROL-01).

use crate::instants::Ts;
use crate::instrument::Contract;
use crate::units::Price;

/// Why the front passed to a new contract (D-44): its rule's leader, or its last trade date.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RollReason {
    /// The contract with the most volume in the session before.
    Volume,
    /// The contract with the most open interest by the open.
    OpenInterest,
    /// A set number of sessions before the last trade date.
    Calendar,
    /// The contract rolled from stops trading in the session.
    Expiry,
}

impl RollReason {
    /// The word the roll calendar writes, such as `open-interest`.
    pub const fn word(self) -> &'static str {
        match self {
            Self::Volume => "volume",
            Self::OpenInterest => "open-interest",
            Self::Calendar => "calendar",
            Self::Expiry => "expiry",
        }
    }
}

/// A roll: at `session_open` the front passes from `rolled_from` to `contract`, whose close in
/// the latest bar both traded in before that session is `gap` above the old one's, for `reason`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Roll {
    /// The open of the session the new front serves from.
    pub session_open: Ts,
    /// The contract rolled from.
    pub rolled_from: Contract,
    /// The new front.
    pub contract: Contract,
    /// The new contract's close less the old one's, in 1e-9 units of price.
    pub gap: Price,
    /// Why.
    pub reason: RollReason,
}
