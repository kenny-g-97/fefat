"""A saved run's market exposure and buy and hold (step 5.23, D-121, D-123): a run long one lot
from its first decision to its last, without costs, has a correlation of 1 and a beta of one lot,
and the beta's lots of the market's change plus the alpha is the run's days summed (Done means 3);
buy and hold at one lot is that run's account, across a roll whose gap the market's day leaves
out, its drawdown the engine's running drawdown on that walk; the same days a trade date later
correlate near zero on a random walk; a run that never trades has no correlation; a roll's legs
on their way leave the old contract's level in the marks; buy and hold at the run's volatility is
one lot's figures at its lots; and fewer than three days leave nothing to count."""

import random
import statistics
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import RunConfig, run_config
from fefat.backtest import requests as run_requests
from fefat.backtest import run_inputs as run_documents
from fefat.backtest.artifacts import read_artifact
from fefat.backtest.exposure import Comoments, Uncounted, daily_moves, market_values
from fefat.backtest.record import RollRecord
from fefat.backtest.schemas import EQUITY
from fefat.market import fees
from fefat.market.engine_units import InstrumentParameters, micro_units, money_text
from fefat.market.fees import TABLES, FeeSchedule, FeeTable, FuturesFee
from fefat.market.roll_decisions import RollReason
from fefat.reference.settings import SlippageTicks
from generated_minutes import FEBRUARY, write_minutes
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


def days_of(run: ff.backtest.Run) -> pl.DataFrame:
    """The run's and the market's days as `market_exposure` pairs them."""
    equity = read_artifact(run.folder, "equity")
    decisions = market_values(equity, run.fills, run.record.rolls, ES)
    return daily_moves(decisions, micro_units(run.config.capital))


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


def test_the_same_days_a_trade_date_later_correlate_near_zero_on_a_random_walk() -> None:
    draws = random.Random(523)
    market = [draws.randint(-40, 40) * 12_500_000 for _ in range(1_001)]

    later = Comoments.of(market[1:], market[:-1]).days_exposure()
    alike = Comoments.of(market[1:], market[1:]).days_exposure()

    assert (alike.correlation, alike.beta_lots) == (1, 1)
    assert later.correlation is not None
    assert abs(later.correlation) < 0.1


def test_a_run_that_never_trades_has_no_correlation() -> None:
    write_minutes(FEBRUARY)
    run = ff.backtest.run(NEVER, *ACROSS_THE_ROLL)

    exposure = ff.backtest.market_exposure(run)

    every = exposure.all_days
    assert (every.correlation, every.explained_share) == (None, None)
    assert every.uncounted == Uncounted.RUN_NEVER_DIFFERED
    assert (every.beta_lots, every.alpha) == (0, 0)
    held = exposure.buy_and_hold
    assert held.at_one_lot.net_pnl != 0
    assert (held.at_run_volatility, held.curve) == (None, None)
    assert held.uncounted == Uncounted.RUN_NEVER_DIFFERED


def test_buy_and_hold_at_the_runs_volatility_is_one_lots_figures_at_its_lots() -> None:
    # On a run of trades and costs: its days are its metrics', the beta's lots of the market's
    # change plus the alpha is its days summed, and the days the market fell, rose, or stood
    # still are all its days.
    write_minutes(FEBRUARY)
    run = ff.backtest.run(breakout_both_ways(), *ACROSS_THE_ROLL)

    exposure = ff.backtest.market_exposure(run)

    days = days_of(run)
    assert days.get_column("run").to_list() == run.equity("1d")["pnl"].to_list()
    market, made = days.get_column("market").to_list(), days.get_column("run").to_list()
    every, held = exposure.all_days, exposure.buy_and_hold
    assert every.correlation is not None
    assert every.beta_lots is not None
    assert every.alpha is not None
    market_change = float(held.at_one_lot.net_pnl)
    assert every.beta_lots * market_change + every.alpha == pytest.approx(sum(made) / 10**6)
    still = sum(1 for moved in market if moved == 0)
    assert exposure.falling_days.days + exposure.rising_days.days + still == every.days
    sized, one_lot = held.at_run_volatility, held.at_one_lot
    assert sized is not None
    assert sized.lots == pytest.approx(statistics.stdev(made) / statistics.stdev(market))
    for figure in ("net_pnl", "max_drawdown"):
        exact = getattr(one_lot, figure) * Decimal(sized.lots)
        assert abs(getattr(sized, figure) - exact) <= Decimal("0.000001"), figure
    assert (sized.longest_drawdown_days, sized.sharpe) == (
        one_lot.longest_drawdown_days,
        one_lot.sharpe,
    )
    assert held.curve is not None
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
    assert held.at_one_lot.net_pnl == Decimal(money_text(sum(days_of(run)["market"])))
    assert (held.at_run_volatility, held.uncounted) == (None, Uncounted.TOO_FEW_DAYS)


MARCH_9_ROLL = RollRecord(
    trade_date=date(2026, 3, 9),
    rolled_from="ESH2026",
    contract="ESM2026",
    gap=Decimal(20),
    reason=RollReason.VOLUME,
)


def account(position: int, marks: tuple[str, str, str]) -> pl.DataFrame:
    """Three decisions, the first before the roll of 03-09 and two after it, holding `position`
    after the first, at `marks`."""
    units = [int(Decimal(mark) * 10**9) for mark in marks]
    return pl.DataFrame(
        {
            "ts": [100, 200, 400],
            "trade_date": [date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 9)],
            "cash": [50_000_000_000] * 3,
            "position": [position] * 3,
            "mark": units,
            "equity": [50_000_000_000] * 3,
        },
        schema=EQUITY,
    )


def filled(*fills: tuple[int, str]) -> pl.DataFrame:
    """Fills at their instants on their contracts, all on 03-09, after the roll."""
    return pl.DataFrame(
        {
            "ts": [ts for ts, _ in fills],
            "contract": [contract for _, contract in fills],
            "trade_date": [date(2026, 3, 9)] * len(fills),
        },
        schema={"ts": pl.Int64, "contract": pl.String, "trade_date": pl.Date},
    )


@pytest.mark.parametrize(
    ("position", "marks", "fills"),
    [
        # Flat at the roll: the mark moved by the gap at once (F-ROL-03).
        (0, ("5000", "5021", "5022"), filled()),
        # An entry on the new front after the roll, which no leg was waiting for.
        (0, ("5000", "5021", "5022"), filled((300, "ESM2026"))),
        # Held: valued at the old contract's price until the close leg filled at 300.
        (1, ("5000", "5001", "5022"), filled((300, "ESH2026"), (300, "ESM2026"))),
        # Held, the legs still on their way when the run ended.
        (1, ("5000", "5001", "5002"), filled()),
    ],
)
def test_a_rolls_gap_is_taken_off_the_marks_the_engine_moved_by_it(
    position: int, marks: tuple[str, str, str], fills: pl.DataFrame
) -> None:
    decisions = market_values(account(position, marks), fills, (MARCH_9_ROLL,), ES)

    worth = [250_000_000_000, 250_050_000_000, 250_100_000_000]
    assert decisions.get_column("market").to_list() == worth
