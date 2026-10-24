"""The check notebook of step 2.3 (Your checks) runs top to bottom, as Run All does, on a store
of synthetic 1-minute bars: it prints the specification of the example strategy of
`02-engine-and-data.md` §5, evaluates its signal frame, and runs the first backtest's strategy
as a template, whose trades are those `notebooks/02-first-backtest.ipynb` makes by hand, with
its signal exit and with a flat-by time."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"


def test_the_check_notebook_prints_the_spec_and_trades_as_the_first_backtest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")
    by_hand = run_notebook(NOTEBOOKS / "02-first-backtest.ipynb")
    capsys.readouterr()

    check = run_notebook(NOTEBOOKS / "checks" / "2.03.ipynb")

    printed = capsys.readouterr().out
    assert '"kind": "atr"' in printed
    assert '"flat_by": "15:05"' in printed
    assert "Signal frame: " in printed
    assert check["TRADES"]
    assert check["TRADES"] == by_hand["TRADES"]
    assert check["result"].position == 0
    # The fixtures' one session holds no halt, so flat-by reads 15:05 as the signal exit does.
    assert check["FLAT_BY_TRADES"] == check["TRADES"]
