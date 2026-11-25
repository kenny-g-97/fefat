"""A Monte Carlo over a run's trades (steps 5.20 and 5.21, D-118, D-119): paths of its trades drawn
again with replacement from one seed and walked from the capital, the same seed giving the same
report and another seed another, the run's own walk beside them, and a run of fewer than two trades
answering why (Done means 3 of step 5.20); by whole percent of the paths, every figure the run's own
where every trade is the same, the run's own profit factor its metrics' (Done means 3 of step 5.21),
a path's profit factor and averages those of the trades its fan shows it drew, and a path that drew
no loser last; and the route's most within a stated memory."""

import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from itertools import pairwise

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fefat as ff
from fefat.backtest import resampling
from fefat.backtest.resampling import (
    PERCENTILES,
    MonteCarlo,
    Percentiles,
    TooFewTrades,
    percentiles_of,
    resampled_trades,
)
from fefat.market.engine_units import micro_units, money_text
from notebook_runs import breakout, store_with

CAPITAL = 50_000_000_000
WINDOW = ("2026-03-05", "2026-03-09")
TRADE_SCHEMA = {"pnl": pl.Int64, "mae_ticks": pl.Int64, "mfe_ticks": pl.Int64}
"""What a Monte Carlo draws of each trade: its net P&L in micro-units, its MAE and MFE in ticks."""
MEMORY_BOUND = 512 * 2**20 if sys.platform == "win32" else 2 * 2**30
"""What 10,000 paths of 50,000 trades with a fan of 10,000 counts, the route's most, may hold at
their peak above the trades they draw from, where every path's equity at once would be 4 GB: 324
to 340 MiB on Windows at step 5.20, and 1,228 MiB on CI's Ubuntu, whose allocator in Polars keeps
the walk's freed blocks resident, a bound by system that you chose at the review of its pull
request (D-119, `BACKLOG.md`); 379 to 389 MiB on Windows once each drawn trade brought its
excursions (step 5.21)."""
ROUTES_MOST = """
import sys

import polars as pl
import psutil

from fefat.backtest.resampling import resampled_trades

trades = pl.DataFrame(
    {
        "pnl": [((i * 7919) % 1001 - 500) * 1_000_000 for i in range(50_000)],
        "mae_ticks": [(i * 31) % 41 for i in range(50_000)],
        "mfe_ticks": [(i * 17) % 61 for i in range(50_000)],
    },
    schema={"pnl": pl.Int64, "mae_ticks": pl.Int64, "mfe_ticks": pl.Int64},
)
before = psutil.Process().memory_info().rss
resampled_trades(trades, 50_000_000_000, paths=10_000, seed=0, max_points=10_000)
if sys.platform == "win32":
    peak = psutil.Process().memory_info().peak_wset
else:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == "darwin" else 1024
print(peak - before)
"""
"""The route's most in a process of its own, printing the bytes its peak stood above the trades."""


def excursions_of(amount: int) -> tuple[int, int]:
    """The MAE and the MFE in ticks of a trade of net P&L `amount`, each its own."""
    return abs(amount) % 97, abs(amount) % 89 + 1


def trades_of(excursions: Mapping[int, tuple[int, int]]) -> pl.DataFrame:
    """Trades told apart by their net P&L in micro-units, the keys of `excursions` in the order
    made, each with its MAE and MFE in ticks."""
    rows = [(amount, mae, mfe) for amount, (mae, mfe) in excursions.items()]
    return pl.DataFrame(rows, schema=TRADE_SCHEMA, orient="row")


def trades(*amounts: int) -> pl.DataFrame:
    """Trades of net P&L `amounts` in micro-units, in the order made, each with the excursions
    `excursions_of` gives it."""
    rows = [(amount, *excursions_of(amount)) for amount in amounts]
    return pl.DataFrame(rows, schema=TRADE_SCHEMA, orient="row")


def resampled(
    drawn_from: pl.DataFrame, *, paths: int = 200, seed: int = 0, max_points: int = 3000
) -> MonteCarlo:
    report = resampled_trades(drawn_from, CAPITAL, paths=paths, seed=seed, max_points=max_points)
    assert isinstance(report, MonteCarlo)
    return report


@contextmanager
def drawn_in_blocks_of(draws: int) -> Iterator[None]:
    """Walks that draw `draws` trades over every path at a time, so that a test's walk crosses
    the edges of many blocks, where the default's block holds every trade of a short run."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(resampling, "BLOCK_DRAWS", draws)
        yield


def test_the_same_seed_gives_the_same_report_and_another_seed_another() -> None:
    # Done means 3 of step 5.20.
    drawn_from = trades(*[(index * 37 % 101 - 50) * 1_000_000 for index in range(50)])

    report = resampled(drawn_from, seed=7)

    assert resampled(drawn_from, seed=7) == report
    other = resampled(drawn_from, seed=8)
    assert other.net_pnl != report.net_pnl
    assert other.fan != report.fan
    assert other.by_percent != report.by_percent


@pytest.mark.parametrize("amount", [-30, 40])
def test_trades_of_one_amount_give_every_figure_the_runs_own_at_every_percent(amount: int) -> None:
    # Done means 3 of step 5.21. Blocks of 5 counts over the 100 paths: the fan's counts fall
    # inside, at the start of, and at the end of a block.
    with drawn_in_blocks_of(500):
        report = resampled(trades(*[amount * 1_000_000] * 12), paths=100, max_points=5)

    assert report.own_net_pnl == 12 * amount
    assert report.own_max_drawdown == max(0, -12 * amount)
    assert set(report.net_pnl.model_dump().values()) == {report.own_net_pnl}
    assert set(report.max_drawdown.model_dump().values()) == {report.own_max_drawdown}
    assert report.net_loss_share == (1 if amount < 0 else 0)
    assert report.deeper_drawdown_share == 0
    by = report.by_percent
    assert (by.net_pnl.own, by.max_drawdown.own) == (12 * amount, max(0, -12 * amount))
    assert by.profit_factor.own == (0 if amount < 0 else None)
    assert (by.average_mae_ticks.own, by.average_mfe_ticks.own) == excursions_of(amount * 10**6)
    figures = (by.net_pnl, by.max_drawdown, by.profit_factor, by.average_mae_ticks)
    for figure in (*figures, by.average_mfe_ticks):
        assert figure.at_percent == (figure.own,) * 101
    fan = report.fan
    assert fan.trades_made == (0, 3, 6, 9, 12)
    columns = (fan.p5, fan.p25, fan.median, fan.p75, fan.p95, fan.own)
    for made, *equities in zip(fan.trades_made, *columns, strict=True):
        assert set(equities) == {50_000 + amount * made}


def test_a_runs_own_figures_are_its_metrics_and_lie_within_its_paths() -> None:
    # Done means 3 of step 5.21: the run's own profit factor is its metrics'.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)

    report = ff.backtest.monte_carlo(run)

    assert isinstance(report, MonteCarlo)
    assert (report.paths, report.seed, report.trades) == (1000, 0, run.trades.height)
    assert report.own_net_pnl == run.record.summary.pnl
    assert report.net_pnl.p5 <= report.own_net_pnl <= report.net_pnl.p95
    capital = micro_units(run.config.capital)
    walked = run.trades.get_column("pnl").cum_sum() + capital
    own_walk = pl.concat([pl.Series([capital], dtype=pl.Int64), walked])
    deepest = ff.backtest.running_drawdown(own_walk).max()
    assert isinstance(deepest, int)
    assert report.own_max_drawdown == Decimal(money_text(deepest))
    fan = report.fan
    assert fan.capital == float(run.config.capital)
    assert fan.trades_made == tuple(range(report.trades + 1))
    columns = (fan.trades_made, fan.p5, fan.p25, fan.median, fan.p75, fan.p95, fan.own)
    assert {len(column) for column in columns} == {report.trades + 1}
    assert fan.own == tuple(equity / 10**6 for equity in own_walk.to_list())
    by = report.by_percent
    assert run.metrics.trades.losses > 0
    assert by.profit_factor.own == run.metrics.trades.profit_factor
    assert by.net_pnl.own == float(report.own_net_pnl)
    assert by.max_drawdown.own == float(report.own_max_drawdown)
    excursions = run.trades.select(pl.col("mae_ticks", "mfe_ticks").sum()).row(0)
    own_averages = (by.average_mae_ticks.own, by.average_mfe_ticks.own)
    assert own_averages == tuple(total / report.trades for total in excursions)
    for name, percent in PERCENTILES.items():
        assert by.net_pnl.at_percent[percent] == float(getattr(report.net_pnl, name))
        assert by.max_drawdown.at_percent[percent] == float(getattr(report.max_drawdown, name))
    for figure in (by.net_pnl, by.max_drawdown, by.average_mae_ticks, by.average_mfe_ticks):
        assert list(figure.at_percent) == sorted(figure.at_percent)
    factors = by.profit_factor.at_percent
    held = [factor for factor in factors if factor is not None]
    assert list(factors) == [*held, *[None] * (len(factors) - len(held))]
    assert held == sorted(held)


@settings(max_examples=100, deadline=None)
@given(
    excursions=st.dictionaries(
        st.integers(-(10**9), 10**9),
        st.tuples(st.integers(0, 400), st.integers(0, 400)),
        min_size=2,
        max_size=60,
    )
)
def test_one_paths_figures_are_those_of_the_trades_its_fan_shows_it_drew(
    excursions: dict[int, tuple[int, int]],
) -> None:
    # Blocks of 3 trades, so that the equity, the peak, the deepest fall, and the sums of the
    # winners, the losers, and the excursions carry across many; trades told apart by their P&L.
    with drawn_in_blocks_of(3):
        report = resampled(trades_of(excursions), paths=1, max_points=len(excursions) + 1)

    walk = [round(equity * 10**6) for equity in report.fan.median]
    drawn = [after - before for before, after in pairwise(walk)]
    assert walk[0] == CAPITAL
    assert all(amount in excursions for amount in drawn)
    deepest = ff.backtest.running_drawdown(pl.Series(walk, dtype=pl.Int64)).max()
    assert isinstance(deepest, int)
    assert report.max_drawdown.median == Decimal(money_text(deepest))
    assert report.net_pnl.median == Decimal(money_text(walk[-1] - CAPITAL))
    by = report.by_percent
    profit = sum(amount for amount in drawn if amount > 0)
    loss = -sum(amount for amount in drawn if amount < 0)
    assert set(by.profit_factor.at_percent) == {None if loss == 0 else profit / loss}
    mae = sum(excursions[amount][0] for amount in drawn) / len(drawn)
    mfe = sum(excursions[amount][1] for amount in drawn) / len(drawn)
    assert set(by.average_mae_ticks.at_percent) == {mae}
    assert set(by.average_mfe_ticks.at_percent) == {mfe}


def test_a_path_that_drew_no_loser_has_no_profit_factor_and_stands_last() -> None:
    # Three trades a path from two winners and a loser, so that about 30 of the 100 paths draw no
    # loser; a block of one count, so that the profit and the loss carry across the blocks.
    with drawn_in_blocks_of(100):
        report = resampled(trades(10_000_000, 20_000_000, -5_000_000), paths=100, max_points=4)

    factors = report.by_percent.profit_factor.at_percent
    held = [factor for factor in factors if factor is not None]
    assert 0 < len(held) < len(factors)
    assert list(factors) == [*held, *[None] * (len(factors) - len(held))]
    assert held == sorted(held)
    assert report.by_percent.profit_factor.own == 30 / 5


def test_a_percentile_is_the_amount_at_its_nearest_rank() -> None:
    # D-118: the rank round((n - 1) * share) of the amounts ordered from the lowest, a half up.
    ranked = percentiles_of(pl.Series(range(1000), dtype=pl.Int64))

    assert ranked == Percentiles(
        p5=Decimal("0.000050"),
        p25=Decimal("0.000250"),
        median=Decimal("0.000500"),
        p75=Decimal("0.000749"),
        p95=Decimal("0.000949"),
    )
    assert percentiles_of(pl.Series(range(102), dtype=pl.Int64)).median == Decimal("0.000051")


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
    # Done means 3 of step 5.20.
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
