"""`ff.backtest.run` against the reference engine (step 2.10, D-10): the whole pipeline, the
signal frame, the engine cache across the fixtures' roll of 2026-03-09, the fee table, and the
engine through its bindings, fills on the 1-minute bars as the reference does on the same spliced
bars with the same rolls; the first backtest's trades (step 2.2) are the reference's, and a
position held across the roll is one trade whose profit and loss its fills make."""

from datetime import time as clock
from decimal import Decimal

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import RunConfig
from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.fees import TABLES
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.reference.costs import RunFees
from fefat.reference.engine import ReferenceEngine
from fefat.reference.hours import CalendarHours
from fefat.reference.ledger import trades_of
from fefat.reference.rolls import tape_across_rolls
from fefat.reference.rust_batch import FillView
from fefat.reference.settings import RunSettings
from fefat.reference.strategy import decisions_of
from fefat.reference.template import TemplateStrategy
from fefat.reference.timeline import RunResult
from fefat.reference.units import instrument_parameters
from notebook_runs import store_with

START, END = "2026-03-06", "2026-03-09"
ONE_MINUTE = Timeframe.parse("1m")
FEES = "retail-default"


def local_close() -> pl.Expr:
    return (
        pl.from_epoch("ts_close", time_unit="ns")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/Chicago")
        .dt.time()
    )


def first_backtest() -> ff.SignalStrategy:
    """Step 2.2's strategy as `notebooks/checks/2.03.ipynb` writes it: a long when the 5-minute
    close crosses above the mean of the last 20 between 08:30 and 15:00 Chicago, a stop of 12
    ticks and a target of 24, out at the first close from 15:05."""
    cross_up = (pl.col("close") > pl.col("mean")) & (
        pl.col("close").shift(1) <= pl.col("mean").shift(1)
    )
    in_hours = pl.col("local_close").is_between(clock(8, 30), clock(15, 0), closed="left")
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"mean": pl.col("close").rolling_mean(20), "local_close": local_close()},
        long_entry=cross_up & in_hours,
        short_entry=pl.lit(False),
        long_exit=pl.col("local_close") >= clock(15, 5),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=12),
            targets=[ff.Target(ticks=24)],
            sizing=ff.Fixed(1),
        ),
    )


def breakout() -> ff.SignalStrategy:
    """A long on a close above the highest of the 12 closes before it, a stop of 12 ticks and a
    target of 24, which holds a position across the roll."""
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"highest": pl.col("close").rolling_max(12).shift(1)},
        long_entry=pl.col("close") > pl.col("highest"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=12),
            targets=[ff.Target(ticks=24)],
            sizing=ff.Fixed(1),
        ),
    )


def reference_run(strategy: ff.SignalStrategy) -> RunResult:
    """`strategy` through the reference engine's template on the spliced 1-minute bars of ES,
    across the roll calendar's rolls, paying the fee table's fees."""
    paths = resolve_paths(__import__("os").environ)
    sessions = instrument_table(paths.data_dir).sessions_of("ES", paths.cache_dir)
    parameters = instrument_parameters(instruments.get("ES"))
    signals = strategy.signals(ff.market.load("ES", "5m", START, END)).collect()
    minutes = ff.market.load("ES", "1m", START, END).collect()
    tape, rolls = tape_across_rolls(minutes, ff.market.roll_calendar("ES"))
    hours = CalendarHours.around(sessions, tape[0].starts_at(), tape[-1].available_at())
    fees = RunFees.of_table(TABLES[FEES], "ES")
    settings = RunSettings.for_fidelity(ONE_MINUTE)
    engine = ReferenceEngine(settings, parameters, ONE_MINUTE, hours, fees=fees)
    template = TemplateStrategy(strategy.to_spec(), signals, parameters, sessions)
    contract = minutes.get_column("contract").item(0)
    return engine.run(tape, decisions_of(signals), template.on_bar, contract=contract, rolls=rolls)


def backtest(strategy: ff.SignalStrategy) -> ff.backtest.Run:
    config = RunConfig(fidelity=ONE_MINUTE, fee_table=FEES)
    with pytest.warns(UserWarning, match="F-FEE-01"):
        return ff.backtest.run(strategy, START, END, config)


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")


def test_the_first_backtests_fills_and_trades_are_the_reference_engines() -> None:
    run = backtest(first_backtest())
    reference = reference_run(first_backtest())

    fills = tuple(FillView.of_row(row) for row in run.fills.iter_rows(named=True))
    assert fills == tuple(FillView.of(fill) for fill in reference.fills)
    expected = trades_of(reference.fills)
    trades = run.trades.sort("exit_ts")
    assert trades.height == len(expected) > 0
    for row, trade in zip(trades.iter_rows(named=True), expected, strict=True):
        assert (row["entry_ts"], row["entry_price"]) == (trade.entry_ts, trade.entry_price)
        assert (row["exit_ts"], row["exit_price"]) == (trade.exit_ts, float(trade.exit_price))
        assert (row["exit_reason"], row["lots"]) == (str(trade.exit_reason), trade.lots)
        assert (row["gross_pnl"], row["fees"]) == (trade.pnl, trade.fees)


def test_a_position_held_across_the_roll_is_one_trade_its_fills_make() -> None:
    # BACKLOG's trades across a roll (§20) and cache reader across rolls (F-ROL-01).
    run = backtest(breakout())
    reference = reference_run(breakout())

    fills = tuple(FillView.of_row(row) for row in run.fills.iter_rows(named=True))
    assert fills == tuple(FillView.of(fill) for fill in reference.fills)
    across = run.trades.filter(pl.col("rolls") == 1)
    assert across.select("entry_contract", "exit_contract").rows() == [("ESH2026", "ESM2026")]
    legs = run.fills.filter(pl.col("role") == "roll_volume")
    assert legs.get_column("contract").to_list() == ["ESH2026", "ESM2026"]
    summary = run.record.summary
    assert summary.position == 0
    assert summary.cash - Decimal(50_000) == summary.pnl
    assert [roll.contract for roll in run.record.rolls] == ["ESM2026"]
