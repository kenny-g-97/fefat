"""A saved run's market exposure and buy and hold (step 5.23, D-121, D-123), worked out from its
own artifacts, with no change to the engine or to the run and no read of the store.

The market is one lot of the instrument the run trades, held long, valued at each decision's mark,
the price the engine valued the account at, which the `equity` artifact holds whether or not the
run held a position, floored to the micro-unit as the engine values a position (F-FEE-03), each
roll's gap taken off from the trade date its new front serves from, so that a roll is no move of
the market: a series anchored on the run's first contract. While a roll's legs are on their way,
the engine values the position at the old contract's price, the mark less the gap (F-ROL-03),
which those decisions' marks hold already, so the roll's gap is not taken off them again: from the
roll to the first fill on the contract rolled from, the close leg or the order already on its way
out, which the engine records on that contract, or to the run's end where nothing filled after the
roll. Before its first mark, the market stands at it, as one lot bought there would.

Over the trade dates the run was valued on, the run's days as its metrics count them, the change of
its equity at each trade date's last decision, the first from the capital, and the market's, the
change of its value there, the first from its first mark, give the correlation; the beta in lots,
the covariance over the market's variance, the lots held long whose days the run's moved like, in
lots since a futures account's return in percent is of a capital that is only a reference; the
share of the run's variance the market explains, the correlation squared; the alpha in the
currency, the run's days summed less what the beta's lots of the market made over them; and the
correlation and the beta again over the days the market fell and over the days it rose. Each is
worked out in whole numbers and divided once. Where fewer than three days, a market whose days
never differed, or a run whose days never differed leave nothing to count, a figure is none and
`uncounted` says why; a run whose days never differed, as one that never trades, has a beta of no
lots and an alpha of its days summed.

Buy and hold is one lot held from the run's first mark to its last, paying no fee, slippage, or
funding: its net P&L, and its maximum drawdown, longest spell under a peak, and Sharpe ratio as the
engine's metrics measure a run's, on its account after each decision, the capital first; at one
lot, and at the lots whose days have the run's volatility, the run's days' standard deviation over
the market's, whose net P&L and drawdown are one lot's times its lots, rounded to the micro-unit,
and whose spell and Sharpe ratio are one lot's, which no size changes; with its equity at that size
at each decision `equity_curve` keeps, for the chart.

    exposure = ff.backtest.market_exposure(run)
    exposure.all_days.correlation, exposure.all_days.beta_lots, exposure.buy_and_hold.at_one_lot
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

import fefat_engine
import polars as pl
from pydantic import Field

from fefat.backtest.artifacts import read_artifact
from fefat.backtest.equity_curves import EQUITY_POINTS, downsampled_equity
from fefat.backtest.metrics import Metrics
from fefat.backtest.metrics_inputs import metrics_inputs_json
from fefat.backtest.record import RollRecord
from fefat.backtest.runs import Run
from fefat.backtest.schemas import FILLS, TRADES
from fefat.backtest.sides import UNREAD_TIME_ZONE
from fefat.market.engine_units import (
    MONEY_SCALE,
    PRICE_SCALE,
    InstrumentParameters,
    instrument_parameters,
    micro_units,
    money_text,
)
from fefat.market.schema import FrozenModel
from fefat.reference.units import price_units

FEWEST_DAYS = 3
"""The fewest days a correlation, a beta, or a volatility is counted over."""
NANOSECONDS_A_SECOND = 1_000_000_000


class Uncounted(StrEnum):
    """Why a figure of a market exposure is none."""

    TOO_FEW_DAYS = "too_few_days"
    """Fewer than `FEWEST_DAYS` days."""
    MARKET_NEVER_DIFFERED = "market_never_differed"
    """The market's days were all alike, so it has no variance to measure against."""
    RUN_NEVER_DIFFERED = "run_never_differed"
    """The run's days were all alike, as a run that never trades has them."""


class DaysExposure(FrozenModel):
    """How the run's days moved with the market's over `days` of them: the correlation and the
    beta in lots, each none where `uncounted` says why."""

    days: int = Field(ge=0)
    correlation: float | None
    beta_lots: float | None
    uncounted: Uncounted | None


class Exposure(DaysExposure):
    """How the run's days moved with the market's over all of them, with the share of the run's
    variance the market explains and the alpha in the currency, each none where `uncounted` says
    why."""

    explained_share: float | None
    alpha: float | None


class BuyAndHoldFigures(FrozenModel):
    """Buy and hold at `lots` (module docstring), money in the instrument's currency."""

    lots: float
    net_pnl: Decimal
    max_drawdown: Decimal
    longest_drawdown_days: int = Field(ge=0)
    sharpe: float | None


class BuyAndHoldCurve(FrozenModel):
    """Buy and hold's equity at the run's volatility at each decision the run's equity curve keeps
    (`equity_curve`), one entry a decision: its close in whole seconds since the epoch, as the
    run's curve is served, and the equity in the instrument's currency."""

    time: tuple[int, ...]
    equity: tuple[float, ...]


class BuyAndHold(FrozenModel):
    """One lot held from the run's first mark to its last, and as many lots as give its days the
    run's volatility, none with its curve where `uncounted` says why."""

    at_one_lot: BuyAndHoldFigures
    at_run_volatility: BuyAndHoldFigures | None
    uncounted: Uncounted | None
    curve: BuyAndHoldCurve | None


class MarketExposure(FrozenModel):
    """A run's market exposure over all its days, the days the market fell, and the days it rose,
    with buy and hold beside it (module docstring)."""

    all_days: Exposure
    falling_days: DaysExposure
    rising_days: DaysExposure
    buy_and_hold: BuyAndHold


@dataclass(frozen=True)
class Comoments:
    """The market's and the run's days, paired, in micro-units: their count, their sums, and each
    count times the sum of the products of their deviations from their means, the market's with
    itself, the run's with itself, and the two together, exact in whole numbers."""

    days: int
    market_sum: int
    run_sum: int
    market_variation: int
    run_variation: int
    covariation: int

    @classmethod
    def of(cls, market: Sequence[int], run: Sequence[int]) -> "Comoments":
        days, market_sum, run_sum = len(market), sum(market), sum(run)
        products = sum(moved * made for moved, made in zip(market, run, strict=True))
        return cls(
            days=days,
            market_sum=market_sum,
            run_sum=run_sum,
            market_variation=days * sum(moved * moved for moved in market) - market_sum**2,
            run_variation=days * sum(made * made for made in run) - run_sum**2,
            covariation=days * products - market_sum * run_sum,
        )

    def uncounted(self) -> Uncounted | None:
        """Why the correlation is none, or none where it is counted."""
        if self.days < FEWEST_DAYS:
            return Uncounted.TOO_FEW_DAYS
        if self.market_variation == 0:
            return Uncounted.MARKET_NEVER_DIFFERED
        if self.run_variation == 0:
            return Uncounted.RUN_NEVER_DIFFERED
        return None

    def beta(self) -> Fraction | None:
        """The covariance over the market's variance, exactly: none without three days and a
        market whose days differed."""
        if self.uncounted() in (Uncounted.TOO_FEW_DAYS, Uncounted.MARKET_NEVER_DIFFERED):
            return None
        return Fraction(self.covariation, self.market_variation)

    def explained(self) -> Fraction | None:
        """The correlation squared, exactly: none where the correlation is."""
        if self.uncounted() is not None:
            return None
        return Fraction(self.covariation**2, self.market_variation * self.run_variation)

    def correlation(self) -> float | None:
        """The square root of `explained` with the covariance's sign."""
        explained = self.explained()
        if explained is None:
            return None
        return math.copysign(math.sqrt(explained), self.covariation)

    def alpha(self) -> float | None:
        """The run's days summed less what the beta's lots of the market made over them, in the
        currency."""
        beta = self.beta()
        if beta is None:
            return None
        return float((self.run_sum - beta * self.market_sum) / MONEY_SCALE)

    def volatility_lots(self) -> float | None:
        """The lots whose days have the run's standard deviation, the run's over the market's:
        none where the correlation is."""
        if self.uncounted() is not None:
            return None
        return math.sqrt(Fraction(self.run_variation, self.market_variation))

    def days_exposure(self) -> DaysExposure:
        beta = self.beta()
        return DaysExposure(
            days=self.days,
            correlation=self.correlation(),
            beta_lots=None if beta is None else float(beta),
            uncounted=self.uncounted(),
        )

    def exposure(self) -> Exposure:
        explained = self.explained()
        return Exposure(
            **dict(self.days_exposure()),
            explained_share=None if explained is None else float(explained),
            alpha=self.alpha(),
        )


def market_exposure(run: Run, max_points: int = EQUITY_POINTS) -> MarketExposure:
    """`run`'s market exposure and buy and hold beside it (module docstring), buy and hold's curve
    at the decisions an equity curve of `max_points` keeps; refused for a run whose account no
    decision valued at a mark."""
    parameters = instrument_parameters(run.record.instrument)
    equity = read_artifact(run.folder, "equity")
    decisions = market_values(equity, run.fills, run.record.rolls, parameters)
    if decisions.is_empty() or decisions.get_column("market").null_count() > 0:
        raise ValueError(
            f"Expected a mark at a decision of run {run.hash[:12]}, got none: its account was "
            "never valued at a tradeable price."
        )
    days = daily_moves(decisions, micro_units(run.config.capital))
    moments = _moments_of(days)
    return MarketExposure(
        all_days=moments.exposure(),
        falling_days=_moments_of(days.filter(pl.col("market") < 0)).days_exposure(),
        rising_days=_moments_of(days.filter(pl.col("market") > 0)).days_exposure(),
        buy_and_hold=_buy_and_hold(run, decisions, moments, max_points),
    )


def market_values(
    equity: pl.DataFrame,
    fills: pl.DataFrame,
    rolls: Sequence[RollRecord],
    parameters: InstrumentParameters,
) -> pl.DataFrame:
    """The decisions of `equity`, a run's account after each, that value the account, as its
    metrics take them, `ts`, `trade_date`, and the run's `equity`, with `market`, one lot's value
    in micro-units at the market's level (module docstring), null throughout without a mark."""
    valued = equity.filter(pl.col("equity").is_not_null())
    levels = valued.select(pl.col("mark") - _gaps_taken_off(valued, fills, rolls)).to_series()
    worth = parameters.money_per_point
    values = pl.Series(
        [None if level is None else level * worth // PRICE_SCALE for level in levels.to_list()],
        dtype=pl.Int64,
    )
    marked = values.drop_nulls()
    market = values.fill_null(strategy="forward")
    if not marked.is_empty():
        market = market.fill_null(marked.item(0))
    return valued.select("ts", "trade_date", "equity").with_columns(market=market)


def _gaps_taken_off(
    decisions: pl.DataFrame, fills: pl.DataFrame, rolls: Sequence[RollRecord]
) -> pl.Expr:
    """How far each decision's mark lies above the market's level, in 1e-9 units: the gaps of the
    rolls from whose trade date on it was valued, but of a roll whose legs were on their way."""
    taken = pl.lit(0, dtype=pl.Int64)
    for roll in rolls:
        rolled = (pl.col("trade_date") >= roll.trade_date) & ~_legs_on_their_way(
            decisions, fills, roll
        )
        gap = price_units(format(roll.gap, "f"))
        taken = taken + pl.when(rolled).then(gap).otherwise(0)
    return taken


def _legs_on_their_way(decisions: pl.DataFrame, fills: pl.DataFrame, roll: RollRecord) -> pl.Expr:
    """The decisions from `roll` on whose marks the engine left at the old contract's price while
    the roll's legs were on their way (F-ROL-03): those before the first fill on the contract
    rolled from, which only the close leg or the order already on its way out makes after the
    roll; or every one of them where nothing filled after the roll and the run held a position."""
    after = pl.col("trade_date") >= roll.trade_date
    later = fills.filter(pl.col("trade_date") >= roll.trade_date)
    closing = later.filter(pl.col("contract") == roll.rolled_from).get_column("ts")
    if not closing.is_empty():
        return after & (pl.col("ts") < closing.min())
    held = decisions.filter(after & (pl.col("position") != 0))
    return after & pl.lit(later.is_empty() and not held.is_empty())


def daily_moves(decisions: pl.DataFrame, capital: int) -> pl.DataFrame:
    """The run's and the market's days, `trade_date`, `run`, and `market`, in micro-units: the
    change of each at the trade date's last decision, the run's first from `capital` and the
    market's from its first mark."""
    first = decisions.item(0, "market")
    lasts = decisions.group_by("trade_date", maintain_order=True).agg(
        pl.col("equity", "market").last()
    )
    return lasts.select(
        "trade_date",
        run=pl.col("equity") - pl.col("equity").shift(1, fill_value=capital),
        market=pl.col("market") - pl.col("market").shift(1, fill_value=first),
    )


def _moments_of(days: pl.DataFrame) -> Comoments:
    return Comoments.of(days.get_column("market").to_list(), days.get_column("run").to_list())


def _buy_and_hold(
    run: Run, decisions: pl.DataFrame, moments: Comoments, max_points: int
) -> BuyAndHold:
    """Buy and hold over `decisions` at one lot and at the run's volatility, with its curve."""
    capital = micro_units(run.config.capital)
    moved = pl.col("market") - decisions.item(0, "market")
    one_lot = _held_one_lot(run, decisions.select("trade_date", equity=moved + capital))
    lots = moments.volatility_lots()
    if lots is None:
        why = moments.uncounted()
        return BuyAndHold(at_one_lot=one_lot, at_run_volatility=None, uncounted=why, curve=None)
    kept = downsampled_equity(decisions, capital, max_points).select("ts")
    shown = kept.join(
        decisions.select("ts", moved=moved), on="ts", validate="1:1", maintain_order="left"
    )
    equity = tuple((capital + lots * each) / MONEY_SCALE for each in shown.get_column("moved"))
    return BuyAndHold(
        at_one_lot=one_lot,
        at_run_volatility=_at_lots(one_lot, lots),
        uncounted=None,
        curve=BuyAndHoldCurve(
            time=tuple((shown.get_column("ts") // NANOSECONDS_A_SECOND).to_list()),
            equity=equity,
        ),
    )


def _held_one_lot(run: Run, walk: pl.DataFrame) -> BuyAndHoldFigures:
    """One lot held over `walk`, its account after each decision, as the engine's metrics measure
    a run's: an account without trades, whose drawdown, spell under a peak, and days no trade's
    figures touch."""
    capital = micro_units(run.config.capital)
    document = metrics_inputs_json(
        {
            "trades": pl.DataFrame(schema=TRADES),
            "fills": pl.DataFrame(schema=FILLS),
            "equity": walk,
        },
        capital=capital,
        instrument=instrument_parameters(run.record.instrument),
        window=run.record.window,
        time_zone=UNREAD_TIME_ZONE,
        pnl_at_plus_one_tick=0,
        parameters=0,
        friction_tested=False,
    )
    metrics = Metrics.model_validate_json(fefat_engine.metrics(document))
    return BuyAndHoldFigures(
        lots=1.0,
        net_pnl=Decimal(money_text(walk.item(-1, "equity") - capital)),
        max_drawdown=metrics.drawdown.max_drawdown,
        longest_drawdown_days=metrics.drawdown.longest_drawdown_days,
        sharpe=metrics.daily.sharpe,
    )


def _at_lots(one_lot: BuyAndHoldFigures, lots: float) -> BuyAndHoldFigures:
    """`one_lot` at `lots`: its money times the lots, rounded to the micro-unit, half to even, and
    its spell and Sharpe ratio its own, since a walk scaled by a positive size keeps its peaks and
    its mean over its deviation."""
    return BuyAndHoldFigures(
        lots=lots,
        net_pnl=_times(one_lot.net_pnl, lots),
        max_drawdown=_times(one_lot.max_drawdown, lots),
        longest_drawdown_days=one_lot.longest_drawdown_days,
        sharpe=one_lot.sharpe,
    )


def _times(amount: Decimal, lots: float) -> Decimal:
    return Decimal(money_text(round(micro_units(amount) * lots)))
