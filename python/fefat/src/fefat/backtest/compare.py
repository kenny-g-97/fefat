"""Saved runs side by side (step 5.10, D-93, D-126): each run's figures, those of the run page's
KPI cards but the fidelity split, with what each differs by from the first run's, the reference;
each run's trades by the exit reason that left them flat, beside the reference's; and each run's
equity at each trade date's end over its capital, a share that is 1 at the capital, so that runs
of other capital lie on one axis. Every figure is the run's record's, every delta the difference of
two of them, so that the comparison recomputes nothing a run's page shows.

    comparison = ff.backtest.compare_runs([reference, other])
    comparison.runs[1].deltas.pnl, comparison.runs[1].curve.shares
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field

from fefat.backtest.metrics import Outcome
from fefat.backtest.record import Window
from fefat.backtest.runs import DAILY, Run
from fefat.market.engine_units import micro_units
from fefat.market.instruments import Currency
from fefat.market.schema import FrozenModel, frozen
from fefat.reference.orders import OrderRole
from fefat.strategy.signal_strategy import StrategyPin

FEWEST_RUNS = 2
MOST_RUNS = 4


class RunFigures(FrozenModel):
    """A run's figures as its KPI cards show them (step 5.7), money in its currency and the shares
    fractions of its capital, 0.025 being 2.5 %; or what a run's figures differ by from the
    reference's, each none where either run's is none."""

    pnl: Decimal
    pnl_share: float
    profit_factor: float | None
    expectancy_r: float | None
    win_rate: float | None
    max_drawdown: Decimal
    max_drawdown_share: float
    sharpe: float | None
    trades: int


class OutcomeDelta(FrozenModel):
    """What a run's trades of one exit reason differ by from the reference's."""

    trades: int
    wins: int
    pnl: Decimal


class ShareCurve(FrozenModel):
    """A run's equity at the end of each trade date it was valued on, over its capital."""

    trade_dates: tuple[date, ...]
    shares: tuple[float, ...]


class ComparedRun(FrozenModel):
    """A run in a comparison: what it is, its figures, its trades by exit reason over every
    reason of the comparison, none where it closed no trade by one, and its equity's curve; and,
    but for the reference, what its figures and its trades by exit reason differ by."""

    run_key: str
    strategy: StrategyPin | None
    instrument: str
    timeframe: str
    currency: Currency
    capital: Decimal
    window: Window
    figures: RunFigures
    deltas: RunFigures | None
    exit_reasons: Annotated[Mapping[OrderRole, Outcome], AfterValidator(frozen)]
    exit_reason_deltas: Annotated[Mapping[OrderRole, OutcomeDelta], AfterValidator(frozen)] | None
    curve: ShareCurve


class RunComparison(FrozenModel):
    """Two to four runs, the first the reference, and the exit reasons any of them closed a trade
    by, in the order of `OrderRole`."""

    exit_reasons: tuple[OrderRole, ...]
    runs: tuple[ComparedRun, ...] = Field(min_length=FEWEST_RUNS, max_length=MOST_RUNS)


def compare_runs(runs: Sequence[Run]) -> RunComparison:
    """`runs` side by side, the first the reference (module docstring): refused unless they are two
    to four different runs in one currency, whose money could not be set side by side."""
    _require_comparable(runs)
    return side_by_side(runs, tuple(share_curve(run) for run in runs))


def side_by_side(runs: Sequence[Run], curves: Sequence[ShareCurve]) -> RunComparison:
    """`runs` side by side with `curves`, each its run's `share_curve`, which a caller that reads
    each run's files under a guard of its own reads apart, as the app does; refused as
    `compare_runs` refuses."""
    _require_comparable(runs)
    if len(curves) != len(runs):
        raise ValueError(f"Expected a curve for each of the {len(runs)} runs, got {len(curves)}.")
    reasons = tuple(
        role
        for role in OrderRole
        if any(role in run.metrics.breakdowns.exit_reason for run in runs)
    )
    reference = _compared(runs[0], curves[0], reasons, reference=None)
    others = tuple(
        _compared(run, curve, reasons, reference)
        for run, curve in zip(runs[1:], curves[1:], strict=True)
    )
    return RunComparison(exit_reasons=reasons, runs=(reference, *others))


def _require_comparable(runs: Sequence[Run]) -> None:
    if not FEWEST_RUNS <= len(runs) <= MOST_RUNS:
        raise ValueError(f"Expected {FEWEST_RUNS} to {MOST_RUNS} runs to compare, got {len(runs)}.")
    keys = [run.hash for run in runs]
    for key in keys:
        if keys.count(key) > 1:
            raise ValueError(f"Expected different runs to compare, got run {key[:12]} twice.")
    currencies = sorted({run.record.instrument.currency for run in runs})
    if len(currencies) > 1:
        raise ValueError(
            f"Expected runs in one currency to compare, got {' and '.join(currencies)}: their "
            "money cannot be set side by side."
        )


def _compared(
    run: Run, curve: ShareCurve, reasons: tuple[OrderRole, ...], reference: ComparedRun | None
) -> ComparedRun:
    """`run` in its comparison with its `curve`, beside `reference` unless it is the reference."""
    record = run.record
    figures = figures_of(run)
    outcomes = _outcomes(run, reasons)
    return ComparedRun(
        run_key=run.hash,
        strategy=record.strategy.saved_version,
        instrument=record.instrument.root,
        timeframe=str(record.strategy.spec["timeframe"]),
        currency=record.instrument.currency,
        capital=record.config.capital,
        window=record.window,
        figures=figures,
        deltas=None if reference is None else _less(figures, reference.figures),
        exit_reasons=outcomes,
        exit_reason_deltas=None if reference is None else _less_by_reason(outcomes, reference),
        curve=curve,
    )


def figures_of(run: Run) -> RunFigures:
    """The figures of `run` its record holds (`RunFigures`)."""
    metrics = run.metrics
    return RunFigures(
        pnl=metrics.pnl,
        pnl_share=run.pnl_share,
        profit_factor=metrics.trades.profit_factor,
        expectancy_r=metrics.trades.expectancy_r,
        win_rate=metrics.trades.win_rate,
        max_drawdown=metrics.drawdown.max_drawdown,
        max_drawdown_share=metrics.drawdown.max_drawdown_share,
        sharpe=metrics.daily.sharpe,
        trades=metrics.trades.trades,
    )


def share_curve(run: Run) -> ShareCurve:
    """The equity of `run` at each trade date's end (`equity_daily`) over its capital, divided in
    Python, whose division of two integers rounds once, where Polars multiplies by an inverse."""
    daily = run.equity(DAILY)
    capital = micro_units(run.config.capital)
    equity = daily.get_column("equity").to_list()
    return ShareCurve(
        trade_dates=tuple(daily.get_column("trade_date").to_list()),
        shares=tuple(value / capital for value in equity),
    )


def _outcomes(run: Run, reasons: tuple[OrderRole, ...]) -> dict[OrderRole, Outcome]:
    held = run.metrics.breakdowns.exit_reason
    none = Outcome(trades=0, wins=0, pnl=Decimal(0))
    return {role: held.get(role, none) for role in reasons}


def _less(figures: RunFigures, reference: RunFigures) -> RunFigures:
    return RunFigures(
        pnl=figures.pnl - reference.pnl,
        pnl_share=figures.pnl_share - reference.pnl_share,
        profit_factor=_difference(figures.profit_factor, reference.profit_factor),
        expectancy_r=_difference(figures.expectancy_r, reference.expectancy_r),
        win_rate=_difference(figures.win_rate, reference.win_rate),
        max_drawdown=figures.max_drawdown - reference.max_drawdown,
        max_drawdown_share=figures.max_drawdown_share - reference.max_drawdown_share,
        sharpe=_difference(figures.sharpe, reference.sharpe),
        trades=figures.trades - reference.trades,
    )


def _less_by_reason(
    outcomes: Mapping[OrderRole, Outcome], reference: ComparedRun
) -> dict[OrderRole, OutcomeDelta]:
    return {
        role: OutcomeDelta(
            trades=outcome.trades - reference.exit_reasons[role].trades,
            wins=outcome.wins - reference.exit_reasons[role].wins,
            pnl=outcome.pnl - reference.exit_reasons[role].pnl,
        )
        for role, outcome in outcomes.items()
    }


def _difference(figure: float | None, reference: float | None) -> float | None:
    return None if figure is None or reference is None else figure - reference
