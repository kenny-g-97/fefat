//! Sums of floats as precise as their terms (Neumaier's compensated summation): the rounding of
//! each addition is carried along and added back once at the end, so that a sum whose terms
//! cancel, such as the ticks of winning and losing trades, keeps the digits a plain sum loses.

/// The sum of `values`, compensated.
pub fn compensated_sum(values: impl IntoIterator<Item = f64>) -> f64 {
    let (mut sum, mut lost) = (0.0_f64, 0.0_f64);
    for value in values {
        let total = sum + value;
        lost += if sum.abs() >= value.abs() {
            (sum - total) + value
        } else {
            (value - total) + sum
        };
        sum = total;
    }
    sum + lost
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terms_that_cancel_keep_the_digits_a_plain_sum_loses() {
        let terms = [1.0, 1e100, 1.0, -1e100];
        assert_eq!(terms.iter().sum::<f64>(), 0.0);
        assert_eq!(compensated_sum(terms), 2.0);
        assert_eq!(compensated_sum([0.1; 10]), 1.0);
        assert_eq!(compensated_sum([]), 0.0);
    }
}
