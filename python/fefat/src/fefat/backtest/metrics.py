"""A run's metrics (step 2.11, `02` §7), worked out by the Rust engine's `fefat-metrics` from the
run's trades and its account, and read here as frozen models: money sums and extremes as exact
decimals of the instrument's currency, means and ratios as floats, and none where nothing can be
counted, such as the profit factor of a run without a losing trade.

- `trades`: the trades, wins (profit above zero), losses (below zero), win rate, profit factor,
  expectancy in currency, in ticks, and in R, average win and loss, and the MAE/MFE efficiency;
- `daily`: the daily profit and loss by the session table's trade date, its worst day, the best
  day's share of the profit, the daily CVaR at 95 %, the large daily losses, and the Sharpe,
  Sortino, probabilistic, and deflated Sharpe ratios;
- `drawdown`: the deepest fall of the account after each decision below a peak, in money and as a
  share of the capital, its peak's and trough's trade dates, and the longest spell under a peak;
- `pnl` and `pnl_at_plus_one_tick`, the run's and its rerun's at one more tick of slippage;
- `breakdowns`: the trades by exit reason, entry hour, weekday, year, and fidelity.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

import fefat_engine
import polars as pl
from pydantic import Field

from fefat.backtest.run_config import FidelityText
from fefat.market.schema import FrozenModel
from fefat.reference.orders import OrderRole


def running_drawdown(equity: pl.Series) -> pl.Series:
    """How far each value of `equity`, an account's equity in order, lies below the highest value
    before it or at it, in its units: zero at each new peak, and at the first value. The engine
    reads the series in place, a slice without the values around it, and refuses one that is not
    int64 (TypeError) or holds nulls (ValueError), and a fall beyond int64 (OverflowError)."""
    return pl.Series(equity.name, fefat_engine.running_drawdown(equity), dtype=pl.Int64)


class TradeStatistics(FrozenModel):
    """The statistics of a run's trades, money in the instrument's currency."""

    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    expectancy_ticks: float | None
    expectancy_r: float | None
    average_win: float | None
    average_loss: float | None
    mae_mfe_efficiency: float | None


class DayPnl(FrozenModel):
    """A trade date's profit and loss."""

    trade_date: date
    pnl: Decimal


class DailyStatistics(FrozenModel):
    """The statistics of a run's days: a day's profit and loss is the change of the equity at
    its trade date's last decision, the first day's from the capital."""

    days: int = Field(ge=0)
    worst_day: DayPnl | None
    best_day_share: float | None
    cvar_95: float | None
    large_daily_losses: int = Field(ge=0)
    large_daily_loss_frequency: float | None
    large_daily_loss_threshold: Decimal
    sharpe: float | None
    sortino: float | None
    probabilistic_sharpe: float | None
    deflated_sharpe: float | None
    trials: int = Field(ge=1)


class DrawdownStatistics(FrozenModel):
    """The deepest fall of the account below a peak, and its longest spell under one."""

    max_drawdown: Decimal
    max_drawdown_share: float
    peak: date | None
    trough: date | None
    longest_drawdown_days: int = Field(ge=0)


class Outcome(FrozenModel):
    """A group of trades: how many, how many won, and their profit and loss."""

    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    pnl: Decimal


class Weekday(StrEnum):
    """A day of the week."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


Hour = Annotated[int, Field(ge=0, le=23)]
"""An hour of the day in the exchange's time zone."""


class Breakdowns(FrozenModel):
    """A run's trades by the role of the fill that left them flat (F-TAG-01), the hour of their
    entry's fill in the exchange's time zone, the weekday and the year of their entry's trade
    date, and the fidelity their entry filled on."""

    exit_reason: dict[OrderRole, Outcome]
    hour: dict[Hour, Outcome]
    weekday: dict[Weekday, Outcome]
    year: dict[int, Outcome]
    fidelity: dict[FidelityText, Outcome]


class Metrics(FrozenModel):
    """A run's metrics (`02` §7), as `fefat_engine.metrics` works them out."""

    trades: TradeStatistics
    daily: DailyStatistics
    drawdown: DrawdownStatistics
    pnl: Decimal
    pnl_at_plus_one_tick: Decimal
    breakdowns: Breakdowns
