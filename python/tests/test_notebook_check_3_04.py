"""The check notebook of step 3.4 (Your checks) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: a feature reading the next bar fails its validation with the first cut and
row, and the same feature reading the bar before passes."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.04.ipynb"


def test_the_check_notebook_fails_a_feature_reading_ahead_and_passes_it_reading_behind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    leaky, fixed = check["leaky"], check["fixed"]
    window = "on ES 5m from 2026-02-23 to 2026-03-09"
    assert printed[0] == "ES 5-minute bars from 2026-02-23 to 2026-03-09"
    assert printed[1] == f"neighbour_close() {window}, seed {leaky.seed}: FAILED"
    assert (
        " fail, the first at 2026-03-06T22:00:00Z (session_close): neighbour_close at "
        in (printed[2])
    )
    assert printed[2].endswith("with the data after the cut and None without it")
    assert printed[3].startswith("start check from 2026-03-09")
    assert printed[4].startswith('lint: line 3: return pl.col("close").shift(-1): a negative')
    assert printed[5] == f"neighbour_close() {window}, seed {fixed.seed}: PASSED"
    assert printed[6].startswith("cuts: none of ")
    assert printed[8] == "lint: no finding"
    assert not leaky.passed
    assert fixed.passed
