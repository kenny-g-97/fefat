//! The standard normal distribution as the probabilistic and deflated Sharpe ratios read it
//! (Bailey and López de Prado, 2012 and 2014): its cumulative probability, its quantiles from the
//! median up, and the expected largest of many draws. Every function is `libm`'s or IEEE
//! arithmetic, so that a run's metrics are the same on every system.

use std::f64::consts::{E, EULER_GAMMA, PI, SQRT_2};
use std::num::NonZeroU32;

/// The probability that a standard normal draw lies at or below `x`.
pub fn cumulative(x: f64) -> f64 {
    0.5 * libm::erfc(-x / SQRT_2)
}

/// The probability that a standard normal draw lies above `x`, to full precision far in the tail.
fn upper_tail(x: f64) -> f64 {
    0.5 * libm::erfc(x / SQRT_2)
}

/// The density of the standard normal distribution at `x`.
fn density(x: f64) -> f64 {
    libm::exp(-0.5 * x * x) / (2.0 * PI).sqrt()
}

/// The `x` at which the cumulative probability is `probability`, from one half, the median, up
/// to one, which it never reaches. It solves for the upper tail, one less the probability, which
/// IEEE arithmetic works out exactly from one half up: Newton's method from the median climbs to
/// the root without passing it, since the tail is convex above the median.
pub fn quantile_from_median(probability: f64) -> f64 {
    let tail = 1.0 - probability;
    let mut x: f64 = 0.0;
    for _ in 0..200 {
        let step = (upper_tail(x) - tail) / density(x);
        x += step;
        if step.abs() <= 4.0 * f64::EPSILON * x.abs().max(1.0) {
            break;
        }
    }
    x
}

/// The expected largest of `trials` independent standard normal draws, as the deflated Sharpe
/// ratio approximates it: `(1 - γ) Φ⁻¹(1 - 1/N) + γ Φ⁻¹(1 - 1/(N e))`, γ the Euler-Mascheroni
/// constant; zero for one trial, whose Sharpe ratio is taken as it is.
pub fn expected_maximum(trials: NonZeroU32) -> f64 {
    if trials.get() == 1 {
        return 0.0;
    }
    let trials = f64::from(trials.get());
    let first = quantile_from_median(1.0 - 1.0 / trials);
    let second = quantile_from_median(1.0 - 1.0 / (trials * E));
    (1.0 - EULER_GAMMA) * first + EULER_GAMMA * second
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(left: f64, right: f64) -> bool {
        (left - right).abs() <= 1e-13 * right.abs().max(1.0)
    }

    #[test]
    fn the_cumulative_probability_is_one_half_at_zero_and_symmetric() {
        assert!(close(cumulative(0.0), 0.5));
        assert!(close(cumulative(1.96), 0.975_002_104_851_779_6));
        assert!(close(cumulative(-1.96), 1.0 - 0.975_002_104_851_779_6));
        assert!(cumulative(-40.0) >= 0.0 && cumulative(40.0) <= 1.0);
    }

    #[test]
    fn the_quantile_is_pythons_statistics_normal_dist_inv_cdf() {
        assert_eq!(quantile_from_median(0.5), 0.0);
        assert!(close(quantile_from_median(0.975), 1.959_963_984_540_053_6));
        assert!(close(
            quantile_from_median(1.0 - 1e-9),
            5.997_807_019_601_638
        ));
        for probability in [0.6, 0.9, 0.99, 0.999_999] {
            assert!(close(
                cumulative(quantile_from_median(probability)),
                probability
            ));
        }
    }

    #[test]
    fn more_trials_expect_a_larger_maximum() {
        let maximum = |trials: u32| NonZeroU32::new(trials).map_or(f64::NAN, expected_maximum);
        assert_eq!(maximum(1), 0.0);
        assert!(maximum(2) > 0.0);
        assert!(maximum(10) < maximum(100) && maximum(100) < maximum(1_000));
    }
}
