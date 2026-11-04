"""The check notebook of step 3.5 (Your checks) runs top to bottom, as Run All does, on the
fixtures' ES bars: it prints RSI(14) on three 5-minute bars of the last trade date, for the
trader to read beside a chart's, and the same RSI from TA-Lib past the warm-up, which agrees."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.05.ipynb"


def test_the_check_notebook_prints_three_rsi_values_and_agrees_with_talib(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert (
        printed[0]
        == "ES 5-minute bars from 2026-02-07 to 2026-03-09, contract ESM2026 on 2026-03-09"
    )
    starts = [line.split(": close ")[0] for line in printed[1:4]]
    assert starts == ["09:00 to 09:05 Chicago", "12:00 to 12:05 Chicago", "14:00 to 14:05 Chicago"]
    assert all(", RSI(14) " in line for line in printed[1:4])
    assert printed[4].startswith("RSI(14) and TA-Lib's on the 202 bars past the warm-up: ")
    assert printed[4].endswith(" apart: PASSED")
    assert check["gap"] <= 1e-7
