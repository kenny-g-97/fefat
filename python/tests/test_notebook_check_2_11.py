"""The check notebook of step 2.11 (Your checks) runs top to bottom, as Run All does, on a store
of synthetic 1-minute bars: it prints the first backtest's metrics and its robustness verdict, and
explains its first trade stopped out at a loss, whose stop's fill shows its rule and slippage and
the bar that reached the stop, the two engines' fills alike."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.11.ipynb"


def test_the_check_notebook_prints_the_metrics_and_explains_a_losing_trade(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    with pytest.warns(UserWarning, match="F-FEE-01"):
        check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert check["METRICS"] == check["run"].metrics
    assert "Verdict: " in printed
    assert "red flags: " in printed and "short_test_period" in printed
    explanation = check["EXPLANATION"]
    assert explanation.trade_id == check["TRADE"]
    assert len(explanation.fills) == 2
    # The Phase 2 exit: the notebook shows the explanation as display output, not printed text,
    # which a runner keeping printed text would pass on with the store's prices (D-21).
    assert "(F-STP-04, taker, 1 ticks)" in explanation.text()
    assert "reached the stop at" in explanation.text()
