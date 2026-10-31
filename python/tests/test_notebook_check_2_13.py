"""The check notebook of step 2.13 (Your checks, Done means 3) runs top to bottom, as Run All does,
on ten generated sessions instead of five years (`FEFAT_CHECK_DAYS`): with no MES in the store it
says so and opens the trade paths of a run on the generated days, every path of fidelity `1m`; the
losing trade it picks has its most adverse point at its MAE and ends at its exit price; and the
measurement prints both strategies' files and engine times. Its plot draws on matplotlib's Agg
backend, and the store it points the runs at is given back."""

import os
from pathlib import Path

import pytest

from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.13.ipynb"


def test_the_check_notebook_plots_a_losing_trades_path_and_measures_what_paths_cost(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEFAT_CHECK_DAYS", "10")
    monkeypatch.setenv("MPLBACKEND", "Agg")
    store = os.environ["FEFAT_DATA_DIR"]

    with pytest.warns(UserWarning, match="F-FEE-01"):
        cells = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    lines = printed.splitlines()
    assert "10 sessions from 2026-03-06 to 2026-03-19, ready in" in printed
    assert "No MES 1-minute bars in your store" in printed
    assert [str(path.fidelity) for path in cells["run"].record.path_fidelities] == ["1m"]
    trade = cells["TRADE"]
    assert trade["pnl"] < 0
    mae = trade["mae_ticks"]
    assert f"Its most adverse point lies its MAE of {mae} ticks from its entry: True" in lines
    assert "Its path ends at its exit price: True" in lines
    for name in ("breakout", "days-long"):
        assert any(line.startswith(f"{name}: ") for line in lines), name
    assert sum(line.startswith("  engine with paths ") for line in lines) == 2
    assert os.environ["FEFAT_DATA_DIR"] == store
