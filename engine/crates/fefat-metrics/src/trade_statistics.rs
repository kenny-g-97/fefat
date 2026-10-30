//! The statistics of a run's trades (`02` §7, step 2.11): how many won (profit and loss above
//! zero) and lost (below zero); the profit factor, what the winners made over what the losers
//! lost; the expectancy, the mean profit and loss, in the instrument's currency, in ticks of the
//! trade's lots, and in R over the trades with a stop; the average win and loss; and how much of
//! the range between a trade's worst and best marks its exit kept, over all trades. A statistic
//! with nothing to count is none: the profit factor without a losing trade, the expectancy without
//! a trade.

use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS};
use serde::Serialize;

use crate::inputs::{InstrumentUnits, TradeOutcome};
use crate::summation::compensated_sum;

/// The statistics of a run's trades, money in the instrument's currency.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct TradeStatistics {
    /// The trades.
    pub trades: usize,
    /// Those with a profit.
    pub wins: usize,
    /// Those with a loss.
    pub losses: usize,
    /// The wins over the trades.
    pub win_rate: Option<f64>,
    /// The winners' profit over the losers' loss.
    pub profit_factor: Option<f64>,
    /// The mean profit and loss.
    pub expectancy: Option<f64>,
    /// The mean profit and loss in ticks of each trade's lots.
    pub expectancy_ticks: Option<f64>,
    /// The mean profit and loss over the initial risk, of the trades with a stop (F-RND-02).
    pub expectancy_r: Option<f64>,
    /// The mean profit of the winners.
    pub average_win: Option<f64>,
    /// The mean loss of the losers, below zero.
    pub average_loss: Option<f64>,
    /// The trades' moves from their worst marks to their exits over the ranges from their worst
    /// marks to their best, summed in ticks: one when every trade left at the best mark it saw.
    pub mae_mfe_efficiency: Option<f64>,
}

/// The statistics of `trades`, on an instrument of `units`.
pub fn trade_statistics(trades: &[TradeOutcome], units: InstrumentUnits) -> TradeStatistics {
    let pnls = || trades.iter().map(|trade| i128::from(trade.pnl.0));
    let won: Vec<i128> = pnls().filter(|pnl| *pnl > 0).collect();
    let lost: Vec<i128> = pnls().filter(|pnl| *pnl < 0).collect();
    let (profit, loss) = (won.iter().sum::<i128>(), lost.iter().sum::<i128>());
    let risked: Vec<f64> = trades
        .iter()
        .filter_map(|trade| {
            let risk = trade.initial_risk?;
            Some(trade.pnl.0 as f64 / risk.0 as f64)
        })
        .collect();
    let in_ticks: Vec<f64> = trades
        .iter()
        .map(|trade| ticks(trade.pnl, trade, units))
        .collect();
    TradeStatistics {
        trades: trades.len(),
        wins: won.len(),
        losses: lost.len(),
        win_rate: ratio(won.len() as f64, trades.len() as f64),
        profit_factor: (!lost.is_empty()).then(|| profit as f64 / -loss as f64),
        expectancy: currency_mean(pnls().sum(), trades.len()),
        expectancy_ticks: mean(&in_ticks),
        expectancy_r: mean(&risked),
        average_win: currency_mean(profit, won.len()),
        average_loss: currency_mean(loss, lost.len()),
        mae_mfe_efficiency: efficiency(trades, units),
    }
}

/// `amount` of `trade` in ticks of its lots: the amount over the value of one tick for its lots.
fn ticks(amount: Money, trade: &TradeOutcome, units: InstrumentUnits) -> f64 {
    let tick_value = i128::from(units.tick_size.0)
        * i128::from(units.money_per_point.0)
        * i128::from(trade.lots.0);
    (i128::from(amount.0) * i128::from(PRICE_UNITS)) as f64 / tick_value as f64
}

/// The share of the trades' ranges from their worst marks to their best that their exits kept.
fn efficiency(trades: &[TradeOutcome], units: InstrumentUnits) -> Option<f64> {
    let ranges: i128 = trades
        .iter()
        .map(|trade| i128::from(trade.mae_ticks) + i128::from(trade.mfe_ticks))
        .sum();
    let kept = compensated_sum(
        trades
            .iter()
            .map(|trade| ticks(trade.gross_pnl, trade, units) + trade.mae_ticks as f64),
    );
    ratio(kept, ranges as f64)
}

/// `part` over `whole`, none over nothing.
fn ratio(part: f64, whole: f64) -> Option<f64> {
    (whole != 0.0).then(|| part / whole)
}

/// The mean of `values`, none without values.
fn mean(values: &[f64]) -> Option<f64> {
    ratio(compensated_sum(values.iter().copied()), values.len() as f64)
}

/// `total` micro-units over `count`, in units of the currency, none over no count.
fn currency_mean(total: i128, count: usize) -> Option<f64> {
    ratio(total as f64, count as f64 * MONEY_UNITS as f64)
}

#[cfg(test)]
mod tests {
    use fefat_core::fidelity::Fidelity;
    use fefat_core::instants::TradeDate;
    use fefat_core::orders::OrderRole;
    use fefat_core::units::{Price, Qty};

    use super::*;
    use crate::inputs::Hour;

    const ES: InstrumentUnits = InstrumentUnits {
        tick_size: Price(250_000_000),
        money_per_point: Money(50_000_000),
    };

    fn trade(pnl: i64, lots: i64, risk: Option<i64>, excursions: (i64, i64)) -> TradeOutcome {
        TradeOutcome {
            pnl: Money(pnl),
            gross_pnl: Money(pnl),
            lots: Qty(lots),
            initial_risk: risk.map(Money),
            mae_ticks: excursions.0,
            mfe_ticks: excursions.1,
            entry_trade_date: TradeDate(20_517),
            entry_hour: Hour::try_from(9).unwrap(),
            exit_reason: OrderRole::Stop,
            fidelity: Fidelity::Trades,
        }
    }

    #[test]
    fn two_wins_and_a_loss_of_es() {
        let trades = [
            trade(25_000_000, 1, Some(12_500_000), (0, 2)),
            trade(50_000_000, 2, None, (1, 2)),
            trade(-37_500_000, 1, Some(37_500_000), (3, 0)),
        ];
        let statistics = trade_statistics(&trades, ES);
        assert_eq!(
            (statistics.trades, statistics.wins, statistics.losses),
            (3, 2, 1)
        );
        assert_eq!(statistics.win_rate, Some(2.0 / 3.0));
        assert_eq!(statistics.profit_factor, Some(2.0));
        assert_eq!(statistics.expectancy, Some(12.5));
        assert_eq!(statistics.expectancy_ticks, Some((2.0 + 2.0 - 3.0) / 3.0));
        assert_eq!(statistics.expectancy_r, Some((2.0 - 1.0) / 2.0));
        assert_eq!(statistics.average_win, Some(37.5));
        assert_eq!(statistics.average_loss, Some(-37.5));
        assert_eq!(statistics.mae_mfe_efficiency, Some((2.0 + 3.0 + 0.0) / 8.0));
    }

    #[test]
    fn without_trades_nothing_is_counted() {
        let statistics = trade_statistics(&[], ES);
        assert_eq!(statistics.trades, 0);
        assert_eq!(statistics.win_rate, None);
        assert_eq!(statistics.profit_factor, None);
        assert_eq!(statistics.expectancy, None);
        assert_eq!(statistics.mae_mfe_efficiency, None);
    }

    #[test]
    fn without_a_losing_trade_there_is_no_profit_factor() {
        let statistics = trade_statistics(&[trade(1, 1, None, (0, 0))], ES);
        assert_eq!(statistics.profit_factor, None);
        assert_eq!(statistics.average_loss, None);
        assert_eq!(statistics.expectancy_r, None);
        assert_eq!(statistics.mae_mfe_efficiency, None);
    }
}
