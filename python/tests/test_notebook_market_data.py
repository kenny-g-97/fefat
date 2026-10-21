"""The market-data notebook (step 1.11) runs top to bottom, as Run All does, on a store of
synthetic data, and skips with a message the cells whose data the store lacks."""

import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fefat.config import resolve_paths
from fefat.market.bars_check import ComparisonStatus
from fefat_app.cli import main

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "01-market-data.ipynb"
SYNTHETIC = ROOT / "fixtures" / "synthetic"
NINJATRADER_SAMPLE = SYNTHETIC / "exports" / "ninjatrader" / "ES 03-26.Last.txt"


def store_with(*schemas: str) -> None:
    """The data folder holding the fixtures' datasets of `schemas` from the provider
    `synthetic`: ES's contracts ESH2026 and ESM2026, which roll at the open of 2026-03-09, and
    BTCUSDT-PERP."""
    data_dir = resolve_paths(os.environ).data_dir
    for schema in schemas:
        shutil.copytree(SYNTHETIC / schema, data_dir / "synthetic" / schema)


def run_notebook() -> dict[str, Any]:
    """Run the notebook's code cells in order in one namespace, as Run All does, and return the
    namespace."""
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    namespace: dict[str, Any] = {}
    for number, cell in enumerate(cells):
        if cell["cell_type"] == "code":
            exec(compile("".join(cell["source"]), f"cell {number}", "exec"), namespace)
    return namespace


def test_the_notebook_runs_on_your_bars_and_on_an_import_through_a_preset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")
    main(["data", "import", "file", str(NINJATRADER_SAMPLE), "--profile", "ninjatrader"])
    capsys.readouterr()

    namespace = run_notebook()

    printed = capsys.readouterr().out
    # Without MES, the notebook takes the 1-minute bars with the most contracts: the fixtures'
    # ES, whose year holds the roll to ESM2026, from an offset of 0 on ESH2026.
    assert (namespace["ROOT"], namespace["PROVIDER"]) == ("ES", "synthetic")
    rolls = namespace["rolls"]
    assert rolls.select("trade_date", "rolled_from", "contract").rows() == [
        (date(2026, 3, 9), "ESH2026", "ESM2026")
    ]
    assert rolls.item(0, "step") == rolls.item(0, "adj_offset")
    report = namespace["report"]
    assert report.comparisons_run() > 0
    assert report.difference_count() == 0
    assert "Differences: none." in printed
    assert "Skipped until a trades file of ES is imported" in printed
    imported = namespace["IMPORTED"]
    assert (imported["provider"], imported["root"]) == ("ninjatrader", "ES")
    assert namespace["quality"].summary() in printed


def test_the_notebook_rebuilds_bars_from_trades_and_skips_the_import_it_lacks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m", "trades")

    namespace = run_notebook()

    printed = capsys.readouterr().out
    assert namespace["ticks"].status is ComparisonStatus.COMPARED
    assert namespace["report"].difference_count() == 0
    assert "Skipped until a trades file" not in printed
    assert namespace["IMPORTED"] is None
    assert "Skipped: no dataset imported through a preset" in printed


def test_the_notebook_says_what_to_do_on_a_store_without_minute_bars() -> None:
    with pytest.raises(ValueError, match=r"Expected 1-minute bars .* import your files first"):
        run_notebook()
