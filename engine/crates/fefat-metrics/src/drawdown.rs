//! An account's drawdown (`02` §7, step 2.11): at each point of its equity, in order, how far it
//! lies below the highest equity before it or at it, the first point being the first peak; the
//! deepest of those falls, with the trade dates of its peak and its trough; and the longest spell
//! under a peak, in calendar days from the peak's trade date to the recovery's, or to the last
//! trade date when the account has not recovered. The running drawdown of a prefix is the prefix
//! of the running drawdown: no point's value depends on a later one.

use fefat_core::instants::TradeDate;
use fefat_core::units::{Money, Overflow};

/// The account's equity after a decision, and the trade date of that decision.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DatedEquity {
    /// The trade date of the decision (`02` §1.3).
    pub trade_date: TradeDate,
    /// The equity, in micro-units (F-MRK-01).
    pub equity: Money,
}

/// A fall of the account below a peak.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Drawdown {
    /// How far the trough lies below the peak.
    pub depth: Money,
    /// The trade date of the last point at the peak before the fall.
    pub peak: TradeDate,
    /// The trade date of the deepest point of the fall, the first if two are as deep.
    pub trough: TradeDate,
}

/// The deepest fall of an account and its longest spell under a peak.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AccountDrawdown {
    /// The deepest fall, none when the account never fell below a peak.
    pub deepest: Option<Drawdown>,
    /// The calendar days of the longest spell under a peak, from its peak's trade date to the
    /// trade date the equity came back to the peak, or to the last point's when it did not.
    pub longest_days: i64,
}

/// How far each value of `equity` lies below the highest value before it or at it: zero at each
/// new peak, and at the first value.
///
/// # Errors
///
/// [`Overflow`] when a fall does not fit in 64 bits.
pub fn running_drawdown(equity: impl IntoIterator<Item = Money>) -> Result<Vec<Money>, Overflow> {
    equity
        .into_iter()
        .scan(None, |peak: &mut Option<Money>, value| {
            let highest = peak.map_or(value, |earlier| earlier.max(value));
            *peak = Some(highest);
            Some(highest.checked_sub(value))
        })
        .collect()
}

/// The deepest fall of `points`, an account's equity in order, and its longest spell under a peak.
///
/// # Errors
///
/// [`Overflow`] when a fall does not fit in 64 bits.
pub fn account_drawdown(points: &[DatedEquity]) -> Result<AccountDrawdown, Overflow> {
    let spells = spells(points)?;
    let deepest = spells
        .iter()
        .fold(None, |deepest: Option<Drawdown>, spell| match deepest {
            Some(earlier) if earlier.depth >= spell.deepest.depth => Some(earlier),
            _ => Some(spell.deepest),
        });
    let last = points.last().map(|point| point.trade_date);
    let longest_days = spells
        .iter()
        .filter_map(|spell| {
            let end = spell.recovered.or(last)?;
            Some(i64::from(end.0) - i64::from(spell.deepest.peak.0))
        })
        .max();
    Ok(AccountDrawdown {
        deepest,
        longest_days: longest_days.unwrap_or(0),
    })
}

/// A spell under a peak: its deepest fall, and the trade date the equity came back to the peak,
/// none when it did not.
#[derive(Debug, Clone, Copy)]
struct Spell {
    deepest: Drawdown,
    recovered: Option<TradeDate>,
}

/// Each run of points below a peak, in order.
fn spells(points: &[DatedEquity]) -> Result<Vec<Spell>, Overflow> {
    let depths = running_drawdown(points.iter().map(|point| point.equity))?;
    let mut spells = Vec::new();
    let mut peak = None;
    let mut open: Option<Spell> = None;
    for (point, depth) in points.iter().zip(depths) {
        if depth == Money(0) {
            spells.extend(open.take().map(|spell| Spell {
                recovered: Some(point.trade_date),
                ..spell
            }));
            peak = Some(point.trade_date);
            continue;
        }
        let Some(peak) = peak else { continue };
        let fall = Drawdown {
            depth,
            peak,
            trough: point.trade_date,
        };
        let spell = open.get_or_insert(Spell {
            deepest: fall,
            recovered: None,
        });
        if depth > spell.deepest.depth {
            spell.deepest = fall;
        }
    }
    spells.extend(open);
    Ok(spells)
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn money(values: &[i64]) -> Vec<Money> {
        values.iter().copied().map(Money).collect()
    }

    fn dated(points: &[(i32, i64)]) -> Vec<DatedEquity> {
        points
            .iter()
            .map(|&(day, equity)| DatedEquity {
                trade_date: TradeDate(day),
                equity: Money(equity),
            })
            .collect()
    }

    #[test]
    fn each_value_falls_below_the_highest_before_it_or_at_it() {
        let equity = money(&[100, 60, 90, -30, 20, 10]);
        assert_eq!(
            running_drawdown(equity),
            Ok(money(&[0, 40, 10, 130, 80, 90]))
        );
    }

    #[test]
    fn the_first_value_is_the_first_peak() {
        assert_eq!(running_drawdown(money(&[-5, -12])), Ok(money(&[0, 7])));
        assert_eq!(running_drawdown(Vec::new()), Ok(Vec::new()));
    }

    #[test]
    fn a_fall_beyond_64_bits_is_an_overflow() {
        let overflow = running_drawdown(money(&[i64::MAX, -1])).unwrap_err();
        assert_eq!(overflow.left, i128::from(i64::MAX));
        assert_eq!(overflow.right, -1);
    }

    #[test]
    fn the_deepest_fall_names_its_peak_and_its_trough() {
        let points = dated(&[(1, 100), (2, 120), (3, 90), (4, 70), (5, 130), (6, 125)]);
        let account = account_drawdown(&points).unwrap();
        assert_eq!(
            account.deepest,
            Some(Drawdown {
                depth: Money(50),
                peak: TradeDate(2),
                trough: TradeDate(4),
            })
        );
        assert_eq!(account.longest_days, 3);
    }

    #[test]
    fn a_spell_without_a_recovery_lasts_to_the_last_trade_date() {
        let points = dated(&[(10, 100), (11, 90), (12, 100), (13, 99), (20, 95)]);
        let account = account_drawdown(&points).unwrap();
        assert_eq!(account.longest_days, 8);
        assert_eq!(
            account
                .deepest
                .map(|fall| (fall.depth, fall.peak, fall.trough)),
            Some((Money(10), TradeDate(10), TradeDate(11)))
        );
    }

    #[test]
    fn of_two_falls_as_deep_the_first_is_the_deepest() {
        let points = dated(&[(1, 100), (2, 80), (3, 100), (4, 80)]);
        let deepest = account_drawdown(&points).unwrap().deepest.unwrap();
        assert_eq!((deepest.peak, deepest.trough), (TradeDate(1), TradeDate(2)));
    }

    #[test]
    fn a_fall_and_its_recovery_on_one_trade_date_last_no_day() {
        let points = dated(&[(5, 100), (5, 90), (5, 100), (6, 110)]);
        assert_eq!(account_drawdown(&points).unwrap().longest_days, 0);
    }

    #[test]
    fn an_account_that_never_falls_has_no_drawdown() {
        let account = account_drawdown(&dated(&[(1, 100), (2, 100), (3, 101)])).unwrap();
        assert_eq!(
            account,
            AccountDrawdown {
                deepest: None,
                longest_days: 0
            }
        );
        assert_eq!(account_drawdown(&[]).unwrap().deepest, None);
    }

    fn equities() -> impl Strategy<Value = Vec<i64>> {
        prop::collection::vec(-1_000_000_000_i64..=1_000_000_000, 0..200)
    }

    proptest! {
        #[test]
        fn no_fall_is_negative(values in equities()) {
            let depths = running_drawdown(money(&values)).unwrap();
            prop_assert!(depths.iter().all(|depth| depth.0 >= 0));
        }

        #[test]
        fn the_running_drawdown_of_a_prefix_is_its_prefix(values in equities(), cut in 0..200_usize) {
            let cut = cut.min(values.len());
            let whole = running_drawdown(money(&values)).unwrap();
            let prefix = running_drawdown(money(&values[..cut])).unwrap();
            prop_assert_eq!(&whole[..cut], &prefix[..]);
        }

        #[test]
        fn appending_points_never_makes_the_deepest_fall_shallower(
            values in equities(),
            appended in equities(),
        ) {
            let points: Vec<DatedEquity> = values
                .iter()
                .chain(&appended)
                .map(|&equity| DatedEquity { trade_date: TradeDate(0), equity: Money(equity) })
                .collect();
            let depth = |points: &[DatedEquity]| {
                account_drawdown(points).unwrap().deepest.map_or(0, |fall| fall.depth.0)
            };
            prop_assert!(depth(&points[..values.len()]) <= depth(&points));
        }
    }
}
