"""The engine tutorial (step 2.15, Done means 2) runs top to bottom, as Run All does: on the
fixtures' ES here, as on your MES, it loads the bars, defines its features inline, runs the
strategy and times it, reads its metrics, explains and plots a trade stopped out at a loss, runs
the fidelity check on ten generated sessions with ticks instead of the year (`FEFAT_CHECK_DAYS`),
and compares nine variants; the store it points the check at is given back. Its plot draws on
matplotlib's Agg backend."""

import os
from pathlib import Path

import pytest

from fefat.backtest import FidelityCheck
from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "02-engine-tutorial.ipynb"


def test_the_tutorial_runs_top_to_bottom(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_with("ohlcv-1m")
    monkeypatch.setenv("FEFAT_CHECK_DAYS", "10")
    monkeypatch.setenv("MPLBACKEND", "Agg")
    store = os.environ["FEFAT_DATA_DIR"]

    with pytest.warns(UserWarning, match="F-FEE-01"):
        cells = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "ES from synthetic: " in printed
    assert "Ran in " in printed
    assert cells["run"].metrics.trades.trades > 0
    assert cells["TRADE"]["exit_reason"] == "stop"
    assert cells["EXPLANATION"].fills
    assert "10 sessions from 2026-01-02 to 2026-01-15 ready" in printed
    assert isinstance(cells["CHECK"], FidelityCheck)
    assert cells["VARIANTS"].height == 9
    assert os.environ["FEFAT_DATA_DIR"] == store
