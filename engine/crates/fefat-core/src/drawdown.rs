//! The maximum drawdown of a cumulative sum: the function that proves the chain
//! from Rust through Python to a notebook (step 0.8).

use std::fmt;

/// The cumulative sum, or its fall below the peak, left the range of `i64`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DrawdownOverflow {
    /// The zero-based position of the value that overflowed.
    pub index: usize,
}

impl fmt::Display for DrawdownOverflow {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "Expected the cumulative sum and its drawdown to fit in int64, got an overflow at index {}",
            self.index
        )
    }
}

impl std::error::Error for DrawdownOverflow {}

/// The largest fall of the cumulative sum of `values` below its highest point so far.
///
/// The sum starts at 0, which counts as the first peak: a sum that only falls has a
/// drawdown equal to its total loss, and no values give 0.
///
/// # Errors
///
/// [`DrawdownOverflow`] when the cumulative sum, or its fall below the peak, does not fit in `i64`.
pub fn max_drawdown(values: impl IntoIterator<Item = i64>) -> Result<i64, DrawdownOverflow> {
    let mut equity: i64 = 0;
    let mut peak: i64 = 0;
    let mut deepest: i64 = 0;
    for (index, value) in values.into_iter().enumerate() {
        let overflow = DrawdownOverflow { index };
        equity = equity.checked_add(value).ok_or(overflow)?;
        peak = peak.max(equity);
        deepest = deepest.max(peak.checked_sub(equity).ok_or(overflow)?);
    }
    Ok(deepest)
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    #[test]
    fn no_values_give_no_drawdown() {
        assert_eq!(max_drawdown(std::iter::empty()), Ok(0));
    }

    #[test]
    fn a_rising_sum_gives_no_drawdown() {
        assert_eq!(max_drawdown([1, 2, 3]), Ok(0));
    }

    #[test]
    fn the_deepest_fall_below_a_peak_is_the_drawdown() {
        assert_eq!(max_drawdown([100, -40, 30, -120, 50, -10]), Ok(130));
    }

    #[test]
    fn a_sum_that_only_falls_loses_from_the_starting_zero() {
        assert_eq!(max_drawdown([-5, -7]), Ok(12));
    }

    #[test]
    fn a_sum_beyond_i64_names_the_value_that_overflowed() {
        assert_eq!(
            max_drawdown([i64::MAX, 1]),
            Err(DrawdownOverflow { index: 1 })
        );
    }

    #[test]
    fn a_drawdown_beyond_i64_names_the_value_that_overflowed() {
        assert_eq!(max_drawdown([i64::MIN]), Err(DrawdownOverflow { index: 0 }));
    }

    fn profits_and_losses() -> impl Strategy<Value = Vec<i64>> {
        prop::collection::vec(-1_000_000_i64..=1_000_000, 0..200)
    }

    proptest! {
        #[test]
        fn the_drawdown_lies_between_zero_and_the_total_loss(values in profits_and_losses()) {
            let total_loss: i64 = values.iter().filter(|value| **value < 0).sum::<i64>().abs();
            let drawdown = max_drawdown(values.iter().copied());
            prop_assert!(matches!(drawdown, Ok(deepest) if (0..=total_loss).contains(&deepest)));
        }

        #[test]
        fn appending_values_never_shrinks_the_drawdown(
            values in profits_and_losses(),
            appended in profits_and_losses(),
        ) {
            let before = max_drawdown(values.iter().copied());
            let after = max_drawdown(values.iter().chain(&appended).copied());
            prop_assert!(matches!((before, after), (Ok(earlier), Ok(later)) if earlier <= later));
        }
    }
}
