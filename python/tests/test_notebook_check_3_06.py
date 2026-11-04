"""The check notebook of step 3.6 (Your checks) runs top to bottom, as Run All does, on the
fixtures' ES bars: the session's VWAP starts again at its open, 17:00 Chicago the evening before
its trade date, the opening range from the cash open appears from the bar of 09:00 Chicago, and
the day's chart draws without a display."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.06.ipynb"


def test_the_check_notebook_shows_the_vwap_start_again_and_the_opening_range_appear(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "ES 5-minute bars of 2026-03-09, contract ESM2026"
    assert printed[1].startswith("First bar that traded opens 2026-03-08 17:00 Chicago: VWAP ")
    assert printed[2] == "The VWAP started again at the session's open: PASSED"
    assert printed[3].startswith("Opening range of 08:30 to 09:00 Chicago: high ")
    assert printed[4].startswith("Bars before 09:00 with a range: 0; from 09:00: ")
    assert printed[4].endswith(": PASSED")
    assert check["set_late"] == check["late"].height > 0
