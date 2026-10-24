//! A contract's name and an instrument's parameters in the engines' integers (D-51): the tick in
//! 1e-9 units of price, the money one lot gains or loses per point in micro-units, and the lot
//! step. Step 2.10 builds them from `fefat.market.instruments.Instrument`, as
//! `fefat.reference.units.instrument_parameters` does.

use std::fmt;

use thiserror::Error;

use crate::units::{Money, Overflow, PRICE_UNITS, Price, Qty};

/// A contract as the store names it: its root, month code, and four-digit year, such as `ESH2026`.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Contract(pub String);

impl fmt::Display for Contract {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// One lot in 1e-9 units of the instrument's unit: a futures contract is 1_000_000_000, a lot of
/// 0.001 BTC is 1_000_000.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LotStep(pub i64);

/// An instrument's specification in the units both engines count in: ES is a tick of
/// 250_000_000, 50_000_000 micro-units a point, and lots of one contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InstrumentParameters {
    tick_size: Price,
    money_per_point: Money,
    lot_step: LotStep,
}

/// A parameter of an instrument at or below zero.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[error("Expected an instrument's {parameter} above zero, got {value}")]
pub struct NonPositiveParameter {
    /// Which parameter, with its unit.
    pub parameter: &'static str,
    /// Its value in that unit.
    pub value: i64,
}

impl InstrumentParameters {
    /// The tick, the money one lot gains or loses when the price moves one point, and the lot
    /// step, each above zero.
    pub fn new(
        tick_size: Price,
        money_per_point: Money,
        lot_step: LotStep,
    ) -> Result<Self, NonPositiveParameter> {
        let parameters = [
            ("tick size in 1e-9 units", tick_size.0),
            ("money per point in micro-units", money_per_point.0),
            ("lot step in 1e-9 units", lot_step.0),
        ];
        if let Some((parameter, value)) = parameters.into_iter().find(|(_, value)| *value <= 0) {
            return Err(NonPositiveParameter { parameter, value });
        }
        Ok(Self {
            tick_size,
            money_per_point,
            lot_step,
        })
    }

    /// The tick in 1e-9 units of price.
    pub const fn tick_size(&self) -> Price {
        self.tick_size
    }

    /// The money one lot gains or loses when the price moves one point, in micro-units.
    pub const fn money_per_point(&self) -> Money {
        self.money_per_point
    }

    /// One lot in 1e-9 units of the instrument's unit.
    pub const fn lot_step(&self) -> LotStep {
        self.lot_step
    }

    /// What `lots` are worth at `price` in micro-units, worked out exactly and floored once
    /// toward minus infinity (F-FEE-03): negative for a short. Callers pass the signed quantity
    /// and never negate a rounded amount, so that what the trader pays rounds up and what the
    /// trader receives rounds down, as `fefat.reference.engine` books them.
    pub fn value(&self, price: Price, lots: Qty) -> Result<Money, Overflow> {
        let overflow = Overflow {
            operation: "the value of lots at a price",
            left: price.0.into(),
            right: lots.0.into(),
        };
        let exact = i128::from(price.0)
            .checked_mul(i128::from(lots.0))
            .and_then(|product| product.checked_mul(i128::from(self.money_per_point.0)))
            .ok_or(overflow)?;
        let floored = exact.div_euclid(i128::from(PRICE_UNITS));
        i64::try_from(floored).map(Money).map_err(|_| overflow)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::units::MONEY_UNITS;

    fn es() -> InstrumentParameters {
        InstrumentParameters::new(
            Price(250_000_000),
            Money(50 * MONEY_UNITS),
            LotStep(PRICE_UNITS),
        )
        .unwrap()
    }

    fn inexact() -> InstrumentParameters {
        InstrumentParameters::new(Price(1), Money(1), LotStep(1)).unwrap()
    }

    #[test]
    fn two_es_lots_at_5000_are_worth_500000_dollars_and_a_short_owes_them() {
        let price = Price(5_000 * PRICE_UNITS);
        assert_eq!(es().value(price, Qty(2)), Ok(Money(500_000 * MONEY_UNITS)));
        assert_eq!(
            es().value(price, Qty(-2)),
            Ok(Money(-500_000 * MONEY_UNITS))
        );
    }

    #[test]
    fn an_inexact_value_floors_toward_minus_infinity() {
        assert_eq!(inexact().value(Price(1), Qty(1)), Ok(Money(0)));
        assert_eq!(inexact().value(Price(1), Qty(-1)), Ok(Money(-1)));
        assert_eq!(inexact().value(Price(-1), Qty(1)), Ok(Money(-1)));
        assert_eq!(inexact().value(Price(1_500_000_000), Qty(1)), Ok(Money(1)));
        assert_eq!(
            inexact().value(Price(1_500_000_000), Qty(-1)),
            Ok(Money(-2))
        );
    }

    #[test]
    fn a_value_beyond_64_bits_is_an_error_not_a_wrap() {
        let beyond_128_bits = es().value(Price(i64::MAX), Qty(i64::MAX)).unwrap_err();
        assert_eq!(beyond_128_bits.operation, "the value of lots at a price");
        assert!(es().value(Price(i64::MAX), Qty(1_000)).is_err());
        assert!(es().value(Price(i64::MIN), Qty(1_000)).is_err());
    }

    #[test]
    fn instrument_parameters_are_above_zero() {
        let refused = InstrumentParameters::new(Price(0), Money(1), LotStep(1)).unwrap_err();
        assert_eq!(
            refused.to_string(),
            "Expected an instrument's tick size in 1e-9 units above zero, got 0"
        );
        assert!(InstrumentParameters::new(Price(1), Money(1), LotStep(-1)).is_err());
    }
}
