"""A saved run's market exposure and buy and hold (step 5.23, D-121, D-123): a run long one lot
from its first decision to its last, without costs, has a correlation of 1 and a beta of one lot,
and the beta's lots of the market's change plus the alpha is the run's days summed (Done means 3);
buy and hold at one lot is that run's account, across a roll whose gap the market's day leaves
out, its drawdown the engine's running drawdown on that walk, and while the roll's legs are on
their way too; the same days a trade date later correlate near zero on a random walk; a run that
never trades has no correlation; the figures are the statistics module's on a run of trades; a
roll's gap comes off at its instant; a crypto pair's lot is a coin; buy and hold at the run's
volatility is one lot's figures at its lots; and fewer than three days leave nothing to count."""

import os
import random
import statistics
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import RunConfig, run_config
from fefat.backtest import requests as run_requests
from fefat.backtest import run_inputs as run_documents
from fefat.backtest.artifacts import read_artifact, write_run
from fefat.backtest.comoments import Comoments, Uncounted
from fefat.backtest.exposure import (
    EngineRoll,
    SizedBuyAndHold,
    UnsizedBuyAndHold,
    daily_moves,
    engine_rolls,
    market_values,
)
from fefat.backtest.schemas import EQUITY
from fefat.config import resolve_paths
from fefat.market import fees, instruments
from fefat.market.calendar import sessions_of
from fefat.market.engine_units import InstrumentParameters, micro_units, money_text
from fefat.market.fees import TABLES, FeeSchedule, FeeTable, FuturesFee
from fefat.market.layout import Partition, YearMonth
from fefat.market.roll_decisions import RollReason
from fefat.market.store import Store
from fefat.reference.settings import SlippageTicks
from fefat.reference.units import day_number
from generated_minutes import FEBRUARY, MINUTE, MINUTES, write_minutes
from notebook_runs import breakout_both_ways, store_with

ACROSS_THE_ROLL = ("2026-02-03", "2026-02-20")
"""Thirteen trade dates of the generated February store, which rolls at the open of 02-19."""
ES = InstrumentParameters(tick=250_000_000, money_per_point=50_000_000, lot_step=Decimal(1))
NO_FEES = FeeTable(
    name="no-fees",
    schedules=(
        FeeSchedule(
            effective_from=date(2010, 1, 4),
            sources=("This test's own table, which charges nothing.",),
            fees={"ES": FuturesFee(per_contract_side=Decimal(0))},
        ),
    ),
)
HELD_LONG = ff.SignalStrategy(
    instrument="ES",
    timeframe="5m",
    long_entry=pl.lit(True),
    short_entry=pl.lit(False),
    execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
)
"""One lot long from the first decision, which the template places only while flat, never
closed: the run holds it to its last decision, across the roll."""
NEVER = ff.SignalStrategy(
    instrument="ES",
    timeframe="5m",
    long_entry=pl.lit(False),
    short_entry=pl.lit(False),
    execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
)


@pytest.fixture
def without_costs(monkeypatch: pytest.MonkeyPatch) -> RunConfig:
    """A run's settings that pay no cost: no slippage, and a fee table that charges ES nothing
    among those a run can name, which FEAT's own tables never allow."""
    tables = MappingProxyType({**TABLES, NO_FEES.name: NO_FEES})
    for module in (fees, run_config, run_requests, run_documents):
        monkeypatch.setattr(module, "TABLES", tables)
    return RunConfig(fee_table=NO_FEES.name, slippage_ticks=SlippageTicks(market=0, stop=0))


def decisions_of(run: ff.backtest.Run) -> pl.DataFrame:
    """The run's valued decisions with the market's value at each, as `market_exposure` reads
    them."""
    equity = read_artifact(run.folder, "equity")
    return market_values(equity, run.fills, engine_rolls(run), ES)


def days_of(run: ff.backtest.Run) -> pl.DataFrame:
    """The run's and the market's days as `market_exposure` pairs them."""
    return daily_moves(decisions_of(run), micro_units(run.config.capital))


def made_over_the_run(run: ff.backtest.Run) -> Decimal:
    """The run's days summed: its equity at its last decision less its capital."""
    last = read_artifact(run.folder, "equity").get_column("equity").drop_nulls().item(-1)
    return Decimal(money_text(last - micro_units(run.config.capital)))


def test_a_run_long_one_lot_without_costs_has_a_correlation_of_1_and_a_beta_of_one_lot(
    without_costs: RunConfig,
) -> None:
    # Done means 3, across the roll the run's lot is carried over, at the gap.
    write_minutes(FEBRUARY)
    run = ff.backtest.run(HELD_LONG, *ACROSS_THE_ROLL, without_costs)

    exposure = ff.backtest.market_exposure(run)

    (roll,) = run.record.rolls
    assert roll.gap != 0
    assert run.fills.get_column("fee").sum() == 0
    every = exposure.all_days
    assert (every.correlation, every.beta_lots, every.explained_share) == (1, 1, 1)
    assert every.uncounted is None
    for side in (exposure.falling_days, exposure.rising_days):
        assert side.days >= 3
        assert (side.correlation, side.beta_lots) == (1, 1)
    assert every.beta_lots is not None
    assert every.alpha is not None
    market_change = exposure.buy_and_hold.at_one_lot.net_pnl
    assert every.beta_lots * float(market_change) + every.alpha == float(made_over_the_run(run))


def test_buy_and_hold_at_one_lot_is_a_run_long_one_lot_without_costs(
    without_costs: RunConfig,
) -> None:
    # Across the roll the market's day leaves the gap out: a run that never trades sees the marks
    # the held run carried its lot over, and buy and hold's drawdown is the engine's running
    # drawdown on that walk.
    write_minutes(FEBRUARY)
    held = ff.backtest.run(HELD_LONG, *ACROSS_THE_ROLL, without_costs)
    flat = ff.backtest.run(NEVER, *ACROSS_THE_ROLL, without_costs)

    one_lot = ff.backtest.market_exposure(flat).buy_and_hold.at_one_lot

    assert days_of(flat).get_column("market").to_list() == held.equity("1d")["pnl"].to_list()
    walk = read_artifact(held.folder, "equity").get_column("equity").drop_nulls()
    deepest = ff.backtest.running_drawdown(walk).max()
    assert isinstance(deepest, int)
    assert deepest > 0
    assert (
        one_lot.max_drawdown == Decimal(money_text(deepest)) == held.metrics.drawdown.max_drawdown
    )
    assert one_lot.net_pnl == made_over_the_run(held)
    assert one_lot.longest_drawdown_days == held.metrics.drawdown.longest_drawdown_days
    assert one_lot.sharpe == held.metrics.daily.sharpe
    assert one_lot.lots == 1


def without_the_new_fronts_first_minutes(store: Store) -> int:
    """The generated February store with ESM2026's first five minutes of 02-19's session left out,
    so that the decision at their close finds the roll's legs still on their way; the session's
    open, in nanoseconds."""
    paths = resolve_paths(os.environ)
    sessions = sessions_of(instruments.get("ES").session_calendar(), paths.cache_dir)
    opens = sessions.between(date(2026, 2, 19), date(2026, 2, 19)).item(0, "open")
    partition = Partition(dataset=MINUTES, contract="ESM2026", key=YearMonth.parse("2026-02"))
    rows = store.scan_partition(partition).collect()
    store.write_partition(
        partition, rows.filter(~pl.col("ts_open").is_between(opens, opens + 5 * MINUTE, "left"))
    )
    return opens


def test_while_a_rolls_legs_are_on_their_way_the_market_keeps_the_old_contracts_level(
    without_costs: RunConfig,
) -> None:
    # The engine review: with the new front silent for the session's first bucket, its decision
    # finds the legs on their way and values the held lot at the old contract's price, which the
    # market keeps; at every decision the market is what the lot held without costs is worth.
    opens = without_the_new_fronts_first_minutes(write_minutes(FEBRUARY))
    held = ff.backtest.run(HELD_LONG, *ACROSS_THE_ROLL, without_costs)
    flat = ff.backtest.run(NEVER, *ACROSS_THE_ROLL, without_costs)

    held_market, flat_market = decisions_of(held), decisions_of(flat)

    (roll,) = engine_rolls(held)
    assert roll.session_open == opens
    legs = held.fills.filter((pl.col("ts") >= opens) & (pl.col("contract") == roll.rolled_from))
    waiting = held_market.filter(pl.col("ts").is_between(opens, legs.item(0, "ts"), "left"))
    assert waiting.height == 1
    capital = micro_units(held.config.capital)
    moved = held_market.select(pl.col("market") - pl.col("market").first() + capital)
    assert moved.to_series().to_list() == held_market.get_column("equity").to_list()
    assert flat_market.get_column("market").to_list() == held_market["market"].to_list()


def test_the_same_days_a_trade_date_later_correlate_near_zero_on_a_random_walk() -> None:
    draws = random.Random(523)
    market = [draws.randint(-40, 40) * 12_500_000 for _ in range(1_001)]

    later = Comoments.of(market[1:], market[:-1]).days_exposure()
    alike = Comoments.of(market[1:], market[1:]).days_exposure()

    assert (alike.correlation, alike.beta_lots) == (1, 1)
    assert later.correlation is not None
    assert abs(later.correlation) < 0.1
    with pytest.raises(ValueError, match="Expected days whose correlation counts"):
        Comoments.of(market[:2], market[:2]).volatility_lots()


def test_a_run_that_never_trades_has_no_correlation() -> None:
    write_minutes(FEBRUARY)
    run = ff.backtest.run(NEVER, *ACROSS_THE_ROLL)

    exposure = ff.backtest.market_exposure(run)

    every = exposure.all_days
    assert (every.correlation, every.explained_share) == (None, None)
    assert every.uncounted == Uncounted.RUN_NEVER_DIFFERED
    assert (every.beta_lots, every.alpha) == (0, 0)
    held = exposure.buy_and_hold
    assert isinstance(held, UnsizedBuyAndHold)
    assert held.at_one_lot.net_pnl != 0
    assert held.uncounted == Uncounted.RUN_NEVER_DIFFERED


def test_the_figures_are_the_statistics_modules_on_a_run_of_trades() -> None:
    # The step review: the correlation, the beta, the explained share, and each side's are held
    # to Python's own statistics, on the days `market_exposure` pairs.
    write_minutes(FEBRUARY)
    run = ff.backtest.run(breakout_both_ways(), *ACROSS_THE_ROLL)

    exposure = ff.backtest.market_exposure(run)

    days = days_of(run)
    assert days.get_column("run").to_list() == run.equity("1d")["pnl"].to_list()
    pairs = [
        (exposure.all_days, days),
        (exposure.falling_days, days.filter(pl.col("market") < 0)),
        (exposure.rising_days, days.filter(pl.col("market") > 0)),
    ]
    for side, its_days in pairs:
        market, made = its_days["market"].to_list(), its_days["run"].to_list()
        assert side.days == len(market) >= 3
        assert side.correlation == pytest.approx(statistics.correlation(market, made))
        slope = statistics.covariance(market, made) / statistics.variance(market)
        assert side.beta_lots == pytest.approx(slope)
    every = exposure.all_days
    assert every.correlation is not None
    assert every.explained_share == pytest.approx(every.correlation**2)


def test_buy_and_hold_at_the_runs_volatility_is_one_lots_figures_at_its_lots() -> None:
    # On a run of trades and costs: the beta's lots of the market's change plus the alpha is its
    # days summed, and the days the market fell, rose, or stood still are all its days.
    write_minutes(FEBRUARY)
    run = ff.backtest.run(breakout_both_ways(), *ACROSS_THE_ROLL)

    exposure = ff.backtest.market_exposure(run)

    days = days_of(run)
    market, made = days.get_column("market").to_list(), days.get_column("run").to_list()
    every, held = exposure.all_days, exposure.buy_and_hold
    assert isinstance(held, SizedBuyAndHold)
    assert every.beta_lots is not None
    assert every.alpha is not None
    market_change = float(held.at_one_lot.net_pnl)
    assert every.beta_lots * market_change + every.alpha == pytest.approx(sum(made) / 10**6)
    still = sum(1 for moved in market if moved == 0)
    assert exposure.falling_days.days + exposure.rising_days.days + still == every.days
    sized, one_lot = held.at_run_volatility, held.at_one_lot
    assert sized.lots == pytest.approx(statistics.stdev(made) / statistics.stdev(market))
    for figure in ("net_pnl", "max_drawdown"):
        exact = getattr(one_lot, figure) * Decimal(sized.lots)
        assert abs(getattr(sized, figure) - exact) <= Decimal("0.000001"), figure
    assert (sized.longest_drawdown_days, sized.sharpe) == (
        one_lot.longest_drawdown_days,
        one_lot.sharpe,
    )
    curve = ff.backtest.equity_curve(run)
    assert held.curve.time == tuple((curve.get_column("ts") // 10**9).to_list())
    ends = float(run.config.capital + sized.net_pnl)
    assert held.curve.equity[-1] == pytest.approx(ends, abs=1e-6)


def test_fewer_than_three_days_leave_nothing_to_count() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout_both_ways(), "2026-03-05", "2026-03-09")

    exposure = ff.backtest.market_exposure(run)

    every = exposure.all_days
    assert every.days == 2
    figures = (every.correlation, every.beta_lots, every.explained_share, every.alpha)
    assert figures == (None, None, None, None)
    assert every.uncounted == Uncounted.TOO_FEW_DAYS
    for side in (exposure.falling_days, exposure.rising_days):
        assert (side.correlation, side.uncounted) == (None, Uncounted.TOO_FEW_DAYS)
    held = exposure.buy_and_hold
    assert isinstance(held, UnsizedBuyAndHold)
    assert held.at_one_lot.net_pnl == Decimal(money_text(sum(days_of(run)["market"])))
    assert held.uncounted == Uncounted.TOO_FEW_DAYS
    with pytest.raises(ValueError, match="Expected at least 5 points of the curve, got 4"):
        ff.backtest.market_exposure(run, max_points=4)


def test_a_run_whose_account_no_decision_valued_at_a_mark_is_refused(tmp_path: Path) -> None:
    # The step review: the refusal 02 section 7 states, of a folder whose marks are all gone.
    store_with("ohlcv-1m")
    run = ff.backtest.run(NEVER, "2026-03-05", "2026-03-09")
    unmarked = read_artifact(run.folder, "equity").with_columns(mark=pl.lit(None, pl.Int64))
    folder = tmp_path / "runs" / run.hash
    write_run(folder, {"equity": unmarked, "fills": run.fills}, run.record)

    with pytest.raises(ValueError, match=f"Expected a mark at a decision of run {run.hash[:12]}"):
        ff.backtest.market_exposure(ff.backtest.Run.open(folder))


def test_two_decisions_at_one_instant_are_refused(tmp_path: Path) -> None:
    # The code review: buy and hold's curve pairs its decisions with the account's one to one.
    store_with("ohlcv-1m")
    run = ff.backtest.run(NEVER, "2026-03-05", "2026-03-09")
    equity = read_artifact(run.folder, "equity")
    twice = pl.concat([equity, equity.head(1)]).sort("ts")
    folder = tmp_path / "runs" / run.hash
    write_run(folder, {"equity": twice, "fills": run.fills}, run.record)

    with pytest.raises(
        ValueError, match=f"Expected one decision at each instant of run {run.hash[:12]}, got 2"
    ):
        ff.backtest.market_exposure(ff.backtest.Run.open(folder))


SESSION_OPEN = 300
"""The instant of the session the hand-made roll serves from."""
MARCH_9_ROLL = EngineRoll(
    trade_date=day_number(date(2026, 3, 9)),
    session_open=SESSION_OPEN,
    rolled_from="ESH2026",
    contract="ESM2026",
    gap=20_000_000_000,
    reason=RollReason.VOLUME,
)
MARCH_6, MARCH_9, MARCH_10 = date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)
Marks = tuple[str | None, str, str, str]


def account(
    position: int,
    marks: Marks,
    trade_dates: tuple[date, date, date, date] = (MARCH_6, MARCH_6, MARCH_9, MARCH_9),
) -> pl.DataFrame:
    """Four decisions: one before the roll; one at the roll's instant, which a calendar without a
    break between sessions dates to the trade date before, and which follows the roll
    (F-CLK-02); and two after it; holding `position` after the first, at `marks`, none before
    the first tradeable price."""
    units = [None if mark is None else int(Decimal(mark) * 10**9) for mark in marks]
    return pl.DataFrame(
        {
            "ts": [100, SESSION_OPEN, 400, 600],
            "trade_date": list(trade_dates),
            "cash": [50_000_000_000] * 4,
            "position": [position] * 4,
            "mark": units,
            "equity": [50_000_000_000] * 4,
        },
        schema=EQUITY,
    )


def filled(*fills: tuple[int, str, date]) -> pl.DataFrame:
    """Fills at their instants on their contracts, with the trade dates the engine stamps
    them with."""
    return pl.DataFrame(
        {
            "ts": [ts for ts, _, _ in fills],
            "contract": [contract for _, contract, _ in fills],
            "trade_date": [trade_date for _, _, trade_date in fills],
        },
        schema={"ts": pl.Int64, "contract": pl.String, "trade_date": pl.Date},
    )


@pytest.mark.parametrize(
    ("position", "marks", "fills", "levels"),
    [
        # Flat at the roll: the mark moved by the gap at once (F-ROL-03), at its instant too.
        (0, ("5000", "5021", "5021", "5022"), filled(), ("5000", "5001", "5001", "5002")),
        # An entry on the new front after the roll, which no leg was waiting for.
        (
            0,
            ("5000", "5021", "5021", "5022"),
            filled((500, "ESM2026", MARCH_9)),
            ("5000", "5001", "5001", "5002"),
        ),
        # Held: valued at the old contract's price until the close leg filled at 500.
        (
            1,
            ("5000", "5001", "5001", "5022"),
            filled((500, "ESH2026", MARCH_9), (500, "ESM2026", MARCH_9)),
            ("5000", "5001", "5001", "5002"),
        ),
        # Held, the legs filled on a record at the roll's instant, before its decision.
        (
            1,
            ("5000", "5021", "5021", "5022"),
            filled((SESSION_OPEN, "ESH2026", MARCH_9), (SESSION_OPEN, "ESM2026", MARCH_9)),
            ("5000", "5001", "5001", "5002"),
        ),
        # Held, the legs still on their way when the run ended, the mark frozen with them.
        (1, ("5000", "5001", "5001", "5001"), filled(), ("5000", "5001", "5001", "5001")),
        # The engine review: an entry on the old front's bar closing at the roll's instant,
        # stamped with the trade date before, comes before the roll (F-ROL-01), and the
        # close leg after it ends the legs' way.
        (
            1,
            ("5000", "5001", "5021", "5022"),
            filled(
                (SESSION_OPEN, "ESH2026", MARCH_6),
                (350, "ESH2026", MARCH_9),
                (350, "ESM2026", MARCH_9),
            ),
            ("5000", "5001", "5001", "5002"),
        ),
        # The same entry, its legs never filling.
        (
            1,
            ("5000", "5001", "5001", "5001"),
            filled((SESSION_OPEN, "ESH2026", MARCH_6)),
            ("5000", "5001", "5001", "5001"),
        ),
        # No tradeable price before the roll: the market stands at its first mark until then.
        (0, (None, "5021", "5021", "5022"), filled(), ("5001", "5001", "5001", "5002")),
    ],
)
def test_a_rolls_gap_is_taken_off_the_marks_the_engine_moved_by_it(
    position: int,
    marks: Marks,
    fills: pl.DataFrame,
    levels: tuple[str, str, str, str],
) -> None:
    decisions = market_values(account(position, marks), fills, (MARCH_9_ROLL,), ES)

    assert decisions.get_column("market").to_list() == worth_of(levels)


def worth_of(levels: tuple[str, str, str, str]) -> list[int]:
    """One ES lot's value at each of `levels`, in micro-units."""
    return [int(Decimal(level) * 50) * 10**6 for level in levels]


MARCH_10_ROLL = EngineRoll(
    trade_date=day_number(MARCH_10),
    session_open=500,
    rolled_from="ESM2026",
    contract="ESU2026",
    gap=10_000_000_000,
    reason=RollReason.VOLUME,
)
"""A second roll, at the open of the session the last decision is in."""


@pytest.mark.parametrize(
    ("position", "marks", "fills"),
    [
        # Flat: each gap off the marks from its own instant on.
        (0, ("5000", "5021", "5022", "5033"), filled()),
        # Held: the first roll's legs filled at 350; the second's still on their way at the end.
        (
            1,
            ("5000", "5001", "5022", "5023"),
            filled((350, "ESH2026", MARCH_9), (350, "ESM2026", MARCH_9)),
        ),
    ],
)
def test_each_of_two_rolls_takes_its_own_gap_off(
    position: int, marks: Marks, fills: pl.DataFrame
) -> None:
    # The ponytail review: the gaps add up, each roll's legs judged by its own trade date.
    decisions = market_values(
        account(position, marks, (MARCH_6, MARCH_6, MARCH_9, MARCH_10)),
        fills,
        (MARCH_9_ROLL, MARCH_10_ROLL),
        ES,
    )

    assert decisions.get_column("market").to_list() == worth_of(("5000", "5001", "5002", "5003"))


def test_a_crypto_pairs_lot_is_a_coin() -> None:
    # The engine review: the market is one unit of what a run's sizes count, a coin of BTC, not
    # one of the dataset's steps of 0.001.
    bitcoin = InstrumentParameters(
        tick=100_000_000, money_per_point=1_000, lot_step=Decimal("0.001")
    )
    marked = pl.DataFrame(
        {
            "ts": [int(datetime(2026, 3, 7, 1, tzinfo=UTC).timestamp()) * 10**9],
            "trade_date": [date(2026, 3, 7)],
            "cash": [50_000_000_000],
            "position": [0],
            "mark": [60_000_100_000_000],
            "equity": [50_000_000_000],
        }
    ).cast(EQUITY)

    decisions = market_values(marked, filled(), (), bitcoin)

    assert decisions.get_column("market").to_list() == [60_000_100_000]
