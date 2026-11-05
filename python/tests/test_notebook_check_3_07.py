"""The check notebook of step 3.7 (Your checks) runs top to bottom, as Run All does, on two weeks
of generated ES bars: `rsi_stretch`, RSI(14) less its mean over ten bars, is built with the
combinators, passes the leak detector, is saved with the RSI it reads, and runs in a strategy
beside RSI(14), both read from the library by version, whose run names both versions and opens
again from its request."""

import os
from pathlib import Path

import pytest

import gen_fixtures
from fefat.config import resolve_paths
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.07.ipynb"
RETURN = '    return pl.col("rsi") - pl.col("rsi").rolling_mean(10)'
"""The line of the feature's code that combines RSI(14) and its mean."""


@pytest.fixture(name="two_weeks_of_es")
def fixture_two_weeks_of_es() -> None:
    """ESH2026's 1-minute bars from 2026-03-02 to 03-13, and its ticks of 03-13."""
    synthetic = resolve_paths(os.environ).data_dir / "synthetic"
    dates = ["--dates", "2026-03-02..2026-03-13", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(synthetic), *dates, "--ticks-from", "2026-03-13"]) == 0


@pytest.mark.usefixtures("two_weeks_of_es")
def test_the_check_notebook_builds_validates_saves_and_runs_a_combination(
    capsys: pytest.CaptureFixture[str],
) -> None:
    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "ES 5-minute bars from 2026-02-27 to 2026-03-13"
    assert printed[1] == "@ff.feature("
    assert any('FeatureInput(name="rsi", hash="' in line for line in printed)
    assert any('parameters={"n": 14})' in line for line in printed)
    assert RETURN in printed
    assert "Its description: a subtract of a feature and a rolling_mean" in printed
    assert "The leak detector on ES's 5-minute bars: PASSED" in printed
    assert "It read: rsi {'n': 14}" in printed
    assert "  rsi version 1" in printed
    assert "  rsi_stretch version 1, a combination" in printed
    assert "The run names the versions your library keeps: PASSED" in printed
    assert "The second run opened the first: PASSED" in printed
    assert check["run"].record.summary.trades > 0
    assert [pin.slot for pin in check["pins"]] == ["stretch", "rsi"]
