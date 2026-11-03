"""The check notebook of step 3.1 (Your checks) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: it defines a feature with a parameter, computes it on the bars, saves it,
prints its version record with its code, hash, and parameter schema, loads it back with the same
hash, and saves a changed default as version 2 while a changed character gives another hash; run
again, it writes nothing new."""

import json
import os
from pathlib import Path

import pytest

from fefat.config import resolve_paths
from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.01.ipynb"


def test_the_check_notebook_saves_a_feature_and_loads_it_back_with_the_same_hash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")
    folder = resolve_paths(os.environ).features_dir / "stretch"

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    record = json.loads((folder / "v1.json").read_text(encoding="utf-8"))
    assert {"code", "hash", "parameter_schema"} <= set(record)
    assert f'"hash": "{record["hash"]}"' in printed
    assert '"parameter_schema": {' in printed
    assert "def stretch(bars: pl.LazyFrame, n: int) -> pl.Expr:" in record["code"]
    assert "version 1, identical hash: True" in printed
    assert "all differ: True" in printed
    assert check["saved"].version == 1
    assert check["changed_default_version"].version == 2
    assert check["values"]["stretch"].drop_nulls().len() > 0

    run_notebook(NOTEBOOK)

    assert sorted(path.name for path in folder.iterdir()) == ["v1.json", "v2.json"]
