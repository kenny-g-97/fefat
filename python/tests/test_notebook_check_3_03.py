"""The check notebook of step 3.3 (Your checks) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: a year of the example RSI and ATR computed twice, the second call reading
the values the first kept, and the feature cache's folders of ES's 5-minute bars."""

import re
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from fefat.market import series_source as bar_source
from fefat.market.signal_grid import gridded_bars
from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.03.ipynb"


def test_the_check_notebook_computes_a_year_twice_and_lists_what_the_cache_holds(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_with("ohlcv-1m")
    built: list[tuple[Any, ...]] = []

    def counted_bars(*arguments: Any, **keywords: Any) -> pl.DataFrame:
        built.append(arguments)
        return gridded_bars(*arguments, **keywords)

    monkeypatch.setattr(bar_source, "gridded_bars", counted_bars)

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "ES from 2025-03-09 to 2026-03-09: 552 rows of 5-minute bars"
    assert re.fullmatch(r"first call \d+\.\d\d s, second call \d+\.\d\d s", printed[1])
    assert printed[2] == "the second read the same values: True"
    assert printed[-1] == "ES 5m: 3 folders, 3 partitions"
    assert check["held"].get_column("feature").to_list() == ["atr", "bars", "rsi"]
    # The first call builds March's bars, once alone and once from the two sessions before it
    # that RSI and ATR both read for their warm-up; the second builds none.
    assert len(built) == 2
