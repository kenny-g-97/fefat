"""A saved run's market exposure and buy and hold (step 5.23, D-121, D-123), worked out from its
own artifacts, with no change to the engine or to the run and no read of the store.

The market is one lot of the instrument the run trades, held long: the unit a run's sizes count
in, a contract, or a coin of a crypto pair, of which the engine's lots are the dataset's steps. It
is valued at each decision's mark, the price the engine valued the account at, which the `equity`
artifact holds whether or not the run held a position, floored to the micro-unit as the engine
values a position (F-FEE-03), each roll's gap taken off from the roll's instant, its session's
open, after which the engine moves the mark by the gap (F-ROL-01, F-ROL-03), a decision at that
instant coming after it (F-CLK-02), so that a roll is no move of the market: a series anchored on
the run's first contract. While a roll's legs are on their way, the engine values the position at
the old contract's price, the mark less the gap, which those decisions' marks hold already, so the
roll's gap is not taken off them again: from the roll to the first fill on the contract rolled
from, the close leg or the order already on its way out, which the engine records on that
contract, or to the run's end where nothing filled after the roll and a position was held. A fill
is after the roll by the trade date the engine stamps it with, since a fill on a bar closing at
the session's open, as a calendar without a break between sessions has one, comes before the roll
at the roll's own instant (F-ROL-01). Before its first mark, the market stands at it, as one lot
bought there would.

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
engine's metrics measure a run's, on its account after each decision, the capital first. Where the
volatility counts, it is `sized`: beside one lot stand the lots whose days have the run's
volatility, the run's days' standard deviation over the market's, whose net P&L and drawdown are
one lot's times its lots, rounded to the micro-unit, and whose spell and Sharpe ratio are one
lot's, which no size changes, with its equity at that size at each decision `equity_curve` keeps,
for the chart; elsewhere it is `unsized`, with why.

    exposure = ff.backtest.market_exposure(run)
    exposure.all_days.correlation, exposure.all_days.beta_lots, exposure.buy_and_hold.at_one_lot
"""

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

import fefat_engine
import polars as pl
from pydantic import Field

from fefat.backtest.artifacts import read_artifact
from fefat.backtest.comoments import Comoments, DaysExposure, Exposure, Uncounted
from fefat.backtest.equity_curves import EQUITY_POINTS, downsampled_equity
from fefat.backtest.metrics import Metrics
from fefat.backtest.metrics_inputs import metrics_inputs_json
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
from fefat.market.roll_decisions import RollReason
from fefat.market.schema import FrozenModel

NANOSECONDS_A_SECOND = 1_000_000_000


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


class SizedBuyAndHold(FrozenModel):
    """One lot held from the run's first mark to its last, and as many lots as give its days the
    run's volatility, with that size's curve."""

    kind: Literal["sized"] = "sized"
    at_one_lot: BuyAndHoldFigures
    at_run_volatility: BuyAndHoldFigures
    curve: BuyAndHoldCurve


class UnsizedBuyAndHold(FrozenModel):
    """One lot held from the run's first mark to its last alone, `uncounted` saying why it has no
    size at the run's volatility."""

    kind: Literal["unsized"] = "unsized"
    at_one_lot: BuyAndHoldFigures
    uncounted: Uncounted


BuyAndHold = Annotated[SizedBuyAndHold | UnsizedBuyAndHold, Field(discriminator="kind")]
"""Buy and hold, sized at the run's volatility or not, told apart by `kind`."""


class MarketExposure(FrozenModel):
    """A run's market exposure over all its days, the days the market fell, and the days it rose,
    with buy and hold beside it (module docstring)."""

    all_days: Exposure
    falling_days: DaysExposure
    rising_days: DaysExposure
    buy_and_hold: BuyAndHold


class EngineRoll(FrozenModel):
    """A roll as the engine applied it, from the run's config (`roll_document`): the trade date its
    new front serves from in days since 1970-01-01, its session's open in nanoseconds since the
    epoch, the contracts, the gap in 1e-9 units, the new contract's price less the old one's, and
    why."""

    trade_date: int
    session_open: int
    rolled_from: str
    contract: str
    gap: int
    reason: RollReason


def market_exposure(run: Run, max_points: int = EQUITY_POINTS) -> MarketExposure:
    """`run`'s market exposure and buy and hold beside it (module docstring), buy and hold's curve
    at the decisions an equity curve of `max_points` keeps; refused for a run whose account no
    decision valued at a mark, and for fewer points than a curve keeps."""
    parameters = instrument_parameters(run.record.instrument)
    equity = read_artifact(run.folder, "equity")
    decisions = market_values(equity, run.fills, engine_rolls(run), parameters)
    if decisions.is_empty() or decisions.get_column("market").null_count() > 0:
        raise ValueError(
            f"Expected a mark at a decision of run {run.hash[:12]}, got none: its account was "
            "never valued at a tradeable price."
        )
    capital = micro_units(run.config.capital)
    kept = downsampled_equity(decisions, capital, max_points).get_column("ts")
    days = daily_moves(decisions, capital)
    moments = _moments_of(days)
    return MarketExposure(
        all_days=moments.exposure(),
        falling_days=_moments_of(days.filter(pl.col("market") < 0)).days_exposure(),
        rising_days=_moments_of(days.filter(pl.col("market") > 0)).days_exposure(),
        buy_and_hold=_buy_and_hold(run, decisions, moments, kept),
    )


def engine_rolls(run: Run) -> tuple[EngineRoll, ...]:
    """The rolls the engine applied in `run`, as its config holds them."""
    rolls = run.record.engine_config.get("rolls")
    if rolls is None:
        raise ValueError(f"Expected the rolls in the config of run {run.hash[:12]}, got none.")
    return tuple(EngineRoll.model_validate(dict(roll)) for roll in rolls)


def market_values(
    equity: pl.DataFrame,
    fills: pl.DataFrame,
    rolls: Sequence[EngineRoll],
    parameters: InstrumentParameters,
) -> pl.DataFrame:
    """The decisions of `equity`, a run's account after each, that value the account, as its
    metrics take them, `ts`, `trade_date`, and the run's `equity`, with `market`, one lot's value
    in micro-units at the market's level (module docstring), null throughout without a mark. A
    level in 1e-9 units times the money a point overflows int64, ES's at 5,000 reaching 2.5e20, so
    each value is worked out in Python's whole numbers, which Polars' would wrap."""
    valued = equity.filter(pl.col("equity").is_not_null())
    levels = valued.select(pl.col("mark") - _gaps_taken_off(valued, fills, rolls)).to_series()
    lot = Fraction(parameters.lot_step)
    worth, scale = parameters.money_per_point * lot.denominator, lot.numerator * PRICE_SCALE
    values = pl.Series(
        [None if level is None else level * worth // scale for level in levels.to_list()],
        dtype=pl.Int64,
    )
    marked = values.drop_nulls()
    market = values.fill_null(strategy="forward")
    if not marked.is_empty():
        market = market.fill_null(marked.item(0))
    return valued.select("ts", "trade_date", "equity").with_columns(market=market)


def _gaps_taken_off(
    decisions: pl.DataFrame, fills: pl.DataFrame, rolls: Sequence[EngineRoll]
) -> pl.Expr:
    """How far each decision's mark lies above the market's level, in 1e-9 units: the gaps of the
    rolls at or before its instant, but of a roll whose legs were on their way."""
    taken = pl.lit(0, dtype=pl.Int64)
    for roll in rolls:
        rolled = (pl.col("ts") >= roll.session_open) & ~_legs_on_their_way(decisions, fills, roll)
        taken = taken + pl.when(rolled).then(roll.gap).otherwise(0)
    return taken


def _legs_on_their_way(decisions: pl.DataFrame, fills: pl.DataFrame, roll: EngineRoll) -> pl.Expr:
    """The decisions from `roll` on whose marks the engine left at the old contract's price while
    the roll's legs were on their way (F-ROL-03): those before the first fill on the contract
    rolled from, which only the close leg or the order already on its way out makes after the
    roll, a fill's trade date placing it after the roll; or every one of them where nothing filled
    after the roll and the run held a position."""
    after = pl.col("ts") >= roll.session_open
    later = fills.filter(pl.col("trade_date").cast(pl.Int32) >= roll.trade_date)
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
    run: Run, decisions: pl.DataFrame, moments: Comoments, kept: pl.Series
) -> SizedBuyAndHold | UnsizedBuyAndHold:
    """Buy and hold over `decisions` at one lot, and, where the volatility counts, at the run's,
    with its curve at the instants `kept`."""
    capital = micro_units(run.config.capital)
    moved = pl.col("market") - decisions.item(0, "market")
    one_lot = _held_one_lot(run, decisions.select("trade_date", equity=moved + capital))
    why = moments.uncounted()
    if why is not None:
        return UnsizedBuyAndHold(at_one_lot=one_lot, uncounted=why)
    lots = moments.volatility_lots()
    shown = kept.to_frame("ts").join(
        decisions.select("ts", moved=moved), on="ts", validate="1:1", maintain_order="left"
    )
    equity = tuple((capital + lots * each) / MONEY_SCALE for each in shown.get_column("moved"))
    return SizedBuyAndHold(
        at_one_lot=one_lot,
        at_run_volatility=_at_lots(one_lot, lots),
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
