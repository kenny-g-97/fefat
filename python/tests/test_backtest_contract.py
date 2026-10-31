"""A run on one contract (step 2.14, D-59): `RunConfig.contract` reads that contract's bars
unspliced, as `load` reads a contract, so the run crosses no roll and needs no roll calendar,
where a run on the root follows the volume roll's fronts."""

from datetime import date

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import RunConfig
from notebook_runs import breakout, store_with

ACROSS_THE_ROLL = (date(2026, 3, 5), date(2026, 3, 9))
"""The fixtures roll from ESH2026 to ESM2026 at the open of 2026-03-09."""


def test_a_run_on_one_contract_stays_on_it_across_the_roll() -> None:
    store_with("ohlcv-1m")

    pinned = ff.backtest.run(breakout(), *ACROSS_THE_ROLL, RunConfig(contract="ESH2026"))
    spliced = ff.backtest.run(breakout(), *ACROSS_THE_ROLL)

    assert pinned.config.contract == "ESH2026"
    assert pinned.record.rolls == ()
    assert pinned.signals["contract"].unique().to_list() == ["ESH2026"]
    assert pinned.signals.filter(pl.col("trade_date") == date(2026, 3, 9)).height > 0
    assert spliced.config.contract is None
    assert [roll.contract for roll in spliced.record.rolls] == ["ESM2026"]
    assert pinned.hash != spliced.hash


def test_a_pinned_runs_trade_across_the_roll_explains_on_its_own_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`Run.explain` replays the trade on the run's one contract, not on the spliced series,
    whose other contract's prices would make the engines disagree."""
    store_with("ohlcv-1m")
    pinned = ff.backtest.run(breakout(), *ACROSS_THE_ROLL, RunConfig(contract="ESH2026"))
    last = pinned.trades.filter(pl.col("entry_trade_date") == date(2026, 3, 9))

    explanation = pinned.explain(int(last["entry_order"][-1]))

    assert explanation.fills
    assert "ESH2026" in capsys.readouterr().out


def test_a_contract_of_another_root_is_refused() -> None:
    store_with("ohlcv-1m")

    with pytest.raises(ValueError, match="Expected a contract of ES"):
        ff.backtest.run(breakout(), *ACROSS_THE_ROLL, RunConfig(contract="NQH2026"))
