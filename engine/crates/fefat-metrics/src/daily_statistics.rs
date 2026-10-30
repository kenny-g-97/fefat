//! The statistics of a run's days (`02` §7, step 2.11). A day's profit and loss is the change of
//! the account's equity at the last decision of its trade date (`02` §1.3) from the last decision
//! of the trade date before, the first day's from the capital, as `equity_daily` holds it. From
//! the days: the worst; the best day's share of the profit, when both are above zero; the mean of
//! the worst twentieth of the days, at least one, the daily CVaR at 95 %; the days that lose at
//! least a set share of the capital; and the Sharpe and Sortino ratios of the daily profit and
//! loss, annualised by the days a year holds, the days over the calendar days they span times
//! 365.25, with the probabilistic Sharpe ratio (Bailey and López de Prado, 2012) and its
//! deflation for the trials behind the run (2014). A ratio needs two days; none where it cannot
//! be worked out.

use std::num::NonZeroU32;

use fefat_core::costs::Rate;
use fefat_core::instants::TradeDate;
use fefat_core::units::{MONEY_UNITS, Money, Overflow, PRICE_UNITS};
use serde::Serialize;

use crate::drawdown::DatedEquity;
use crate::json_units;
use crate::normal::{cumulative, expected_maximum};
use crate::summation::compensated_sum;

/// The mean length of a year in days.
const DAYS_PER_YEAR: f64 = 365.25;

/// The statistics of a run's days, money in the instrument's currency.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct DailyStatistics {
    /// The trade dates the account was valued on.
    pub days: usize,
    /// The day that lost most, the first if two lost as much.
    pub worst_day: Option<DayPnl>,
    /// The best day's profit over the run's, when both are above zero.
    pub best_day_share: Option<f64>,
    /// The mean profit and loss of the worst twentieth of the days, at least one.
    pub cvar_95: Option<f64>,
    /// The days that lost at least the threshold.
    pub large_daily_losses: usize,
    /// Those days over all days.
    pub large_daily_loss_frequency: Option<f64>,
    /// The loss that makes a day a large daily loss.
    #[serde(serialize_with = "json_units::money_text")]
    pub large_daily_loss_threshold: Money,
    /// The annualised Sharpe ratio of the daily profit and loss.
    pub sharpe: Option<f64>,
    /// The annualised Sortino ratio, the mean over the deviation of the days' losses below zero.
    pub sortino: Option<f64>,
    /// The probability that the daily Sharpe ratio is above zero.
    pub probabilistic_sharpe: Option<f64>,
    /// That probability against the best of the trials' Sharpe ratios that luck alone gives.
    pub deflated_sharpe: Option<f64>,
    /// The trials of which the run is the one kept.
    pub trials: NonZeroU32,
}

/// A trade date's profit and loss.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct DayPnl {
    /// The trade date.
    pub trade_date: TradeDate,
    /// The change of the equity over it.
    #[serde(serialize_with = "json_units::money_text")]
    pub pnl: Money,
}

/// The statistics of the days of an account that holds `capital` before its first decision and
/// `equity` after each, a large daily loss losing `large_daily_loss` of the capital, behind which
/// lie `trials` trials.
///
/// # Errors
///
/// [`Overflow`] when a day's profit and loss or the threshold does not fit in 64 bits.
pub fn daily_statistics(
    capital: Money,
    equity: &[DatedEquity],
    large_daily_loss: Rate,
    trials: NonZeroU32,
) -> Result<DailyStatistics, Overflow> {
    let days = daily_pnl(capital, equity)?;
    let pnls: Vec<i64> = days.iter().map(|day| day.pnl.0).collect();
    let threshold = threshold(capital, large_daily_loss)?;
    let large = pnls.iter().filter(|pnl| **pnl <= -threshold.0).count();
    let ratios = SharpeRatios::of(&days, trials);
    Ok(DailyStatistics {
        days: days.len(),
        worst_day: days
            .iter()
            .copied()
            .reduce(|worst, day| if day.pnl < worst.pnl { day } else { worst }),
        best_day_share: best_day_share(&pnls),
        cvar_95: cvar_95(pnls.clone()),
        large_daily_losses: large,
        large_daily_loss_frequency: (!days.is_empty()).then(|| large as f64 / days.len() as f64),
        large_daily_loss_threshold: threshold,
        sharpe: ratios.sharpe,
        sortino: ratios.sortino,
        probabilistic_sharpe: ratios.probabilistic,
        deflated_sharpe: ratios.deflated,
        trials,
    })
}

/// Each trade date's profit and loss: the change of its last equity from the last before it,
/// the first's from `capital`.
fn daily_pnl(capital: Money, equity: &[DatedEquity]) -> Result<Vec<DayPnl>, Overflow> {
    let closes = equity
        .chunk_by(|earlier, later| earlier.trade_date == later.trade_date)
        .filter_map(<[DatedEquity]>::last);
    let mut before = capital;
    closes
        .map(|close| {
            let pnl = close.equity.checked_sub(before)?;
            before = close.equity;
            Ok(DayPnl {
                trade_date: close.trade_date,
                pnl,
            })
        })
        .collect()
}

/// `share` of `capital`, rounded down.
fn threshold(capital: Money, share: Rate) -> Result<Money, Overflow> {
    let exact = i128::from(capital.0) * i128::from(share.0);
    let floored = exact.div_euclid(i128::from(PRICE_UNITS));
    i64::try_from(floored).map(Money).map_err(|_| Overflow {
        operation: "a share of the capital",
        left: capital.0.into(),
        right: share.0.into(),
    })
}

/// The best day's profit over the run's, when both are above zero.
fn best_day_share(pnls: &[i64]) -> Option<f64> {
    let best = *pnls.iter().max()?;
    let total: i128 = pnls.iter().map(|pnl| i128::from(*pnl)).sum();
    (best > 0 && total > 0).then(|| best as f64 / total as f64)
}

/// The mean profit and loss of the worst twentieth of the days, at least one, in the currency.
fn cvar_95(mut pnls: Vec<i64>) -> Option<f64> {
    if pnls.is_empty() {
        return None;
    }
    pnls.sort_unstable();
    let worst = pnls.len().div_ceil(20);
    let total: i128 = pnls.iter().take(worst).map(|pnl| i128::from(*pnl)).sum();
    Some(total as f64 / (worst as f64 * MONEY_UNITS as f64))
}

/// The ratios of the daily profit and loss: none below two days.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
struct SharpeRatios {
    sharpe: Option<f64>,
    sortino: Option<f64>,
    probabilistic: Option<f64>,
    deflated: Option<f64>,
}

impl SharpeRatios {
    fn of(days: &[DayPnl], trials: NonZeroU32) -> Self {
        let (Some(first), Some(last)) = (days.first(), days.last()) else {
            return Self::default();
        };
        if days.len() < 2 {
            return Self::default();
        }
        let count = days.len() as f64;
        let span = f64::from(last.trade_date.0) - f64::from(first.trade_date.0) + 1.0;
        let annual = (count * DAYS_PER_YEAR / span).sqrt();
        let pnls: Vec<i64> = days.iter().map(|day| day.pnl.0).collect();
        let moments = Moments::of(&pnls);
        let sortino = downside_deviation(&pnls).map(|deviation| moments.mean / deviation * annual);
        let Some(daily) = moments.sharpe() else {
            return Self {
                sortino,
                ..Self::default()
            };
        };
        let z = moments.probabilistic_z(daily);
        Self {
            sharpe: Some(daily * annual),
            sortino,
            probabilistic: z.map(cumulative),
            deflated: z.map(|z| cumulative(z - expected_maximum(trials))),
        }
    }
}

/// The root mean square of each day's loss below zero, a day without a loss counting zero;
/// none without a losing day.
fn downside_deviation(pnls: &[i64]) -> Option<f64> {
    let losses = pnls.iter().map(|pnl| (*pnl).min(0) as f64);
    let squares = compensated_sum(losses.map(|loss| loss * loss));
    (squares > 0.0).then(|| (squares / pnls.len() as f64).sqrt())
}

/// The mean of two or more values and the sums of the second, third, and fourth powers of their
/// distances from it, each distance worked out exactly before it becomes a float.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Moments {
    count: f64,
    mean: f64,
    squares: f64,
    cubes: f64,
    fourths: f64,
}

impl Moments {
    fn of(values: &[i64]) -> Self {
        let count = values.len() as i128;
        let total: i128 = values.iter().map(|value| i128::from(*value)).sum();
        let distances: Vec<f64> = values
            .iter()
            .map(|value| (count * i128::from(*value) - total) as f64 / count as f64)
            .collect();
        let powers = |power: fn(f64) -> f64| compensated_sum(distances.iter().copied().map(power));
        Self {
            count: count as f64,
            mean: total as f64 / count as f64,
            squares: powers(|distance| distance * distance),
            cubes: powers(|distance| distance * distance * distance),
            fourths: powers(|distance| distance * distance * (distance * distance)),
        }
    }

    /// The daily Sharpe ratio, the mean over the sample standard deviation; none when every
    /// value is the same.
    fn sharpe(&self) -> Option<f64> {
        (self.squares > 0.0).then(|| self.mean / (self.squares / (self.count - 1.0)).sqrt())
    }

    /// The statistic of the probabilistic Sharpe ratio, `SR √(n - 1) / √(1 - γ₃ SR + (γ₄ - 1)
    /// SR² / 4)`, γ₃ and γ₄ the skewness and the kurtosis of the values, their third and fourth
    /// moments about the mean over the second's powers; none where the root's argument is not
    /// above zero.
    fn probabilistic_z(&self, sharpe: f64) -> Option<f64> {
        let second = self.squares / self.count;
        let skewness = self.cubes / self.count / (second * second.sqrt());
        let kurtosis = self.fourths / self.count / (second * second);
        let spread = 1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe;
        (spread > 0.0).then(|| sharpe * (self.count - 1.0).sqrt() / spread.sqrt())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CAPITAL: Money = Money(50_000 * MONEY_UNITS);

    fn account(points: &[(i32, i64)]) -> Vec<DatedEquity> {
        points
            .iter()
            .map(|&(day, equity)| DatedEquity {
                trade_date: TradeDate(day),
                equity: Money(CAPITAL.0 + equity * MONEY_UNITS),
            })
            .collect()
    }

    fn statistics(points: &[(i32, i64)], trials: u32) -> DailyStatistics {
        let trials = NonZeroU32::new(trials).unwrap();
        daily_statistics(CAPITAL, &account(points), Rate(20_000_000), trials).unwrap()
    }

    #[test]
    fn a_day_counts_from_its_last_equity_to_the_last_of_the_day_before() {
        let days = daily_pnl(CAPITAL, &account(&[(1, -10), (1, 30), (2, 20), (4, 50)])).unwrap();
        let pnls: Vec<(i32, i64)> = days
            .iter()
            .map(|day| (day.trade_date.0, day.pnl.0 / MONEY_UNITS))
            .collect();
        assert_eq!(pnls, [(1, 30), (2, -10), (4, 30)]);
    }

    #[test]
    fn the_worst_day_the_best_days_share_and_the_large_losses() {
        let days = statistics(&[(1, 300), (2, -900), (3, 100), (4, 1_100)], 1);
        assert_eq!(days.days, 4);
        assert_eq!(
            days.worst_day,
            Some(DayPnl {
                trade_date: TradeDate(2),
                pnl: Money(-1_200 * MONEY_UNITS)
            })
        );
        assert_eq!(days.best_day_share, Some(1_000.0 / 1_100.0));
        assert_eq!(days.cvar_95, Some(-1_200.0));
        assert_eq!(days.large_daily_loss_threshold, Money(1_000 * MONEY_UNITS));
        assert_eq!(days.large_daily_losses, 1);
        assert_eq!(days.large_daily_loss_frequency, Some(0.25));
    }

    #[test]
    fn a_run_without_profit_has_no_best_days_share() {
        assert_eq!(statistics(&[(1, 100), (2, -200)], 1).best_day_share, None);
    }

    #[test]
    fn one_day_or_equal_days_give_no_sharpe_ratio() {
        let one_day = statistics(&[(1, 100)], 1);
        assert_eq!((one_day.sharpe, one_day.sortino), (None, None));
        let equal = statistics(&[(1, 100), (2, 200), (3, 300)], 1);
        assert_eq!((equal.sharpe, equal.probabilistic_sharpe), (None, None));
        assert_eq!(equal.sortino, None);
    }

    #[test]
    fn the_ratios_of_four_days_in_a_week() {
        let days = statistics(&[(1, 100), (2, 50), (3, 250), (7, 150)], 1);
        let (mean, deviation) = (37.5_f64, (56_875.0_f64 / 3.0).sqrt());
        let annual = (4.0 * 365.25 / 7.0_f64).sqrt();
        let sharpe = days.sharpe.unwrap();
        assert!((sharpe - mean / deviation * annual).abs() < 1e-12);
        let downside = ((2_500.0_f64 + 10_000.0) / 4.0).sqrt();
        let sortino = days.sortino.unwrap();
        assert!((sortino - mean / downside * annual).abs() < 1e-12);
        let (probabilistic, deflated) = (days.probabilistic_sharpe.unwrap(), days.deflated_sharpe);
        assert!(probabilistic > 0.5 && probabilistic < 1.0);
        assert_eq!(deflated, Some(probabilistic));
        let deflated = statistics(&[(1, 100), (2, 50), (3, 250), (7, 150)], 100).deflated_sharpe;
        assert!(deflated.unwrap() < probabilistic);
    }
}
