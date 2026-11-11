"""The check notebook of step 5.2 runs top to bottom, as Run All does (Done means 1, from a
notebook): it saves two versions of the breakout template through `ff.strategy`, prints the diff
of their code, and sees a version with a syntax error refused at its line; run again, it reads
its versions back and writes nothing."""

import os
from pathlib import Path

import pytest

from fefat.config import resolve_paths
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "5.02.ipynb"
VERDICT = [
    "Two versions saved: PASSED",
    "The diff shows the wider stop: PASSED",
    "The syntax error is refused at its line: PASSED",
]


def test_the_check_notebook_saves_two_versions_and_shows_their_diff(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "check_breakout v1 and v2 on MES 5m"
    assert printed[1:3] == ["--- check_breakout v1", "+++ check_breakout v2"]
    assert "-def strategy(lookback: int = 12, stop_atr: float = 1.5) -> ff.SignalStrategy:" in (
        printed
    )
    assert "+def strategy(lookback: int = 12, stop_atr: float = 2.0) -> ff.SignalStrategy:" in (
        printed
    )
    assert "Refused at line 10: SyntaxError: invalid syntax" in printed
    assert printed[-3:] == VERDICT


def test_the_check_notebook_run_again_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    run_notebook(NOTEBOOK)
    folder = resolve_paths(os.environ).strategies_dir / "check_breakout"
    before = {path.name: path.stat().st_mtime_ns for path in folder.iterdir()}

    run_notebook(NOTEBOOK)

    assert {path.name: path.stat().st_mtime_ns for path in folder.iterdir()} == before
    assert capsys.readouterr().out.splitlines()[-3:] == VERDICT
