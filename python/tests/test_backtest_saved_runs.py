"""The saved runs listed from their folders (step 5.3, D-84): each folder named by its run key that
holds `run.json` is a saved run, which the app's index reads; the requests beside them and the
folders a writer is still writing are passed over, a run another version of the engine wrote is
left out, and a record copied under another key is refused. A `.partial` folder a killed writer
left more than a day ago goes when the next run is saved (from step 2.10's review)."""

import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import fefat as ff
from fefat.backtest import Run, saved_runs_in
from fefat.config import resolve_paths
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")
OTHER_KEY = "e" * 64


def runs_dir() -> Path:
    return resolve_paths(os.environ).runs_dir


def test_the_listing_gives_each_saved_run_and_passes_over_requests_and_writes_under_way() -> None:
    store_with("ohlcv-1m")
    first = ff.backtest.run(breakout(), *WINDOW)
    second = ff.backtest.run(breakout(stop_ticks=8), *WINDOW)
    under_way = runs_dir() / f"{OTHER_KEY}.x1y2.partial"
    shutil.copytree(first.folder, under_way)
    shutil.copytree(first.folder, runs_dir() / "small-rates")

    listed = saved_runs_in(runs_dir())

    assert (runs_dir() / "requests").is_dir()
    assert [run.hash for run in listed] == sorted([first.hash, second.hash])
    assert {run.hash: run.record for run in listed} == {
        first.hash: first.record,
        second.hash: second.record,
    }
    assert saved_runs_in(runs_dir() / "none yet") == ()


def test_the_listing_leaves_out_a_run_another_engine_wrote() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    older = runs_dir() / OTHER_KEY
    shutil.copytree(run.folder, older)
    record = json.loads((older / "run.json").read_bytes())
    record["versions"]["engine"] -= 1
    (older / "run.json").write_text(json.dumps(record), encoding="utf-8")

    assert [each.hash for each in saved_runs_in(runs_dir())] == [run.hash]


def test_a_record_copied_under_another_key_is_refused() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    shutil.copytree(run.folder, runs_dir() / OTHER_KEY)

    with pytest.raises(ValueError, match=f"Expected the run of key {OTHER_KEY}"):
        saved_runs_in(runs_dir())


def test_a_partial_folder_left_a_day_ago_goes_at_the_next_save() -> None:
    store_with("ohlcv-1m")
    first = ff.backtest.run(breakout(), *WINDOW)
    killed = runs_dir() / f"{OTHER_KEY}.killed.partial"
    writing = runs_dir() / f"{OTHER_KEY}.writing.partial"
    for folder in (killed, writing):
        shutil.copytree(first.folder, folder)
    two_days_ago = time.time() - timedelta(days=2).total_seconds()
    os.utime(killed, (two_days_ago, two_days_ago))

    ff.backtest.run(breakout(stop_ticks=8), *WINDOW)

    assert not killed.exists()
    assert writing.is_dir()


def test_a_saved_run_says_when_it_was_saved() -> None:
    store_with("ohlcv-1m")
    before = datetime.now(UTC) - timedelta(seconds=2)

    run = ff.backtest.run(breakout(), *WINDOW)

    assert before <= Run.open(run.folder).saved_at <= datetime.now(UTC)
