//! Prices, quantities, and money as the engines count them (Phase 2's conventions, ADR-0019): a
//! price in 1e-9 units of the quote currency, a quantity in lots of the dataset's size unit, and
//! money in micro-units of its currency, each an `i64` whose arithmetic is checked, so that an
//! amount that leaves 64 bits is an error and never wraps (F-FEE-03).

use std::fmt;

use thiserror::Error;

const PRICE_DECIMALS: u32 = 9;
const MONEY_DECIMALS: u32 = 6;

/// Units of price in one unit of the quote currency: 5,432.25 is 5_432_250_000_000.
pub const PRICE_UNITS: i64 = 10_i64.pow(PRICE_DECIMALS);
/// Micro-units of money in one unit of its currency.
pub const MONEY_UNITS: i64 = 10_i64.pow(MONEY_DECIMALS);

/// A price in 1e-9 units of the quote currency, shown as the decimal a scenario writes (`4990.25`).
/// A price may be negative, as CL's were on 2020-04-20.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Price(pub i64);

/// A quantity in lots of the dataset's size unit: a size or a volume, or the lots of a position,
/// positive long and negative short.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Qty(pub i64);

/// An amount of money in micro-units of its currency, shown with six places (`-0.084514`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Money(pub i64);

/// Arithmetic whose result does not fit in 64 bits: the engine never wraps (F-FEE-03).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[error("Expected {operation} to fit in 64 bits, got an overflow from {left} and {right}")]
pub struct Overflow {
    /// What was worked out, such as `a sum of money`.
    pub operation: &'static str,
    /// The first operand, in its type's units.
    pub left: i128,
    /// The second operand, in its type's units.
    pub right: i128,
}

macro_rules! checked_sum_and_difference {
    ($unit:ident, $sum:literal, $difference:literal) => {
        impl $unit {
            /// The sum, or [`Overflow`] when it leaves 64 bits.
            pub fn checked_add(self, other: Self) -> Result<Self, Overflow> {
                self.0.checked_add(other.0).map(Self).ok_or(Overflow {
                    operation: $sum,
                    left: self.0.into(),
                    right: other.0.into(),
                })
            }

            /// The difference, or [`Overflow`] when it leaves 64 bits.
            pub fn checked_sub(self, other: Self) -> Result<Self, Overflow> {
                self.0.checked_sub(other.0).map(Self).ok_or(Overflow {
                    operation: $difference,
                    left: self.0.into(),
                    right: other.0.into(),
                })
            }
        }
    };
}

checked_sum_and_difference!(Price, "a sum of prices", "a difference of prices");
checked_sum_and_difference!(Qty, "a sum of quantities", "a difference of quantities");
checked_sum_and_difference!(Money, "a sum of money", "a difference of money");

impl fmt::Display for Price {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let text = decimal_text(self.0, PRICE_DECIMALS);
        formatter.write_str(text.trim_end_matches('0').trim_end_matches('.'))
    }
}

impl fmt::Display for Qty {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.0)
    }
}

impl fmt::Display for Money {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&decimal_text(self.0, MONEY_DECIMALS))
    }
}

/// `units` counted in `10^-decimals` as a decimal with all `decimals` places: `4990.250000000`.
fn decimal_text(units: i64, decimals: u32) -> String {
    let per_unit = 10_u64.pow(decimals);
    let magnitude = units.unsigned_abs();
    let sign = if units < 0 { "-" } else { "" };
    let width = decimals as usize;
    format!(
        "{sign}{}.{:0width$}",
        magnitude / per_unit,
        magnitude % per_unit
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prices_read_as_the_scenarios_write_them() {
        assert_eq!(Price(4_990_250_000_000).to_string(), "4990.25");
        assert_eq!(Price(5_000 * PRICE_UNITS).to_string(), "5000");
        assert_eq!(Price(-500_000_000).to_string(), "-0.5");
        assert_eq!(Price(1).to_string(), "0.000000001");
        assert_eq!(Price(0).to_string(), "0");
    }

    #[test]
    fn money_shows_its_six_places() {
        assert_eq!(Money(-84_514).to_string(), "-0.084514");
        assert_eq!(Money(2_500_000).to_string(), "2.500000");
        assert_eq!(Money(i64::MIN).to_string(), "-9223372036854.775808");
    }

    #[test]
    fn arithmetic_that_leaves_64_bits_is_an_error_not_a_wrap() {
        let overflow = Money(i64::MAX).checked_add(Money(1)).unwrap_err();
        assert_eq!(
            overflow.to_string(),
            "Expected a sum of money to fit in 64 bits, got an overflow from 9223372036854775807 and 1"
        );
        assert!(Qty(i64::MIN).checked_sub(Qty(1)).is_err());
        assert!(Price(i64::MIN).checked_add(Price(-1)).is_err());
        assert_eq!(Money(5).checked_sub(Money(7)), Ok(Money(-2)));
    }
}
