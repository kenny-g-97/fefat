"""The check notebook of step 2.10 (Your checks) runs top to bottom, as Run All does, on a store
of synthetic 1-minute bars: it runs the first backtest's strategy through `ff.backtest.run` and
through the reference engine on the window `notebooks/02-first-backtest.ipynb` takes, finds no
difference between their trade lists, and reads the run back on a second call."""

import os
from pathlib import Path

import pytest

from fefat.config import resolve_paths
from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.10.ipynb"


def test_the_check_notebook_finds_the_reference_engines_trades_and_reads_the_run_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    with pytest.warns(UserWarning, match="F-FEE-01"):
        check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "Differences: 0" in printed
    assert check["REFERENCE"]
    assert check["DIFFERENCES"].is_empty()
    assert check["run"].trades.height == len(check["REFERENCE"])
    assert check["run"].folder.parent == resolve_paths(os.environ).runs_dir
    assert "the same key: True" in printed
