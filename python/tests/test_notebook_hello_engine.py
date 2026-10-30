"""`notebooks/00-hello-engine.ipynb` runs top to bottom, as Run All does, and prints the maximum
drawdown its markdown works out by hand, 130, through the engine's running drawdown (step 2.11)."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "00-hello-engine.ipynb"


def test_the_hello_engine_notebook_prints_the_maximum_drawdown_its_markdown_works_out(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_notebook(NOTEBOOK)

    assert capsys.readouterr().out.splitlines()[-2:] == ["[0, 40, 10, 130, 80, 90]", "130"]
