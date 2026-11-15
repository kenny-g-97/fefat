"""A saved run once a file is merged into a partition it read (step 5.14, ADR-0021, Done means
4): explaining a trade and working its fidelity check out again are refused with the partition
written since the run, the run's record and results stay as they were, byte for byte, and
running the strategy again gives a new run on a new snapshot. The store is the fixtures'
Databento batch as the importer writes it, ESH2026's 1-minute bars of 2026-03-05 to 03-09, and
the merge a generated file that carries March on by a bar of the next session and brings a bar
of February, a month the run did not read."""

import os
import re
from pathlib import Path

import pytest

import fefat as ff
from dbn_files import utc
from export_samples import SYNTHETIC
from fefat.backtest import Run
from fefat.config import resolve_paths
from fefat.market.importers.databento import import_databento
from fefat.market.store import Store
from notebook_runs import breakout
from test_market_importers_merge_properties import IMPORTED_ON, es_bars, march_file, tree

BATCH = SYNTHETIC / "databento-batch" / "GLBX-20260310-SYNTHETIC0"
WINDOW = ("2026-03-05", "2026-03-09")
MARCH = "databento/ohlcv-1m/root=ES/contract=ESH2026/month=2026-03/part.parquet"


def test_a_run_is_refused_with_the_partition_a_merge_wrote_and_stands_as_it_was(
    tmp_path: Path,
) -> None:
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    import_databento(BATCH, store, paths.cache_dir, imported_on=IMPORTED_ON)
    run = ff.backtest.run(breakout(), *WINDOW)
    saved = tree(run.folder)
    trade = run.trades.item(0, "entry_order")
    bars = es_bars(utc(2026, 2, 10, 14, 30), utc(2026, 3, 10, 14, 30))
    later = march_file(tmp_path, "later", bars)

    import_databento(later, store, paths.cache_dir, imported_on=IMPORTED_ON)

    # February's new partition is written since the run too, and is none of the run's.
    refusal = (
        r"the data changed since the run\. Written since the run was saved: "
        rf"{re.escape(MARCH)}\. The run's record and results stand"
    )
    with pytest.raises(ValueError, match=refusal):
        run.explain(trade)
    with pytest.raises(ValueError, match=refusal):
        ff.backtest.fidelity_check(run)
    assert tree(run.folder) == saved
    again = ff.backtest.run(breakout(), *WINDOW)
    assert again.hash != run.hash
    assert [each.snapshot for each in again.record.datasets] != [
        each.snapshot for each in run.record.datasets
    ]
    assert Run.open(run.folder).record == run.record
