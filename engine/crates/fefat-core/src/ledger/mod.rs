//! The ledger of one run (F-MRK-01, F-FEE-03): its cash, its position, and the mark the position
//! is valued at. Equity is worked out from them, cash plus the position's value at the mark, and
//! never stored. A fill moves the cash by its value, the other way, and by its fee, each booked
//! once and rounded toward minus infinity of the trader's cash, as `fefat.reference.engine` books
//! them, and a funding time by its payment (F-FND-01); the mark moves when the loop marks it,
//! never at a fill, and with a roll's gap (F-ROL-03).

use std::cmp::Ordering;
use std::fmt;

use thiserror::Error;

use crate::costs::{Rate, funding_change};
use crate::fills::Fill;
use crate::instants::Ts;
use crate::instrument::InstrumentParameters;
use crate::orders::Side;
use crate::units::{Money, Overflow, Price, Qty};

#[cfg(test)]
mod tests;

/// A position: flat, or long or short the lots it holds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Position {
    /// No lots held.
    Flat,
    /// Lots bought and not yet sold.
    Long(HeldLots),
    /// Lots sold and not yet bought back.
    Short(HeldLots),
}

/// The lots a long or a short holds, one or more: only [`Position::after`] makes them, so that no
/// position is open with no lots or with fewer than none.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HeldLots(Qty);

impl HeldLots {
    /// The lots, one or more.
    pub const fn lots(self) -> Qty {
        self.0
    }
}

impl Position {
    /// The lots held, positive long and negative short.
    pub const fn signed_lots(self) -> Qty {
        match self {
            Self::Flat => Qty(0),
            Self::Long(held) => held.0,
            Self::Short(held) => Qty(-held.0.0),
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
            Ordering::Greater => Ok(Self::Long(HeldLots(held))),
            Ordering::Equal => Ok(Self::Flat),
            Ordering::Less => Ok(Self::Short(HeldLots(Qty(0).checked_sub(held)?))),
        }
    }
}

impl fmt::Display for Position {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Flat => formatter.write_str("flat"),
            Self::Long(held) => write!(formatter, "long {} lots", held.0),
            Self::Short(held) => write!(formatter, "short {} lots", held.0),
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
    opened_at: Option<Ts>,
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
            opened_at: None,
        }
    }

    /// A ledger of `instrument` holding `starting_cash` that opens in a position, `lots` bought
    /// or sold at `price`, as a scenario's opening position (BACKLOG.md, step 2.6): its cash is
    /// moved by the position's value at `price`, the other way, rounded once (F-FEE-03), so that
    /// equity is `starting_cash` at a mark of `price`. It has no mark yet.
    pub fn holding(
        instrument: InstrumentParameters,
        starting_cash: Money,
        side: Side,
        lots: Qty,
        price: Price,
    ) -> Result<Self, LedgerError> {
        let flat = Self::new(instrument, starting_cash);
        let (position, cash, _) = flat.after(side, lots, price, Money(0))?;
        Ok(Self {
            position,
            cash,
            ..flat
        })
    }

    /// Books `fill`: the position moves by its lots, the cash by its value, the other way, and by
    /// its fee, each rounded once (F-FEE-03), and the mark stays (F-MRK-01). Returns what the
    /// fill's value moved the cash by, the reference engine's `Fill.cash`. A fill the ledger
    /// refuses leaves it as it was.
    pub fn book(&mut self, fill: &Fill) -> Result<Money, LedgerError> {
        let (position, cash, cash_moved) =
            self.after(fill.side, fill.lots, fill.price, fill.fee)?;
        #[cfg(debug_assertions)]
        let before = self.clone();
        let (held, holds) = (self.position.signed_lots().0, position.signed_lots().0);
        self.opened_at = match holds {
            0 => None,
            _ if held.signum() != holds.signum() => Some(fill.ts),
            _ => self.opened_at,
        };
        self.position = position;
        self.cash = cash;
        #[cfg(debug_assertions)]
        self.check_booking(&before, fill);
        Ok(cash_moved)
    }

    /// The position, the cash, and the cash the value moved once `lots` are bought or sold at
    /// `price` for `fee`, worked out before anything changes.
    fn after(
        &self,
        side: Side,
        lots: Qty,
        price: Price,
        fee: Money,
    ) -> Result<(Position, Money, Money), LedgerError> {
        let position = self.position.after(side, lots)?;
        let sold = Qty(-side.sign() * lots.0);
        let cash_moved = self.instrument.value(price, sold)?;
        let cash = self.cash.checked_add(cash_moved)?.checked_sub(fee)?;
        Ok((position, cash, cash_moved))
    }

    /// Books a roll's two legs, `close` on the contract rolled from and then `open` on the new
    /// front, as fills are booked, the position's open staying the fill that opened it (F-ROL-02,
    /// F-TIM-02). Returns what each leg's value moved the cash by; a leg the ledger refuses leaves
    /// it as it was.
    pub fn transfer(&mut self, close: &Fill, open: &Fill) -> Result<[Money; 2], LedgerError> {
        let mut after = self.clone();
        let moved = [after.book(close)?, after.book(open)?];
        after.opened_at = self.opened_at;
        *self = after;
        Ok(moved)
    }

    /// F-FND-01: a funding time at `rate`. An open position pays its signed lots × the mark ×
    /// point value × the rate, which moves the cash the other way, rounded toward minus infinity
    /// (F-FEE-03). Returns that change to the cash, none when flat.
    pub fn pay_funding(&mut self, rate: Rate) -> Result<Money, LedgerError> {
        let change = match (self.position, self.mark) {
            (Position::Flat, _) => return Ok(Money(0)),
            (position, Some(mark)) => {
                funding_change(&self.instrument, position.signed_lots(), mark, rate)?
            }
            (position, None) => return Err(LedgerError::UnmarkedPosition { position }),
        };
        self.cash = self.cash.checked_add(change)?;
        Ok(change)
    }

    /// Marks the position at `price`, the last tradeable price seen (F-MRK-01).
    pub fn mark_at(&mut self, price: Price) {
        self.mark = Some(price);
    }

    /// F-ROL-03: a roll moved the market by `gap`, and the mark moves with it.
    pub fn shift_mark(&mut self, gap: Price) -> Result<(), Overflow> {
        self.mark = self.mark.map(|mark| mark.checked_add(gap)).transpose()?;
        Ok(())
    }

    /// The instrument whose lots the ledger holds.
    pub const fn instrument(&self) -> InstrumentParameters {
        self.instrument
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

    /// The instant of the fill that opened the position, from flat or by reversing one; none when
    /// flat, and for a position held when the tape starts, which no fill opened.
    pub const fn opened_at(&self) -> Option<Ts> {
        self.opened_at
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

    /// Debug builds hold every booking to the accounting identity (F-MRK-01, F-FEE-03). The cash
    /// moves by the fill's exact value, the other way, and by its fee, within the micro-unit that
    /// rounding the value takes from the trader. Once the position is marked, equity moves by the
    /// fee and by the mark's distance from the fill's price over the lots the fill adds, exactly
    /// but for three amounts each rounded once (the cash the fill moved and the position's value
    /// before and after), so within two micro-units below and one above.
    #[cfg(debug_assertions)]
    fn check_booking(&self, before: &Self, fill: &Fill) {
        let units = i128::from(crate::units::PRICE_UNITS);
        let added = i128::from(fill.side.sign()) * i128::from(fill.lots.0);
        let per_point = i128::from(self.instrument.money_per_point().0);
        let fee = i128::from(fill.fee.0) * units;
        let cash_moved = (i128::from(self.cash.0) - i128::from(before.cash.0)) * units;
        let exact_cash = (-added)
            .checked_mul(i128::from(fill.price.0))
            .and_then(|value| value.checked_mul(per_point))
            .and_then(|value| value.checked_sub(fee));
        if let Some(rounding) = exact_cash.and_then(|exact| cash_moved.checked_sub(exact)) {
            debug_assert!(
                -units < rounding && rounding <= 0,
                "Expected booking {fill:?} to move the cash from {} by the fill's value and fee, \
                 got {}",
                before.cash,
                self.cash
            );
        }
        let (Some(mark), Ok(start), Ok(end)) = (self.mark, before.equity(), self.equity()) else {
            return;
        };
        let exact = (i128::from(mark.0) - i128::from(fill.price.0))
            .checked_mul(added)
            .and_then(|gap| gap.checked_mul(per_point))
            .and_then(|gap| gap.checked_sub(fee));
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
