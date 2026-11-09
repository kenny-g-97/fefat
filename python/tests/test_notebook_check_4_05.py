"""The check notebook of step 4.5 (Your checks) runs top to bottom, as Run All does: a snippet that
sleeps for 30 seconds under a 5-second timeout comes back `timed_out` after about 5 seconds, and
leaves no runner running and nothing in the executions' folder."""

import re
from pathlib import Path

import pytest

from fefat_app.execution import ExecutionTimedOut
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "4.05.ipynb"


def test_the_check_notebook_stops_a_sleeping_snippet_at_its_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "30% Running the snippet"
    assert re.fullmatch(r"timed_out after \d+\.\d s", printed[1])
    assert printed[2:] == [
        "No runner still runs: PASSED",
        "Nothing left in the executions' folder: PASSED",
    ]
    assert check["result"] == ExecutionTimedOut()
    assert 5 <= check["took"] < 10
