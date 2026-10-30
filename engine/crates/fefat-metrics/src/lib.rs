//! Performance metrics of a run (`02` §7, step 2.11): pure arithmetic over what
//! `crate::inputs::MetricsInputs` holds of a run's trades and its account, which the bindings
//! read as JSON, giving `Metrics`, which they write as JSON. Money sums and extremes are exact
//! micro-units, written as decimal text; means and ratios are floats, worked out with `libm` and
//! IEEE arithmetic alone, the same on every system, and none where nothing can be counted.

mod breakdowns;
mod daily_statistics;
pub mod drawdown;
pub mod inputs;
mod json_units;
mod normal;
mod summation;
mod trade_statistics;

use fefat_core::units::Money;
use serde::Serialize;

pub use crate::breakdowns::{Breakdowns, Outcome, Weekday};
pub use crate::daily_statistics::{DailyStatistics, DayPnl};
use crate::drawdown::{DrawdownStatistics, drawdown_statistics};
use crate::inputs::{MetricsError, MetricsInputs};
pub use crate::trade_statistics::TradeStatistics;

/// A run's metrics.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Metrics {
    /// The statistics of its trades.
    pub trades: TradeStatistics,
    /// The statistics of its days.
    pub daily: DailyStatistics,
    /// The drawdown of its account after each decision.
    pub drawdown: DrawdownStatistics,
    /// The profit and loss of its trades.
    #[serde(serialize_with = "json_units::money_text")]
    pub pnl: Money,
    /// The profit and loss of its trades with one more tick of slippage on each market and stop
    /// order (F-SLP-01).
    #[serde(serialize_with = "json_units::money_text")]
    pub pnl_at_plus_one_tick: Money,
    /// Its trades broken down.
    pub breakdowns: Breakdowns,
}

/// The metrics of the run `inputs` describe.
///
/// # Errors
///
/// [`MetricsError`] for inputs `MetricsInputs::check` refuses, or a sum beyond 64 bits.
pub fn compute(inputs: &MetricsInputs) -> Result<Metrics, MetricsError> {
    inputs.check()?;
    let pnl = inputs
        .trades
        .iter()
        .try_fold(Money(0), |total, trade| total.checked_add(trade.pnl))?;
    Ok(Metrics {
        trades: trade_statistics::trade_statistics(&inputs.trades, inputs.instrument),
        daily: daily_statistics::daily_statistics(
            inputs.capital,
            &inputs.equity,
            inputs.large_daily_loss,
            inputs.trials,
        )?,
        drawdown: drawdown_statistics(inputs.capital, &inputs.equity)?,
        pnl,
        pnl_at_plus_one_tick: inputs.pnl_at_plus_one_tick,
        breakdowns: breakdowns::breakdowns(&inputs.trades)?,
    })
}

#[cfg(test)]
mod tests {
    use serde_json::{Value, json};

    use super::*;

    fn inputs() -> Value {
        json!({
            "capital": 50_000_000_000_i64,
            "instrument": {"tick_size": 250_000_000, "money_per_point": 50_000_000},
            "trials": 1,
            "large_daily_loss": 20_000_000,
            "pnl_at_plus_one_tick": -12_500_000,
            "trades": [{
                "pnl": 25_000_000, "gross_pnl": 29_000_000, "lots": 1, "initial_risk": 150_000_000,
                "mae_ticks": 3, "mfe_ticks": 5, "entry_trade_date": "2026-03-06", "entry_hour": 9,
                "exit_reason": "target_1", "fidelity": "trades"
            }],
            "equity": [
                {"trade_date": "2026-03-06", "equity": 49_990_000_000_i64},
                {"trade_date": "2026-03-06", "equity": 50_025_000_000_i64}
            ]
        })
    }

    fn metrics_of(inputs: Value) -> Result<Value, MetricsError> {
        let inputs: MetricsInputs = serde_json::from_value(inputs).unwrap();
        Ok(serde_json::to_value(compute(&inputs)?).unwrap())
    }

    #[test]
    fn the_metrics_of_one_winning_trade_as_python_reads_them() {
        let metrics = metrics_of(inputs()).unwrap();
        assert_eq!(metrics["pnl"], "25.000000");
        assert_eq!(metrics["pnl_at_plus_one_tick"], "-12.500000");
        assert_eq!(metrics["trades"]["profit_factor"], Value::Null);
        assert_eq!(metrics["daily"]["worst_day"]["trade_date"], "2026-03-06");
        assert_eq!(
            metrics["daily"]["large_daily_loss_threshold"],
            "1000.000000"
        );
        assert_eq!(metrics["drawdown"]["max_drawdown"], "10.000000");
        let breakdowns = &metrics["breakdowns"];
        assert_eq!(breakdowns["exit_reason"]["target_1"]["trades"], 1);
        assert_eq!(breakdowns["hour"]["9"]["pnl"], "25.000000");
        assert_eq!(breakdowns["weekday"]["friday"]["wins"], 1);
        assert_eq!(breakdowns["year"]["2026"]["trades"], 1);
        assert_eq!(breakdowns["fidelity"]["trades"]["trades"], 1);
    }

    #[test]
    fn inputs_no_metric_can_be_worked_out_from_are_refused() {
        let mut without_capital = inputs();
        without_capital["capital"] = json!(0);
        let refused = metrics_of(without_capital).unwrap_err();
        assert_eq!(
            refused.to_string(),
            "Expected the capital above zero, got 0"
        );
        let mut out_of_order = inputs();
        out_of_order["equity"][1]["trade_date"] = json!("2026-03-05");
        let refused = metrics_of(out_of_order).unwrap_err();
        assert_eq!(
            refused.to_string(),
            "Expected the account's points in the order of their trade dates, got 2026-03-05 \
             after 2026-03-06"
        );
    }

    #[test]
    fn an_unknown_field_or_an_hour_past_23_is_refused_as_it_is_read() {
        let mut unknown = inputs();
        unknown["capital_usd"] = json!(50_000);
        assert!(serde_json::from_value::<MetricsInputs>(unknown).is_err());
        let mut late = inputs();
        late["trades"][0]["entry_hour"] = json!(24);
        let refused = serde_json::from_value::<MetricsInputs>(late).unwrap_err();
        assert!(
            refused
                .to_string()
                .contains("Expected an hour of the day from 0 to 23, got 24")
        );
    }
}
