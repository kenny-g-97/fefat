"""A saved run once its data is deleted (step 5.18, ADR-0023, Done means 5): the runs that read a
provider's data of a root are counted before a delete; afterwards the run keeps its record and
results, byte for byte, while explaining a trade and working its fidelity check out again are
refused in words that say its data was deleted. The store is the fixtures' Databento batch as the
importer writes it, ESH2026's 1-minute bars of 2026-03-05 to 03-09."""

import os
import re

import pytest

import fefat as ff
from export_samples import SYNTHETIC
from fefat.backtest.saved_runs import runs_that_read
from fefat.config import resolve_paths
from fefat.market.importers.databento import import_databento
from fefat.market.store import Store
from fefat.market.stored_deletion import delete_stored_data
from notebook_runs import breakout
from test_market_importers_merge_properties import IMPORTED_ON, tree

BATCH = SYNTHETIC / "databento-batch" / "GLBX-20260310-SYNTHETIC0"
WINDOW = ("2026-03-05", "2026-03-09")


def test_a_run_whose_data_was_deleted_is_counted_stands_and_refuses_to_be_read_again() -> None:
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    import_databento(BATCH, store, paths.cache_dir, imported_on=IMPORTED_ON)
    run = ff.backtest.run(breakout(), *WINDOW)
    saved = tree(run.folder)
    trade = run.trades.item(0, "entry_order")

    counted = runs_that_read(paths.runs_dir, "databento", "ES")
    elsewhere = (
        runs_that_read(paths.runs_dir, "databento", "MES"),
        runs_that_read(paths.runs_dir, "synthetic", "ES"),
    )
    delete_stored_data(store, paths.reports_dir, paths.cache_dir, "databento", "ES")

    assert [each.hash for each in counted] == [run.hash]
    assert elsewhere == ((), ())
    refusal = re.escape(
        "got none: its data was deleted since the run. The run's record and results stand"
    )
    with pytest.raises(ValueError, match=refusal):
        run.explain(trade)
    with pytest.raises(ValueError, match=refusal):
        ff.backtest.fidelity_check(run)
    assert tree(run.folder) == saved
    assert [each.hash for each in runs_that_read(paths.runs_dir, "databento", "ES")] == [run.hash]
