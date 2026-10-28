//! Floats of a specification or a signal frame read as the decimals they print as, so that the
//! Rust template finds a size or an R multiple whole exactly when `fefat.reference.template`,
//! which reads them as `Decimal(repr(x))`, does.

/// A float of a specification or a signal frame as the decimal it prints as, `1.3` for 1.3: the
/// shortest decimal that reads back as the float, which Python's `repr` writes too, so that sizes
/// and multiples are whole exactly when `fefat.reference.template` finds them whole, and every
/// distance rounds as the reference rounds it (F-RND-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExactDecimal {
    digits: i128,
    scale: u32,
}

impl ExactDecimal {
    /// One, a whole target's fraction.
    pub(crate) const ONE: Self = Self {
        digits: 1,
        scale: 0,
    };

    /// The decimal of `number`; none for a NaN, an infinity, or a decimal too long to count.
    pub(crate) fn of(number: f64) -> Option<Self> {
        let text = number.to_string();
        let (whole, fraction) = text.split_once('.').unwrap_or((text.as_str(), ""));
        Some(Self {
            digits: format!("{whole}{fraction}").parse().ok()?,
            scale: u32::try_from(fraction.len()).ok()?,
        })
    }

    /// `self × multiplier ÷ divisor` when it is a whole number.
    pub(crate) fn whole_times(self, multiplier: i64, divisor: i64) -> Option<i128> {
        let (numerator, denominator) = self.over(multiplier.into(), divisor.into())?;
        let whole = numerator.checked_rem(denominator)? == 0;
        whole.then(|| numerator.checked_div(denominator)).flatten()
    }

    /// `self × multiplier ÷ divisor`, rounded down, for a divisor above zero.
    pub(crate) fn floor_times(self, multiplier: i128, divisor: i128) -> Option<i128> {
        let (numerator, denominator) = self.over(multiplier, divisor)?;
        numerator.checked_div_euclid(denominator)
    }

    /// `self × multiplier ÷ divisor`, rounded up, for a divisor above zero.
    pub(crate) fn ceil_times(self, multiplier: i128, divisor: i128) -> Option<i128> {
        let (numerator, denominator) = self.over(multiplier, divisor)?;
        numerator
            .checked_neg()?
            .checked_div_euclid(denominator)?
            .checked_neg()
    }

    /// The decimal cut toward zero to a whole number, as a feature's value is cut to whole 1e-9
    /// units of price (F-RND-01); none beyond 64 bits.
    pub(crate) fn truncated(self) -> Option<i64> {
        let whole = 10_i128
            .checked_pow(self.scale)
            .map_or(0, |divisor| self.digits / divisor);
        i64::try_from(whole).ok()
    }

    fn over(self, multiplier: i128, divisor: i128) -> Option<(i128, i128)> {
        let numerator = self.digits.checked_mul(multiplier)?;
        let denominator = 10_i128.checked_pow(self.scale)?.checked_mul(divisor)?;
        (denominator > 0).then_some((numerator, denominator))
    }
}

#[cfg(test)]
mod tests {
    use fefat_core::units::PRICE_UNITS;

    use super::*;

    #[test]
    fn a_float_counts_as_the_decimal_it_prints_as() {
        let size = ExactDecimal::of(1.3).unwrap();
        assert_eq!((size.digits, size.scale), (13, 1));
        assert_eq!(ExactDecimal::of(0.1).unwrap().whole_times(10, 1), Some(1));
        assert_eq!(ExactDecimal::of(2.0).unwrap().whole_times(3, 1), Some(6));
        assert_eq!(ExactDecimal::of(1.5).unwrap().whole_times(3, 1), None);
        assert_eq!(
            ExactDecimal::of(0.013)
                .unwrap()
                .whole_times(PRICE_UNITS, 1_000_000),
            Some(13)
        );
        assert_eq!(ExactDecimal::of(f64::NAN), None);
        assert_eq!(ExactDecimal::of(f64::INFINITY), None);
    }

    #[test]
    fn a_decimal_rounds_down_and_up_exactly_and_cuts_to_units_toward_zero() {
        // F-RND-01: 0.07 % of 5000.25 is 14.0007 ticks of 0.25, and 2 × 1.30 is 10.4 ticks.
        let percent = ExactDecimal::of(0.07).unwrap();
        let fill = 5_000_250_000_000_i128;
        assert_eq!(percent.floor_times(fill, 100 * 250_000_000), Some(14));
        let distance = ExactDecimal::of(2.0).unwrap();
        assert_eq!(distance.ceil_times(1_300_000_000, 250_000_000), Some(11));
        assert_eq!(distance.ceil_times(1_000_000_000, 250_000_000), Some(8));
        assert_eq!(
            ExactDecimal::of(1_300_000_000.75).unwrap().truncated(),
            Some(1_300_000_000)
        );
        assert_eq!(ExactDecimal::of(0.5).unwrap().truncated(), Some(0));
        assert_eq!(ExactDecimal::of(1e-30).unwrap().truncated(), Some(0));
        assert_eq!(ExactDecimal::of(1e19).unwrap().truncated(), None);
    }
}
