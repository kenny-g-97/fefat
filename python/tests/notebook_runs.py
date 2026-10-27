"""Running a notebook in a test as Run All does, on a store of the synthetic fixtures."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from fefat.config import resolve_paths

SYNTHETIC = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
SCENARIOS = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
TICK_FIDELITIES = frozenset({"trades", "tbbo"})


def scenario_fidelities() -> list[str]:
    """Each scenario file's fidelity as its `fidelity:` line writes it, read apart from
    `fefat.reference.scenarios`, so that a scenario the loader drops still counts."""
    fidelities = []
    for path in sorted(SCENARIOS.glob("S-*.yaml")):
        found = re.search(r"^fidelity: (\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        assert found is not None, f"Expected a fidelity line in {path.name}, got none"
        fidelities.append(found[1])
    return fidelities


def store_with(*schemas: str) -> None:
    """The data folder holding the fixtures' datasets of `schemas` from the provider
    `synthetic`: ES's contracts ESH2026 and ESM2026, which roll at the open of 2026-03-09, and
    BTCUSDT-PERP."""
    data_dir = resolve_paths(os.environ).data_dir
    for schema in schemas:
        shutil.copytree(SYNTHETIC / schema, data_dir / "synthetic" / schema)


def run_notebook(notebook: Path) -> dict[str, Any]:
    """Run the notebook's code cells in order in one namespace, as Run All does, and return the
    namespace."""
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    namespace: dict[str, Any] = {}
    for number, cell in enumerate(cells):
        if cell["cell_type"] == "code":
            exec(compile("".join(cell["source"]), f"cell {number}", "exec"), namespace)
    return namespace
