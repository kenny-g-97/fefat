"""The check notebook of step 2.12 (Your checks) runs top to bottom, as Run All does, on ten
generated sessions instead of a year (`FEFAT_CHECK_DAYS`): it prints the run's report, whose
fidelity eras are 1-minute bars and then trades and whose fidelity check reruns the last
sessions at 1 second and 1 minute; `fidelity_check` gives the check the run's metrics hold; and
with no MES in the store it says so. The store it points the run at is given back."""

import os
from pathlib import Path

import pytest

from fefat.backtest import FidelityCheck
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.12.ipynb"


def test_the_check_notebook_prints_the_eras_and_the_fidelity_check(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEFAT_CHECK_DAYS", "10")
    store = os.environ["FEFAT_DATA_DIR"]

    with pytest.warns(UserWarning, match="F-FEE-01"):
        check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    lines = printed.splitlines()
    assert "10 sessions from 2026-03-06 to 2026-03-19, ticks from 2026-03-17" in printed
    eras = lines.index("Fidelity eras")
    assert lines[eras + 1 : eras + 4] == [
        "  2026-03-09 to 2026-03-16     6 trade dates  1m",
        "  2026-03-17 to 2026-03-19     3 trade dates  trades",
        "",
    ]
    assert "Fidelity check from 2026-03-17 to 2026-03-19, each run from flat" in lines
    assert any(line.startswith("  at 1s: ") for line in lines)
    assert any(line.startswith("  at 1m: ") for line in lines)
    assert "fidelity_check(run) gives the check run.metrics holds: True" in lines
    assert any(line.startswith("The stop lies 12 ticks from the entry") for line in lines)
    assert "No MES 1-minute bars in your store" in printed
    assert isinstance(check["CHECK"], FidelityCheck)
    assert check["CHECK"] == check["run"].metrics.fidelity_check
    assert os.environ["FEFAT_DATA_DIR"] == store
