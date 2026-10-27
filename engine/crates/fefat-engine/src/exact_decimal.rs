//! Floats of a specification or a signal frame read as the decimals they print as, so that the
//! Rust template finds a size or an R multiple whole exactly when `fefat.reference.template`,
//! which reads them as `Decimal(repr(x))`, does.

/// A float of a specification or a signal frame as the decimal it prints as, `1.3` for 1.3: the
/// shortest decimal that reads back as the float, which Python's `repr` writes too, so that sizes
/// and multiples are whole exactly when `fefat.reference.template` finds them whole.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ExactDecimal {
    digits: i128,
    scale: u32,
}

impl ExactDecimal {
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
        let numerator = self.digits.checked_mul(i128::from(multiplier))?;
        let denominator = 10_i128
            .checked_pow(self.scale)?
            .checked_mul(i128::from(divisor))?;
        let whole = numerator.checked_rem(denominator)? == 0;
        whole.then(|| numerator.checked_div(denominator)).flatten()
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
}
