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
- `breakdowns`: the trades by exit reason, entry hour, weekday, year, and fidelity;
- `robustness`: the backtest-expert skill's summary (`08` §4, D-29), its five scores of 20, their
  total and verdict, and its red flags, as its `evaluate_backtest.py` gives them on the run's
  trades, win rate, average win and loss and drawdown in percent of the capital, years, and
  parameters, with the sample size the run reaches and its profit at one more tick of slippage.
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


class ScriptInputs(FrozenModel):
    """What the skill's script reads of a run, under its own names: the trades, the win rate in
    percent, the average win and loss and the maximum drawdown in percent of the capital, the
    years the window spans rounded to the nearest, the parameters (the numbers the execution
    template sets), and whether the run paid fees or slippage."""

    total_trades: int = Field(ge=0)
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    max_drawdown_pct: float
    years_tested: int = Field(ge=0)
    num_parameters: int = Field(ge=0)
    slippage_tested: bool


class DimensionName(StrEnum):
    """A dimension of the robustness summary, in the script's order."""

    SAMPLE_SIZE = "sample_size"
    EXPECTANCY = "expectancy"
    RISK_MANAGEMENT = "risk_management"
    ROBUSTNESS = "robustness"
    EXECUTION_REALISM = "execution_realism"


class Dimension(FrozenModel):
    """A dimension's score, out of 20."""

    name: DimensionName
    score: int = Field(ge=0, le=20)
    max_score: int


class Verdict(StrEnum):
    """The plain verdict of the total: 70 points or more, 40 or more, or fewer."""

    DEPLOY_GRADE_EVIDENCE = "deploy_grade_evidence"
    REFINE = "refine"
    ABANDON = "abandon"


class RedFlagId(StrEnum):
    """A red flag of the script's checklist."""

    SMALL_SAMPLE = "small_sample"
    NO_SLIPPAGE_TEST = "no_slippage_test"
    EXCESSIVE_DRAWDOWN = "excessive_drawdown"
    OVER_OPTIMIZED = "over_optimized"
    SHORT_TEST_PERIOD = "short_test_period"
    NEGATIVE_EXPECTANCY = "negative_expectancy"
    TOO_GOOD = "too_good"


class Severity(StrEnum):
    """How serious a red flag is."""

    HIGH = "high"
    MEDIUM = "medium"


class RedFlag(FrozenModel):
    """A red flag that fires, with the script's message."""

    id: RedFlagId
    severity: Severity
    message: str


class SampleSize(StrEnum):
    """Which of the skill's trade counts a run reaches: an absolute minimum of 30, 100
    preferred, and 200 for high confidence."""

    BELOW_MINIMUM = "below_minimum"
    MINIMUM = "minimum"
    PREFERRED = "preferred"
    HIGH_CONFIDENCE = "high_confidence"


class Robustness(FrozenModel):
    """The robustness summary of a run: what the script read, its five scores, their total and
    verdict, its red flags, the sample size the run reaches, the script's profit factor (none
    where the script's is infinite) and expectancy in percent of the capital per trade, and the
    profit and loss at one more tick of slippage, `fragile_to_slippage` when the run's profit is
    gone at it. The regimes a run covers arrive with step 11.4 (D-51)."""

    inputs: ScriptInputs
    dimensions: tuple[Dimension, Dimension, Dimension, Dimension, Dimension]
    total_score: int = Field(ge=0, le=100)
    verdict: Verdict
    red_flags: tuple[RedFlag, ...]
    sample_size: SampleSize
    profit_factor: float | None
    expectancy: float
    pnl_at_plus_one_tick: Decimal
    fragile_to_slippage: bool


class Metrics(FrozenModel):
    """A run's metrics (`02` §7), as `fefat_engine.metrics` works them out."""

    trades: TradeStatistics
    daily: DailyStatistics
    drawdown: DrawdownStatistics
    pnl: Decimal
    pnl_at_plus_one_tick: Decimal
    breakdowns: Breakdowns
    robustness: Robustness
