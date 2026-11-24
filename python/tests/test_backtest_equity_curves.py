"""A run's equity curve for a chart (step 5.7, D-116): a long curve downsampled to at most the
points asked for, every row one of the run's, its deepest drawdown, lowest and highest equity,
first decision, and last decision kept. Done means 3."""

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fefat as ff
from fefat.backtest.equity_curves import downsampled_equity
from notebook_runs import breakout, store_with

CAPITAL = 50_000_000_000
WINDOW = ("2026-03-05", "2026-03-09")

equities = st.lists(st.integers(-(10**12), 10**12), min_size=1, max_size=300)


def decisions(equity: list[int | None]) -> pl.DataFrame:
    """The account after each decision, a decision a second."""
    return pl.DataFrame(
        {"ts": [second * 1_000_000_000 for second in range(len(equity))], "equity": equity},
        schema={"ts": pl.Int64, "equity": pl.Int64},
    )


def deepest(equity: list[int], capital: int) -> int:
    """The deepest fall below a peak, the capital first, as the metrics measure it."""
    account = pl.Series("equity", [capital, *equity], dtype=pl.Int64)
    fallen = ff.backtest.running_drawdown(account).max()
    assert isinstance(fallen, int)
    return fallen


@settings(max_examples=200, deadline=None)
@given(equity=equities, max_points=st.integers(5, 400))
def test_a_curve_keeps_its_extremes_within_the_points_asked_for(
    equity: list[int], max_points: int
) -> None:
    every = decisions([*equity])

    curve = downsampled_equity(every, CAPITAL, max_points)

    assert curve.columns == ["ts", "equity", "drawdown"]
    assert curve.height == len(equity) if len(equity) <= max_points else curve.height <= max_points
    assert curve.get_column("ts").is_sorted()
    assert curve.join(every, on=["ts", "equity"], how="anti").is_empty()
    assert curve.get_column("drawdown").max() == deepest(equity, CAPITAL)
    assert curve.get_column("equity").min() == min(equity)
    assert curve.get_column("equity").max() == max(equity)
    assert curve.row(0)[:2] == every.row(0)
    assert curve.row(-1)[:2] == every.row(-1)


def test_a_bucket_keeps_the_trough_that_its_lowest_and_highest_would_lose() -> None:
    # The fall from 200 to 120 is the deepest, its trough neither the lowest nor the highest.
    equity = [90, 200, 120, 300, 280, 290]

    curve = downsampled_equity(decisions([*equity]), 100, 5)

    assert curve.height <= 5
    assert 120 in curve.get_column("equity").to_list()
    assert curve.get_column("drawdown").max() == 80


def test_a_short_curve_is_kept_whole_and_each_depth_is_measured_from_the_capital() -> None:
    curve = downsampled_equity(decisions([90, 120, 100]), 100, 5)

    assert curve.get_column("equity").to_list() == [90, 120, 100]
    assert curve.get_column("drawdown").to_list() == [10, 0, 20]


def test_a_decision_that_values_no_account_is_left_out_as_the_metrics_leave_it() -> None:
    curve = downsampled_equity(decisions([None, 90, None, 100]), 100, 5)

    assert curve.get_column("ts").to_list() == [1_000_000_000, 3_000_000_000]
    assert curve.get_column("drawdown").to_list() == [10, 0]


def test_a_run_without_a_valued_decision_has_an_empty_curve() -> None:
    assert downsampled_equity(decisions([None, None]), 100, 5).is_empty()


def test_fewer_points_than_a_bucket_needs_are_refused() -> None:
    with pytest.raises(ValueError, match=r"Expected at least 5 points of the curve, got 4"):
        downsampled_equity(decisions([1, 2, 3, 4, 5, 6]), 100, 4)


def test_a_daily_strategys_run_gives_the_curve_of_its_decisions() -> None:
    # The code review: `Run.equity("1d")` is the daily artifact, which holds no instants.
    store_with("ohlcv-1m")
    daily = ff.SignalStrategy(
        instrument="ES",
        timeframe="1d",
        features={},
        long_entry=pl.lit(False),
        short_entry=pl.lit(False),
        execution=breakout().execution,
    )
    run = ff.backtest.run(daily, *WINDOW)

    curve = ff.backtest.equity_curve(run)

    assert curve.columns == ["ts", "equity", "drawdown"]
    assert curve.height == run.signals.height > 0


def test_a_saved_run_gives_its_curve_with_the_engines_maximum_drawdown() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    whole = run.equity("5m").height
    assert whole > 90

    curve = ff.backtest.equity_curve(run, max_points=90)

    assert curve.height <= 90
    assert curve.get_column("drawdown").max() == int(run.metrics.drawdown.max_drawdown * 10**6)
