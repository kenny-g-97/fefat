"""A Monte Carlo over a run's trades (step 5.20, D-118): paths of its trades drawn again with
replacement from one seed and walked from the capital, the same seed giving the same report and
another seed another, the run's own walk beside them, a run of fewer than two trades answering why
(Done means 3), and the route's most within a stated memory."""

import subprocess
import sys
from decimal import Decimal
from itertools import pairwise

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fefat as ff
from fefat.backtest.monte_carlo import MonteCarlo, TooFewTrades, resampled_trades
from fefat.market.engine_units import money_text
from notebook_runs import breakout, store_with

CAPITAL = 50_000_000_000
WINDOW = ("2026-03-05", "2026-03-09")
MEMORY_BOUND = 512 * 2**20
"""What 10,000 paths of 50,000 trades, the route's most, may hold at their peak above the trades
they draw from: 264 to 296 MiB on Windows at step 5.20, where every path's equity at once would
be 4 GB."""
ROUTES_MOST = """
import sys

import polars as pl
import psutil

from fefat.backtest.monte_carlo import resampled_trades

pnl = pl.Series([((i * 7919) % 1001 - 500) * 1_000_000 for i in range(50_000)], dtype=pl.Int64)
before = psutil.Process().memory_info().rss
resampled_trades(pnl, 50_000_000_000, paths=10_000, seed=0, max_points=3000)
if sys.platform == "win32":
    peak = psutil.Process().memory_info().peak_wset
else:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == "darwin" else 1024
print(peak - before)
"""
"""The route's most in a process of its own, printing the bytes its peak stood above the trades."""


def trades(*amounts: int) -> pl.Series:
    """The net P&L of trades in micro-units, in the order made."""
    return pl.Series("pnl", amounts, dtype=pl.Int64)


def resampled(
    pnl: pl.Series, *, paths: int = 200, seed: int = 0, max_points: int = 3000
) -> MonteCarlo:
    report = resampled_trades(pnl, CAPITAL, paths=paths, seed=seed, max_points=max_points)
    assert isinstance(report, MonteCarlo)
    return report


def test_the_same_seed_gives_the_same_report_and_another_seed_another() -> None:
    # Done means 3.
    pnl = trades(*[(index * 37 % 101 - 50) * 1_000_000 for index in range(50)])

    report = resampled(pnl, seed=7)

    assert resampled(pnl, seed=7) == report
    other = resampled(pnl, seed=8)
    assert other.net_pnl != report.net_pnl
    assert other.fan != report.fan


@pytest.mark.parametrize("amount", [-30, 40])
def test_trades_of_one_amount_give_every_percentile_the_runs_own_walk(amount: int) -> None:
    report = resampled(trades(*[amount * 1_000_000] * 12), paths=100, max_points=5)

    assert report.own_net_pnl == 12 * amount
    assert report.own_max_drawdown == max(0, -12 * amount)
    assert set(report.net_pnl.model_dump().values()) == {report.own_net_pnl}
    assert set(report.max_drawdown.model_dump().values()) == {report.own_max_drawdown}
    assert report.net_loss_share == (1 if amount < 0 else 0)
    assert report.deeper_drawdown_share == 0
    fan = report.fan
    assert fan.trades_made == (0, 3, 6, 9, 12)
    columns = (fan.p5, fan.p25, fan.median, fan.p75, fan.p95)
    for made, *percentiles in zip(fan.trades_made, *columns, strict=True):
        assert set(percentiles) == {50_000 + amount * made}


def test_a_runs_own_net_pnl_lies_within_its_paths_range() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)

    report = ff.backtest.monte_carlo(run)

    assert isinstance(report, MonteCarlo)
    assert (report.paths, report.seed, report.trades) == (1000, 0, run.trades.height)
    assert report.own_net_pnl == run.record.summary.pnl
    assert report.net_pnl.p5 <= report.own_net_pnl <= report.net_pnl.p95
    fan = report.fan
    assert fan.capital == float(run.config.capital)
    assert fan.trades_made == tuple(range(report.trades + 1))
    columns = (fan.trades_made, fan.p5, fan.p25, fan.median, fan.p75, fan.p95)
    assert {len(column) for column in columns} == {report.trades + 1}


@settings(max_examples=100, deadline=None)
@given(amounts=st.lists(st.integers(-(10**9), 10**9), min_size=2, max_size=60))
def test_one_paths_drawdown_is_the_engines_on_the_walk_its_fan_draws(amounts: list[int]) -> None:
    report = resampled(trades(*amounts), paths=1, max_points=len(amounts) + 1)

    walk = [round(equity * 10**6) for equity in report.fan.median]
    assert walk[0] == CAPITAL
    deepest = ff.backtest.running_drawdown(pl.Series(walk, dtype=pl.Int64)).max()
    assert isinstance(deepest, int)
    assert report.max_drawdown.median == Decimal(money_text(deepest))
    assert report.net_pnl.median == Decimal(money_text(walk[-1] - CAPITAL))


@settings(max_examples=100, deadline=None)
@given(count=st.integers(2, 400), max_points=st.integers(2, 50))
def test_the_fan_spreads_at_most_the_points_asked_for_from_none_to_the_trades(
    count: int, max_points: int
) -> None:
    made = resampled(trades(*[1_000_000] * count), paths=1, max_points=max_points).fan.trades_made

    assert len(made) == min(count + 1, max_points)
    assert (made[0], made[-1]) == (0, count)
    gaps = [after - before for before, after in pairwise(made)]
    assert min(gaps) >= 1
    assert max(gaps) - min(gaps) <= 1


@pytest.mark.parametrize(
    ("amounts", "reason"),
    [
        ((), "This run made no trade, and a Monte Carlo draws from at least 2."),
        ((25_000_000,), "This run made 1 trade, and a Monte Carlo draws from at least 2."),
    ],
)
def test_a_run_of_fewer_than_two_trades_says_why(amounts: tuple[int, ...], reason: str) -> None:
    # Done means 3.
    report = resampled_trades(trades(*amounts), CAPITAL, paths=100, seed=0, max_points=10)

    assert report == TooFewTrades(trades=len(amounts), reason=reason)


@pytest.mark.parametrize(
    ("asked", "refusal"),
    [
        ({"paths": 0}, r"Expected at least 1 path, got 0\."),
        ({"seed": -1}, r"Expected a seed of 0 or more, got -1\."),
        ({"max_points": 1}, r"Expected at least 2 points of the fan, got 1\."),
    ],
)
def test_no_path_a_negative_seed_and_a_fan_of_one_point_are_refused(
    asked: dict[str, int], refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        resampled_trades(
            trades(1, 2, 3), CAPITAL, **({"paths": 100, "seed": 0, "max_points": 10} | asked)
        )


def test_the_routes_most_stays_within_its_memory() -> None:
    measured = subprocess.run(
        [sys.executable, "-c", ROUTES_MOST], capture_output=True, text=True, check=True
    )

    peak = int(measured.stdout)
    print(f"10,000 paths of 50,000 trades: {peak / 2**20:.0f} MiB at their peak")
    assert peak < MEMORY_BOUND
