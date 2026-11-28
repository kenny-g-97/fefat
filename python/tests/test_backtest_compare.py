"""Saved runs side by side (step 5.10, D-126): each delta is a run's figure less the reference's,
both as the runs' records hold them (Done means 3, the SDK's half); each run's curve is its
equity at each trade date's end over its own capital; every exit reason any run closed a trade by
stands for each run, none where it closed none; and a comparison of fewer than two runs, more than
four, one run twice, or two currencies is refused."""

from decimal import Decimal
from fractions import Fraction

import pytest

import fefat as ff
from fefat.backtest import Run, RunConfig
from fefat.market.engine_units import micro_units
from fefat.market.instruments import Currency
from fefat.reference.orders import OrderRole
from notebook_runs import breakout, breakout_both_ways, store_with

WINDOW = ("2026-03-05", "2026-03-09")


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    store_with("ohlcv-1m")


def test_each_delta_is_the_runs_figure_less_the_references_as_their_records_hold_them() -> None:
    reference = ff.backtest.run(breakout(), *WINDOW)
    other = ff.backtest.run(breakout_both_ways(), *WINDOW)

    compared = ff.backtest.compare_runs([reference, other]).runs

    first, second = reference.metrics, other.metrics
    assert compared[0].deltas is None
    assert compared[0].exit_reason_deltas is None
    deltas = compared[1].deltas
    assert deltas is not None
    assert deltas.pnl == second.pnl - first.pnl
    assert deltas.pnl_share == other.pnl_share - reference.pnl_share
    assert deltas.trades == second.trades.trades - first.trades.trades
    assert deltas.win_rate == difference(second.trades.win_rate, first.trades.win_rate)
    assert deltas.profit_factor == difference(
        second.trades.profit_factor, first.trades.profit_factor
    )
    assert deltas.expectancy_r == difference(second.trades.expectancy_r, first.trades.expectancy_r)
    assert deltas.sharpe == difference(second.daily.sharpe, first.daily.sharpe)
    assert deltas.max_drawdown == second.drawdown.max_drawdown - first.drawdown.max_drawdown
    assert deltas.max_drawdown_share == (
        second.drawdown.max_drawdown_share - first.drawdown.max_drawdown_share
    )
    assert deltas.trades != 0
    assert (compared[0].figures.pnl, compared[1].figures.pnl) == (first.pnl, second.pnl)


def test_each_reasons_delta_is_the_runs_trades_by_that_reason_less_the_references() -> None:
    reference = ff.backtest.run(breakout(), *WINDOW)
    other = ff.backtest.run(breakout_both_ways(), *WINDOW)

    comparison = ff.backtest.compare_runs([reference, other])

    by_reason = (reference.metrics.breakdowns.exit_reason, other.metrics.breakdowns.exit_reason)
    assert set(comparison.exit_reasons) == set(by_reason[0]) | set(by_reason[1])
    deltas = comparison.runs[1].exit_reason_deltas
    assert deltas is not None
    for role in comparison.exit_reasons:
        first, second = (
            comparison.runs[0].exit_reasons[role],
            comparison.runs[1].exit_reasons[role],
        )
        assert (deltas[role].trades, deltas[role].wins, deltas[role].pnl) == (
            second.trades - first.trades,
            second.wins - first.wins,
            second.pnl - first.pnl,
        )


def test_an_exit_reason_a_run_closed_no_trade_by_reads_none_of_its_trades() -> None:
    reference = ff.backtest.run(breakout(), *WINDOW)
    other = without_exit_reasons(ff.backtest.run(breakout_both_ways(), *WINDOW))

    comparison = ff.backtest.compare_runs([reference, other])

    assert comparison.exit_reasons == tuple(
        role for role in OrderRole if role in reference.metrics.breakdowns.exit_reason
    )
    for role in comparison.exit_reasons:
        assert comparison.runs[1].exit_reasons[role].trades == 0
        assert comparison.runs[1].exit_reasons[role].pnl == 0


def test_each_runs_curve_is_its_daily_equity_over_its_own_capital() -> None:
    reference = ff.backtest.run(breakout(), *WINDOW)
    other = ff.backtest.run(breakout(8), *WINDOW, RunConfig(capital=Decimal(100_000)))

    comparison = ff.backtest.compare_runs([reference, other])

    for run, compared in zip((reference, other), comparison.runs, strict=True):
        daily = run.equity("1d")
        capital = micro_units(run.config.capital)
        assert compared.curve.trade_dates == tuple(daily.get_column("trade_date").to_list())
        assert compared.curve.shares == tuple(
            float(Fraction(equity, capital)) for equity in daily.get_column("equity").to_list()
        )
    assert comparison.runs[1].config.capital == Decimal(100_000)


def test_a_comparison_needs_two_to_four_different_runs_in_one_currency() -> None:
    reference = ff.backtest.run(breakout(), *WINDOW)
    other = ff.backtest.run(breakout_both_ways(), *WINDOW)

    with pytest.raises(ValueError, match="Expected 2 to 4 runs to compare, got 1"):
        ff.backtest.compare_runs([reference])
    with pytest.raises(ValueError, match="Expected 2 to 4 runs to compare, got 5"):
        ff.backtest.compare_runs([reference, other, reference, other, reference])
    with pytest.raises(ValueError, match=f"got run {reference.hash[:12]} twice"):
        ff.backtest.compare_runs([reference, other, reference])
    with pytest.raises(
        ValueError, match="Expected runs in one currency to compare, got USD and USDT"
    ):
        ff.backtest.compare_runs([reference, in_currency(other, Currency.USDT)])


def difference(figure: float | None, reference: float | None) -> float | None:
    return None if figure is None or reference is None else figure - reference


def without_exit_reasons(run: Run) -> Run:
    """`run` as if it had closed no trade by any exit reason."""
    metrics = run.metrics
    breakdowns = metrics.breakdowns.model_copy(update={"exit_reason": {}})
    held = metrics.model_copy(update={"breakdowns": breakdowns})
    return Run(folder=run.folder, record=run.record.model_copy(update={"metrics": held}))


def in_currency(run: Run, currency: Currency) -> Run:
    """`run` as if its instrument counted its money in `currency`."""
    instrument = run.record.instrument.model_copy(update={"currency": currency})
    return Run(folder=run.folder, record=run.record.model_copy(update={"instrument": instrument}))
