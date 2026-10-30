//! What a run's metrics read (step 2.11): its closed trades (`docs/spec/fill-semantics.md` §20),
//! each with the labels its breakdowns group it by; its account after each decision, with the
//! decision's trade date, by which its daily profit and loss counts (`02` §1.3); its capital; its
//! instrument's tick and point value; the trials behind it, which deflate its Sharpe ratio; the
//! share of the capital a day must lose to be a large daily loss; and the profit and loss of its
//! rerun at one more tick of slippage. `fefat.backtest.metrics_inputs` writes them as JSON, in the
//! units of `crate::json_units`, trade dates as `2026-03-05`.

use std::num::NonZeroU32;

use fefat_core::costs::Rate;
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::TradeDate;
use fefat_core::orders::OrderRole;
use fefat_core::units::{Money, Overflow, Price, Qty};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::drawdown::DatedEquity;
use crate::json_units;

/// What a run's metrics read.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MetricsInputs {
    /// The run's capital, its equity before its first decision (D-51).
    #[serde(deserialize_with = "json_units::money")]
    pub capital: Money,
    /// The instrument's tick and point value.
    pub instrument: InstrumentUnits,
    /// The trials of which this run is the one kept, one for a run on its own (`02` §9).
    pub trials: NonZeroU32,
    /// The share of the capital a day must lose to be a large daily loss, in 1e-9 units.
    #[serde(deserialize_with = "json_units::rate")]
    pub large_daily_loss: Rate,
    /// The profit and loss of the run's trades with one more tick of slippage on each market and
    /// stop order (F-SLP-01).
    #[serde(deserialize_with = "json_units::money")]
    pub pnl_at_plus_one_tick: Money,
    /// The trade dates the run's signal bars span.
    pub window: Window,
    /// The parameters of its strategy.
    pub parameters: u32,
    /// Whether it paid fees or slippage.
    pub friction_tested: bool,
    /// The trades, in the order they closed.
    pub trades: Vec<TradeOutcome>,
    /// The account after each decision that values it, in their order.
    pub equity: Vec<DatedEquity>,
}

/// The trade dates a run's signal bars span, from `start` to `end`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Window {
    /// The first.
    pub start: TradeDate,
    /// The last.
    pub end: TradeDate,
}

impl Window {
    /// The calendar years it spans, rounded to the nearest: its days, both ends counted, over
    /// 365.25.
    pub fn years(self) -> u32 {
        let days = f64::from(self.end.0) - f64::from(self.start.0) + 1.0;
        (days / 365.25 + 0.5).floor() as u32
    }
}

/// An instrument's tick and the money one lot gains or loses when the price moves one point.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InstrumentUnits {
    /// The tick, in 1e-9 units of price.
    #[serde(deserialize_with = "json_units::price")]
    pub tick_size: Price,
    /// The money per point and lot, in micro-units.
    #[serde(deserialize_with = "json_units::money")]
    pub money_per_point: Money,
}

/// A closed trade as the metrics read it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TradeOutcome {
    /// Its profit and loss, its gross less its fees plus its funding (§20).
    #[serde(deserialize_with = "json_units::money")]
    pub pnl: Money,
    /// What its fills' values moved the cash by, before fees and funding.
    #[serde(deserialize_with = "json_units::money")]
    pub gross_pnl: Money,
    /// Its entry's lots.
    #[serde(deserialize_with = "json_units::lots")]
    pub lots: Qty,
    /// What its entry's lots lose from the entry to the stop, none without a stop (F-RND-02).
    #[serde(deserialize_with = "json_units::optional_money")]
    pub initial_risk: Option<Money>,
    /// The farthest the marks went against it, in whole ticks.
    pub mae_ticks: i64,
    /// The farthest the marks went for it, in whole ticks.
    pub mfe_ticks: i64,
    /// The trade date of its entry's fill.
    pub entry_trade_date: TradeDate,
    /// The hour of its entry's fill in its exchange's time zone.
    pub entry_hour: Hour,
    /// The role of the fill that left it flat (F-TAG-01).
    pub exit_reason: OrderRole,
    /// The fidelity its entry filled on (F-TAG-01).
    pub fidelity: Fidelity,
}

/// An hour of the day, from 0 to 23.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
pub struct Hour(u8);

/// A number that is no hour of the day.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[error("Expected an hour of the day from 0 to 23, got {0}")]
pub struct NoHour(u8);

impl TryFrom<u8> for Hour {
    type Error = NoHour;

    fn try_from(hour: u8) -> Result<Self, Self::Error> {
        if hour < 24 {
            Ok(Self(hour))
        } else {
            Err(NoHour(hour))
        }
    }
}

impl From<Hour> for u8 {
    fn from(hour: Hour) -> Self {
        hour.0
    }
}

/// What the metrics refuse to read.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum MetricsError {
    /// A capital, a tick, a point value, a rate, or a trade's lots at or below zero.
    #[error("Expected {what} above zero, got {value}")]
    NotAboveZero {
        /// What it is, such as `the capital`.
        what: &'static str,
        /// Its value in its units.
        value: i64,
    },
    /// A trade's excursion below zero.
    #[error("Expected {what} at or above zero, got {value}")]
    BelowZero {
        /// What it is, such as `a trade's adverse excursion`.
        what: &'static str,
        /// Its value, in ticks.
        value: i64,
    },
    /// A window that ends before it starts.
    #[error("Expected a window that ends on or after its start, {start}, got {end}")]
    WindowBackwards {
        /// Its first trade date.
        start: TradeDate,
        /// Its last.
        end: TradeDate,
    },
    /// The account's points out of the order of their trade dates.
    #[error(
        "Expected the account's points in the order of their trade dates, got {next} after {previous}"
    )]
    EquityOutOfOrder {
        /// The earlier point's trade date.
        previous: TradeDate,
        /// The later point's.
        next: TradeDate,
    },
    /// An amount beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
}

impl MetricsInputs {
    /// Refuses inputs no metric can be worked out from: a capital, a tick, a point value, a
    /// large daily loss's share, or a trade's lots or initial risk at or below zero, a trade's
    /// excursion below zero, the account's points out of the order of their trade dates, and a
    /// window that ends before it starts.
    pub fn check(&self) -> Result<(), MetricsError> {
        self.check_amounts()?;
        self.check_excursions()?;
        self.check_order()
    }

    /// The capital, the tick, the point value, the share, and each trade's lots and initial risk
    /// above zero.
    fn check_amounts(&self) -> Result<(), MetricsError> {
        let units = self.instrument;
        let settings = [
            ("the capital", self.capital.0),
            ("the tick size", units.tick_size.0),
            ("the money per point", units.money_per_point.0),
            ("the share of a large daily loss", self.large_daily_loss.0),
        ];
        let trades = self.trades.iter().flat_map(|trade| {
            let risk = trade
                .initial_risk
                .map(|risk| ("a trade's initial risk", risk.0));
            std::iter::once(("a trade's lots", trade.lots.0)).chain(risk)
        });
        let mut amounts = settings.into_iter().chain(trades);
        match amounts.find(|(_, value)| *value <= 0) {
            Some((what, value)) => Err(MetricsError::NotAboveZero { what, value }),
            None => Ok(()),
        }
    }

    /// Each trade's excursions at or above zero.
    fn check_excursions(&self) -> Result<(), MetricsError> {
        let mut excursions = self.trades.iter().flat_map(|trade| {
            [
                ("a trade's adverse excursion", trade.mae_ticks),
                ("a trade's favourable excursion", trade.mfe_ticks),
            ]
        });
        match excursions.find(|(_, value)| *value < 0) {
            Some((what, value)) => Err(MetricsError::BelowZero { what, value }),
            None => Ok(()),
        }
    }

    /// The account's points in the order of their trade dates, and the window forward.
    fn check_order(&self) -> Result<(), MetricsError> {
        let out_of_order = self.equity.windows(2).find_map(|pair| match pair {
            [earlier, later] if later.trade_date < earlier.trade_date => {
                Some((earlier.trade_date, later.trade_date))
            }
            _ => None,
        });
        if let Some((previous, next)) = out_of_order {
            return Err(MetricsError::EquityOutOfOrder { previous, next });
        }
        let Window { start, end } = self.window;
        if end < start {
            return Err(MetricsError::WindowBackwards { start, end });
        }
        Ok(())
    }
}
