"""The check notebook of step 2.7 (Your checks) runs top to bottom, as Run All does, on three
generated sessions instead of a year (`FEFAT_CHECK_DAYS`): every scenario through both engines in
both replays, each agreeing, S-fill-022's ambiguous fill and S-template-006's trade at a signal
close filled alike by both, and the sessions replayed skipping and in full, three runs each, to
one outcome, printed `identical`, with the line comparing their times."""

import re
from pathlib import Path

import pytest

from notebook_runs import TICK_FIDELITIES, run_notebook, scenario_fidelities

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"
AMBIGUOUS_FILL = (
    "Rust fills: order 1 sell 1 at 4994.75 at 2026-03-06T14:32:00Z (F-STP-04, taker, 1 ticks, "
    "ambiguous)"
)
FILLED_BEFORE_THE_DECISION = (
    "Rust fills: order 1 buy 1 at 5000.25 at 2026-03-06T14:30:00.2Z (F-MKT-02, taker, 1 ticks); "
    "order 2 sell 1 at 4999 at 2026-03-06T14:31:00Z (F-STP-03, taker, 1 ticks)"
)


def test_the_check_notebook_replays_generated_sessions_skipping_and_in_full_alike(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEFAT_CHECK_DAYS", "3")

    check = run_notebook(NOTEBOOKS / "checks" / "2.07.ipynb")

    printed = capsys.readouterr().out
    fidelities = scenario_fidelities()
    on_bars = sum(fidelity not in TICK_FIDELITIES for fidelity in fidelities)
    agreeing = f"{len(fidelities)} scenarios: {len(fidelities)} agree with the reference engine"
    assert f"{agreeing} in both replays" in printed, printed
    assert f"{on_bars} of them on bars" in printed
    assert AMBIGUOUS_FILL in printed
    assert FILLED_BEFORE_THE_DECISION in printed
    assert "generated 3 sessions in" in printed
    assert "identical" in printed.splitlines()
    assert len(check["outcomes"]) == 6
    assert check["outcomes"][0].fills
    assert re.search(r"the skipping engine is \d+\.\d times as fast as the full replay", printed)
