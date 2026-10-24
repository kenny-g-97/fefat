//! The ledger of one run (F-MRK-01, F-FEE-03): its cash, its position, and the mark the position
//! is valued at. Equity is worked out from them, cash plus the position's value at the mark, and
//! never stored. A fill moves the cash by its value, the other way, and by its fee, each booked
//! once and rounded toward minus infinity of the trader's cash, as `fefat.reference.engine` books
//! them; the mark moves when the loop marks it, never at a fill.

use std::cmp::Ordering;
use std::fmt;

use thiserror::Error;

use crate::fills::Fill;
use crate::instrument::InstrumentParameters;
use crate::orders::Side;
use crate::units::{Money, Overflow, Price, Qty};

#[cfg(test)]
mod tests;

/// A position: flat, or long or short a number of lots above zero.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Position {
    /// No lots held.
    Flat,
    /// Lots bought and not yet sold.
    Long(Qty),
    /// Lots sold and not yet bought back.
    Short(Qty),
}

impl Position {
    /// The lots held, positive long and negative short.
    pub const fn signed_lots(self) -> Qty {
        match self {
            Self::Flat => Qty(0),
            Self::Long(lots) => lots,
            Self::Short(lots) => Qty(-lots.0),
        }
    }

    /// The position once `lots` more are bought or sold: a buy adds to a long and reduces,
    /// closes, or reverses a short, crossing flat (S-fill-042).
    pub fn after(self, side: Side, lots: Qty) -> Result<Self, LedgerError> {
        if lots.0 <= 0 {
            return Err(LedgerError::NonPositiveLots { lots });
        }
        let held = self.signed_lots().checked_add(Qty(side.sign() * lots.0))?;
        match held.0.cmp(&0) {
            Ordering::Greater => Ok(Self::Long(held)),
            Ordering::Equal => Ok(Self::Flat),
            Ordering::Less => Ok(Self::Short(Qty(0).checked_sub(held)?)),
        }
    }
}

impl fmt::Display for Position {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Flat => formatter.write_str("flat"),
            Self::Long(lots) => write!(formatter, "long {lots} lots"),
            Self::Short(lots) => write!(formatter, "short {lots} lots"),
        }
    }
}

/// Why the ledger refused a booking or a valuation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum LedgerError {
    /// A fill of no lots, or of fewer than none.
    #[error("Expected a fill of one lot or more, got {lots} lots")]
    NonPositiveLots {
        /// The lots the fill named.
        lots: Qty,
    },
    /// An open position without a price to value it at.
    #[error(
        "Expected a mark to value the position ({position}) at, got none: no tradeable price \
         has been seen (F-MRK-01)"
    )]
    UnmarkedPosition {
        /// The position held.
        position: Position,
    },
    /// An amount beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
}

/// What one run holds: its cash, its position, and the mark (module documentation).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ledger {
    instrument: InstrumentParameters,
    cash: Money,
    position: Position,
    mark: Option<Price>,
}

impl Ledger {
    /// A flat ledger of `instrument` holding `starting_cash`, the run's `capital` (50,000 USD by
    /// default, D-51), with no mark yet.
    pub const fn new(instrument: InstrumentParameters, starting_cash: Money) -> Self {
        Self {
            instrument,
            cash: starting_cash,
            position: Position::Flat,
            mark: None,
        }
    }

    /// Books `fill`: the position moves by its lots, the cash by its value, the other way, and by
    /// its fee, each rounded once (F-FEE-03), and the mark stays (F-MRK-01). Returns what the
    /// fill's value moved the cash by, the reference engine's `Fill.cash`. A fill the ledger
    /// refuses leaves it as it was.
    pub fn book(&mut self, fill: &Fill) -> Result<Money, LedgerError> {
        let position = self.position.after(fill.side, fill.lots)?;
        let sold = Qty(-fill.side.sign() * fill.lots.0);
        let cash_moved = self.instrument.value(fill.price, sold)?;
        let cash = self.cash.checked_add(cash_moved)?.checked_sub(fill.fee)?;
        #[cfg(debug_assertions)]
        let before = self.clone();
        self.position = position;
        self.cash = cash;
        #[cfg(debug_assertions)]
        self.check_booking(&before, fill);
        Ok(cash_moved)
    }

    /// Marks the position at `price`, the last tradeable price seen (F-MRK-01).
    pub fn mark_at(&mut self, price: Price) {
        self.mark = Some(price);
    }

    /// The cash, in micro-units.
    pub const fn cash(&self) -> Money {
        self.cash
    }

    /// The position.
    pub const fn position(&self) -> Position {
        self.position
    }

    /// The mark, none before the first tradeable price.
    pub const fn mark(&self) -> Option<Price> {
        self.mark
    }

    /// The position's value at the mark, rounded once (F-FEE-03): zero when flat, negative for a
    /// short.
    pub fn position_value(&self) -> Result<Money, LedgerError> {
        match (self.position, self.mark) {
            (Position::Flat, _) => Ok(Money(0)),
            (position, Some(mark)) => Ok(self.instrument.value(mark, position.signed_lots())?),
            (position, None) => Err(LedgerError::UnmarkedPosition { position }),
        }
    }

    /// Cash plus the position's value at the mark (F-MRK-01).
    pub fn equity(&self) -> Result<Money, LedgerError> {
        Ok(self.cash.checked_add(self.position_value()?)?)
    }

    /// Debug builds hold every booking to the accounting identity: a fill moves equity by its fee
    /// and by the mark's distance from its price over the lots it adds, exactly but for the three
    /// amounts each rounded once, the cash the fill moved and the position's value before and
    /// after, so the move lies within two micro-units below and one above the exact one.
    #[cfg(debug_assertions)]
    fn check_booking(&self, before: &Self, fill: &Fill) {
        let (Some(mark), Ok(start), Ok(end)) = (self.mark, before.equity(), self.equity()) else {
            return;
        };
        let units = i128::from(crate::units::PRICE_UNITS);
        let added = i128::from(fill.side.sign()) * i128::from(fill.lots.0);
        let exact = (i128::from(mark.0) - i128::from(fill.price.0))
            .checked_mul(added)
            .and_then(|gap| gap.checked_mul(i128::from(self.instrument.money_per_point().0)))
            .and_then(|gap| gap.checked_sub(i128::from(fill.fee.0) * units));
        let booked = (i128::from(end.0) - i128::from(start.0)) * units;
        if let Some(rounding) = exact.and_then(|exact| booked.checked_sub(exact)) {
            debug_assert!(
                -2 * units < rounding && rounding < units,
                "Expected booking {fill:?} to move equity from {start} by its fee and the mark's \
                 distance from its price, got {end}"
            );
        }
    }
}
