"""The first backtest notebook (step 2.2) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: it backtests the contract that was the front longest at bar fidelity
and the same strategy on the fixtures' ES trades at tick fidelity, and prints each trade list
with its entries, exits, prices, and reasons (Done means 3)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.reference.units import money_text
from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "02-first-backtest.ipynb"


def test_the_notebook_backtests_the_front_on_bars_and_the_fixtures_on_ticks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    namespace = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    # The fixtures' fronts are ESH2026 on 2026-03-06 and ESM2026 on 03-09, one session each, and
    # the later one is taken; the dataset's first session, 03-05, has no front.
    chosen = ("ROOT", "PROVIDER", "CONTRACT", "START", "END")
    assert tuple(namespace[name] for name in chosen) == (
        "ES",
        "synthetic",
        "ESM2026",
        date(2026, 3, 9),
        date(2026, 3, 9),
    )
    runs = (("result", "TRADES", "1m", "zone"), ("tick_result", "TICK_TRADES", "trades", "es_zone"))
    for result_name, trades_name, fidelity, zone in runs:
        result, trades = namespace[result_name], namespace[trades_name]
        assert trades, f"expected {result_name} to trade"
        assert {str(fill.fidelity) for fill in result.fills} == {fidelity}
        assert result.position == 0
        assert money_text(sum(trade.pnl for trade in trades)) in printed
        listed = namespace["trade_list"](trades, namespace[zone])
        assert listed.columns == [
            "entry",
            "exit",
            "side",
            "entry_price",
            "exit_price",
            "reason",
            "pnl",
        ]
        same_day = listed.select(pl.col("entry").dt.date() == pl.col("exit").dt.date())
        assert same_day.to_series().all()


def test_the_notebook_says_what_to_do_on_a_store_without_minute_bars() -> None:
    with pytest.raises(ValueError, match=r"Expected 1-minute bars .* import your files first"):
        run_notebook(NOTEBOOK)
