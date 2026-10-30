//! A run's trades broken down (`02` §7, step 2.11): by exit reason, the role of the fill that left
//! each flat (F-TAG-01); by the hour of its entry's fill in its exchange's time zone; by the
//! weekday and the year of its entry's trade date (`02` §1.3); and by the fidelity its entry
//! filled on, the fidelity era it belongs to. Each group counts its trades and wins and sums
//! their profit and loss.

use std::collections::BTreeMap;

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::TradeDate;
use fefat_core::orders::OrderRole;
use fefat_core::strategy_spec::Weekday;
use fefat_core::units::{Money, Overflow};
use serde::Serialize;

use crate::inputs::{Hour, TradeOutcome};
use crate::json_units;

/// A run's trades broken down five ways, each group in its key's order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Breakdowns {
    /// By the role of the fill that left the trade flat.
    pub exit_reason: BTreeMap<OrderRole, Outcome>,
    /// By the hour of the entry's fill in the exchange's time zone.
    pub hour: BTreeMap<Hour, Outcome>,
    /// By the weekday of the entry's trade date.
    pub weekday: BTreeMap<Weekday, Outcome>,
    /// By the year of the entry's trade date.
    pub year: BTreeMap<i64, Outcome>,
    /// By the fidelity the entry filled on.
    pub fidelity: BTreeMap<Fidelity, Outcome>,
}

/// A group of trades: how many, how many won, and their profit and loss.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Outcome {
    /// The trades.
    pub trades: usize,
    /// Those with a profit.
    pub wins: usize,
    /// Their profit and loss.
    #[serde(serialize_with = "json_units::money_text")]
    pub pnl: Money,
}

impl Outcome {
    /// A group before its first trade.
    const EMPTY: Self = Self {
        trades: 0,
        wins: 0,
        pnl: Money(0),
    };
}

/// The weekday of `date`: 1970-01-01, day zero, was a Thursday.
const fn weekday_of(date: TradeDate) -> Weekday {
    match (date.0 as i64 + 3).rem_euclid(7) {
        0 => Weekday::Monday,
        1 => Weekday::Tuesday,
        2 => Weekday::Wednesday,
        3 => Weekday::Thursday,
        4 => Weekday::Friday,
        5 => Weekday::Saturday,
        _ => Weekday::Sunday,
    }
}

/// `trades` broken down five ways.
///
/// # Errors
///
/// [`Overflow`] when a group's profit and loss does not fit in 64 bits.
pub fn breakdowns(trades: &[TradeOutcome]) -> Result<Breakdowns, Overflow> {
    Ok(Breakdowns {
        exit_reason: grouped(trades, |trade| trade.exit_reason)?,
        hour: grouped(trades, |trade| trade.entry_hour)?,
        weekday: grouped(trades, |trade| weekday_of(trade.entry_trade_date))?,
        year: grouped(trades, |trade| trade.entry_trade_date.year_month_day().0)?,
        fidelity: grouped(trades, |trade| trade.fidelity)?,
    })
}

fn grouped<K: Ord>(
    trades: &[TradeOutcome],
    key: impl Fn(&TradeOutcome) -> K,
) -> Result<BTreeMap<K, Outcome>, Overflow> {
    let mut groups: BTreeMap<K, Outcome> = BTreeMap::new();
    for trade in trades {
        let group = groups.entry(key(trade)).or_insert(Outcome::EMPTY);
        group.trades += 1;
        group.wins += usize::from(trade.pnl.0 > 0);
        group.pnl = group.pnl.checked_add(trade.pnl)?;
    }
    Ok(groups)
}

#[cfg(test)]
mod tests {
    use fefat_core::units::Qty;

    use super::*;

    fn trade(pnl: i64, date: &str, hour: u8, exit_reason: OrderRole) -> TradeOutcome {
        TradeOutcome {
            pnl: Money(pnl),
            gross_pnl: Money(pnl),
            lots: Qty(1),
            initial_risk: None,
            mae_ticks: 0,
            mfe_ticks: 0,
            entry_trade_date: date.parse().unwrap(),
            entry_hour: Hour::try_from(hour).unwrap(),
            exit_reason,
            fidelity: Fidelity::Trades,
        }
    }

    #[test]
    fn the_weekday_of_a_trade_date() {
        assert_eq!(weekday_of(TradeDate(0)), Weekday::Thursday);
        assert_eq!(weekday_of("2026-03-09".parse().unwrap()), Weekday::Monday);
        assert_eq!(weekday_of("2026-03-08".parse().unwrap()), Weekday::Sunday);
        assert_eq!(weekday_of(TradeDate(-1)), Weekday::Wednesday);
    }

    #[test]
    fn each_group_counts_its_trades_and_wins_and_sums_their_pnl() {
        let trades = [
            trade(10, "2025-12-31", 9, OrderRole::Stop),
            trade(-4, "2026-01-05", 9, OrderRole::Stop),
            trade(7, "2026-01-05", 14, OrderRole::Entry),
        ];
        let broken = breakdowns(&trades).unwrap();
        let stop = Outcome {
            trades: 2,
            wins: 1,
            pnl: Money(6),
        };
        assert_eq!(broken.exit_reason.get(&OrderRole::Stop), Some(&stop));
        assert_eq!(broken.exit_reason.keys().next(), Some(&OrderRole::Entry));
        assert_eq!(broken.hour.len(), 2);
        assert_eq!(broken.year.get(&2025).map(|year| year.pnl), Some(Money(10)));
        assert_eq!(broken.year.get(&2026).map(|year| year.trades), Some(2));
        let weekdays: Vec<Weekday> = broken.weekday.keys().copied().collect();
        assert_eq!(weekdays, [Weekday::Monday, Weekday::Wednesday]);
        assert_eq!(
            broken.fidelity.get(&Fidelity::Trades).map(|all| all.trades),
            Some(3)
        );
    }
}
