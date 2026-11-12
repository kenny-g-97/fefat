"""A run whose data changed while it ran (step 5.3, from the Phase 2 exit's reviews, D-93): what a
run pins of the store is worked out before a bar is loaded and again once the engine, its reruns,
and its metrics are done, and a run whose data was added, replaced, or removed between the two is
refused before anything is saved, since its signals, its fills, and its key could come from two
versions of the data; a partition the run never reads changes nothing."""

import os
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import fefat_engine
import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.market.layout import Partition
from fefat.market.store import Store
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")


def rewritten(path: str) -> None:
    """The store's partition at `path`, relative to the store, written again with one minute's
    volume one more."""
    store = Store(resolve_paths(os.environ).data_dir)
    partition = Partition.from_relative_path(PurePosixPath(path))
    rows = store.scan_partition(partition).collect()
    first = pl.int_range(pl.len()) == 0
    store.write_partition(
        partition,
        rows.with_columns(volume=pl.when(first).then(pl.col("volume") + 1).otherwise("volume")),
    )


def engine_rewriting(path: str) -> Callable[..., Any]:
    """The engine's run, which first rewrites the partition at `path`, once, as an import
    running beside the backtest would."""
    run_signal_backtest = fefat_engine.run_signal_backtest
    done: list[str] = []

    def running(*arguments: Any, **named: Any) -> Any:
        if not done:
            rewritten(path)
            done.append(path)
        return run_signal_backtest(*arguments, **named)

    return running


def test_a_run_whose_data_changed_while_it_ran_is_refused_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_with("ohlcv-1m")
    path = "synthetic/ohlcv-1m/root=ES/contract=ESM2026/month=2026-03/part.parquet"
    monkeypatch.setattr(fefat_engine, "run_signal_backtest", engine_rewriting(path))

    with pytest.raises(ValueError, match="the store changed while the run read it: run it again"):
        ff.backtest.run(breakout(), *WINDOW)

    runs_dir = resolve_paths(os.environ).runs_dir
    assert ff.backtest.saved_runs_in(runs_dir) == ()
    assert not (runs_dir / "requests").exists()


def test_a_partition_the_run_never_reads_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    store_with("ohlcv-1m")
    path = "synthetic/ohlcv-1m/root=BTCUSDT-PERP/contract=BTCUSDT-PERP/month=2026-03/part.parquet"
    monkeypatch.setattr(fefat_engine, "run_signal_backtest", engine_rewriting(path))

    run = ff.backtest.run(breakout(), *WINDOW)

    assert (run.folder / "run.json").is_file()
