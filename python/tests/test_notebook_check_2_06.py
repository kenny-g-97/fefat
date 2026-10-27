"""The check notebook of step 2.6 (Your checks) runs top to bottom, as Run All does: the
scenarios on ticks through both engines, S-fill-012's gap through a stop filled at 4990.25 by
both, and 1,000 drawn tapes ending with the line `0 differences`."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"


def test_the_check_notebook_compares_both_engines_and_prints_no_difference(
    capsys: pytest.CaptureFixture[str],
) -> None:
    check = run_notebook(NOTEBOOKS / "checks" / "2.06.ipynb")

    printed = capsys.readouterr().out
    assert "28 scenarios on ticks: 28 agree with the reference engine" in printed
    assert "Rust fills: order 1 sell 1 at 4990.25 at 2026-03-06T14:30:01.25Z (F-STP-03" in printed
    assert "1000 drawn tapes through both engines" in printed
    assert printed.rstrip().splitlines()[-1] == "0 differences"
    assert check["differing"] == []
