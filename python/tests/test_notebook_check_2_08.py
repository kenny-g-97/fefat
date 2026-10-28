"""The check notebook of step 2.8 (Your checks) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: it prints the example strategy's specification with its two targets and
its breakeven, runs it on the store's last week through both engines, which agree, and lists its
trades one row per exit with the exit's reason."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"


def test_the_check_notebook_runs_the_example_through_both_engines_and_lists_its_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOKS / "checks" / "2.08.ipynb")

    printed = capsys.readouterr().out
    assert '"after_target"' in printed
    assert '"fraction": 0.5' in printed
    assert "The Rust engine agrees with the reference engine on the week." in printed
    assert check["comparison"].differences() == ()
    exits = check["table"]
    assert exits.height == len(check["TRADES"])
    reasons = set(exits.get_column("exit reason"))
    assert "target_1" in reasons
    assert reasons <= {
        "stop",
        "target_1",
        "target_2",
        "flat_by",
        "signal_exit",
        "exit",
    }
