"""The feature cache of step 3.3 (`02-engine-and-data.md` §6, D-56, D-71): `ff.features.compute`
keeps each feature's values by partition of the store under `FEFAT_HOME/cache/features/` and reads
them back while their inputs are unchanged. A range computed in chunks equals the range computed
at once (Done means 1), a second computation of a year reads the cache in well under a second
(Done means 2), and a changed partition of the store computes what read it again (Done means 3).
The stores are dense 1-minute bars of ES's contracts that `generated_minutes` writes, each leading
by volume for a stretch so that the roll calendar rolls where they cross, or `gen_fixtures`'s."""

import os
import random
import re
import shutil
import time
import warnings
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

import fefat as ff
import gen_fixtures
from fefat.config import resolve_paths
from fefat.features import InstrumentInput, cache, cache_evaluation, cache_index
from fefat.features.cache_evaluation import evaluated_features
from fefat.features.cache_index import (
    PrunedCache,
    prune_feature_cache,
    read_cache_index,
    write_cache_index,
    write_merged_index,
)
from fefat.features.examples import atr, in_session_window, rsi
from fefat.features.runtime import FeatureGraph
from fefat.market import instruments
from fefat.market import series_source as bar_source
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.continuous import RollCalendar
from fefat.market.layout import Dataset, Partition, SeriesKind, YearMonth
from fefat.market.schema import Timeframe, parse_schema_name
from fefat.market.store import Store
from generated_minutes import (
    FIXTURES,
    MINUTE,
    MINUTES,
    SPRING,
    TICK,
    YEAR,
    Listing,
    listing,
    write_minutes,
)
from notebook_runs import store_with

FIVE = Timeframe.parse("5m")


@ff.feature(warmup=1, outputs={"change": "price_distance"})
def change(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") - pl.col("close").shift(1)


@ff.feature(outputs={"running": "price"})
def running_total(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").cum_sum()


@ff.feature(warmup=1, outputs={"slow_mean": "price"})
def slow_mean(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").ewm_mean(alpha=0.001)


@ff.feature(inputs=[InstrumentInput(root="BTCUSDT-PERP")], outputs={"btc_age": "other"})
def btc_age(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("staleness_BTCUSDT-PERP")


SLOTS = {"rsi": rsi(n=14), "atr": atr(n=14), "cash": in_session_window(), "change": change()}
"""Two averages that remember their first bars a little, a flag, and an integer difference."""


def cache_folder() -> Path:
    return resolve_paths(os.environ).cache_dir / "features"


def written() -> dict[str, int]:
    """Each file of the feature cache, `<folder>/<partition>`, with its modification time."""
    return {
        f"{path.parent.name.split('-')[0]}/{path.stem}": path.stat().st_mtime_ns
        for path in cache_folder().rglob("*.parquet")
    }


def rewritten(before: dict[str, int]) -> set[str]:
    return {name for name, modified in written().items() if before.get(name) != modified}


def refused(*_: object, **__: object) -> object:
    raise AssertionError("Expected the values from the cache, got a computation.")


def test_a_range_computed_in_chunks_is_the_range_computed_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Done means 1: cut anywhere and computed in any order, the chunks give the frame a
    # computation of the whole range gives, exactly, and a computation of the whole range after
    # them reads the cache alone.
    write_minutes(SPRING)
    first, last = date(2026, 1, 5), date(2026, 4, 30)
    whole = ff.features.compute(SLOTS, "ES", "5m", first, last).collect()
    days = whole.get_column("trade_date").unique().sort().to_list()

    @settings(
        max_examples=6,
        deadline=None,
        database=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(cuts=st.sets(st.sampled_from(days[1:]), min_size=1, max_size=3), order=st.randoms())
    def chunks_give_the_whole(cuts: set[date], order: random.Random) -> None:
        shutil.rmtree(cache_folder(), ignore_errors=True)
        starts = [first, *sorted(cuts)]
        ends = [cut - timedelta(days=1) for cut in sorted(cuts)] + [last]
        chunks = list(zip(starts, ends, strict=True))
        order.shuffle(chunks)
        computed = {
            chunk: ff.features.compute(SLOTS, "ES", "5m", *chunk).collect() for chunk in chunks
        }
        with monkeypatch.context() as patched:
            patched.setattr(bar_source, "gridded_bars", refused)
            again = ff.features.compute(SLOTS, "ES", "5m", first, last).collect()

        assert again.equals(whole)
        for (start, end), frame in computed.items():
            assert frame.equals(whole.filter(pl.col("trade_date").is_between(start, end)))

    chunks_give_the_whole()


def test_the_cached_range_is_the_range_evaluated_in_one_pass() -> None:
    # Done means 1: each partition's warm-up, read from the sessions before it, gives the values a
    # single evaluation of all the data gives: exactly where a feature forgets the bars before its
    # warm-up, and within 1e-9 where an average weighs them less than a billionth (your choice).
    write_minutes(SPRING)
    first = date(2026, 1, 5)
    computed = ff.features.compute(SLOTS, "ES", "5m", first, "2026-04-30").collect()
    bars = ff.market.load("ES", "5m", "2026-01-02", "2026-04-30").collect()
    graph = FeatureGraph.of(SLOTS, "ES", FIVE)
    values = graph.evaluate({graph.signal_grid: bars}).drop("ts_close")
    one_pass = pl.concat([bars, values], how="horizontal").filter(pl.col("trade_date") >= first)

    exact = [*SIGNAL_BAR_COLUMNS, "cash", "change"]
    assert computed.select(exact).equals(one_pass.select(exact))
    assert computed.get_column("rsi").null_count() == one_pass.get_column("rsi").null_count()
    averages = computed.select("rsi", "atr")
    assert_frame_equal(averages, one_pass.select("rsi", "atr"), rel_tol=1e-9, abs_tol=0)
    assert min(computed.select(pl.col("rsi", "atr").drop_nulls().len()).row(0)) > 20_000


def test_a_second_computation_reads_the_cache_and_one_after_a_change_computes_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Done means 1: a cache hit while the inputs are unchanged, and a miss where one input
    # partition's hash changes: February's, which February's partitions read, and March's
    # through their warm-up and the session before them, but not January's or April's.
    store = write_minutes(SPRING)
    window = ("2026-01-05", "2026-04-30")
    first = ff.features.compute(SLOTS, "ES", "5m", *window).collect()
    before = written()
    with monkeypatch.context() as patched:
        patched.setattr(bar_source, "gridded_bars", refused)
        again = ff.features.compute(SLOTS, "ES", "5m", *window).collect()
    february = Partition(dataset=MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=2))
    rows = store.scan_partition(february).collect().with_row_index("row")
    (moved,) = rows.filter((pl.col("ts_close") % (5 * MINUTE)) == 0).head(1).get_column("row")
    close = pl.when(pl.col("row") == moved).then(pl.col("close") + TICK).otherwise(pl.col("close"))
    store.write_partition(february, rows.with_columns(close=close).drop("row"))

    changed = ff.features.compute(SLOTS, "ES", "5m", *window).collect()

    assert again.equals(first)
    assert rewritten(before) == {
        f"{folder}/{month}"
        for folder in ("bars", "rsi", "atr", "in_session_window", "change")
        for month in ("2026-02", "2026-03")
    }
    differs = changed.filter(pl.col("close") != first.get_column("close"))
    assert differs.get_column("trade_date").dt.month().unique().to_list() == [2]


def test_a_new_month_of_data_computes_that_month_alone() -> None:
    # Done means 3 and the prompt: a new month computes the new month, and a changed partition
    # computes the partitions that read it again, its own and the next month's, whose warm-up
    # reads it.
    first_months = (
        SPRING[0],
        listing("ESM2026", 1003, ("2026-02-23", "2026-03-31"), ("2026-03-11", "2026-03-31")),
    )
    store = write_minutes(first_months)
    window = ("2026-01-05", "2026-04-30")
    before = ff.features.compute(SLOTS, "ES", "5m", *window).collect()
    cached = written()
    write_minutes(
        (listing("ESM2026", 1003, ("2026-04-01", "2026-04-30"), ("2026-04-01", "2026-04-30")),)
    )

    after = ff.features.compute(SLOTS, "ES", "5m", *window).collect()

    folders = ("bars", "rsi", "atr", "in_session_window", "change")
    assert rewritten(cached) == {f"{folder}/2026-04" for folder in folders}
    assert after.filter(pl.col("trade_date") < date(2026, 4, 1)).equals(before)
    assert after.filter(pl.col("trade_date") >= date(2026, 4, 1)).height > 0
    january = Partition(dataset=MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=1))
    rows = store.scan_partition(january).collect()
    store.write_partition(january, rows.with_columns(volume=pl.col("volume") + 1))
    cached = written()

    ff.features.compute(SLOTS, "ES", "5m", *window).collect()

    assert rewritten(cached) == {
        f"{folder}/{month}" for folder in folders for month in ("2026-01", "2026-02")
    }


def test_a_second_computation_of_a_years_feature_reads_the_cache_in_well_under_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Done means 2, with a generous bound: the second computation builds no bars and reads the
    # cache alone.
    write_minutes(YEAR)
    slots = {"rsi": rsi(n=14)}
    window = ("2025-04-01", "2026-03-31")

    began = time.perf_counter()
    first = ff.features.compute(slots, "ES", "5m", *window).collect()
    computing = time.perf_counter() - began
    monkeypatch.setattr(bar_source, "gridded_bars", refused)
    began = time.perf_counter()
    again = ff.features.compute(slots, "ES", "5m", *window).collect()
    reading = time.perf_counter() - began

    print(f"a year of 5-minute RSI: computed in {computing:.2f} s, read back in {reading:.2f} s")
    assert again.equals(first)
    assert first.get_column("trade_date").n_unique() > 240
    assert first.get_column("rsi").drop_nulls().len() > 60_000
    assert reading < 1.0


def test_a_feature_that_remembers_more_than_its_warmup_is_refused() -> None:
    # If it fails: chunked results that differ from whole-range ones mean the declared warm-up is
    # too small, and the runtime fails loudly rather than return wrong edges: a running total,
    # which never forgets, and a slow average declaring one bar are refused, and nothing is kept.
    write_minutes(SPRING)
    window = ("2026-01-05", "2026-03-31")

    with pytest.raises(ValueError, match="Expected feature running_total to give the same values"):
        ff.features.compute({"total": running_total()}, "ES", "5m", *window)
    with pytest.raises(ValueError, match="it remembers more than its warm-up of 1 bar of 5m"):
        ff.features.compute({"slow": slow_mean()}, "ES", "5m", *window)

    assert list(cache_folder().rglob("*.parquet")) == []


def test_a_trade_date_of_finer_data_is_a_partition_of_its_own() -> None:
    # The amendment: a partition of the cache is one of the store, a month of 1-minute bars or a
    # trade date of finer data; the month leaves the trade dates of ticks out, and the warm-up
    # check compares each with the month's values on it.
    synthetic = resolve_paths(os.environ).data_dir / "synthetic"
    dates = ["--dates", "2026-03-02..2026-03-13", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(synthetic), *dates, "--ticks-from", "2026-03-10"]) == 0
    for schema in ("trades", "ohlcv-1s"):
        for day in ("2026-03-12", "2026-03-13"):
            shutil.rmtree(synthetic / schema / "root=ES" / "contract=ESH2026" / f"date={day}")

    computed = ff.features.compute(
        {"rsi": rsi(n=7)}, "ES", "5m", "2026-03-02", "2026-03-13"
    ).collect()

    (folder,) = cache_folder().glob("synthetic/ES/5m/rsi-*")
    assert sorted(path.stem for path in folder.glob("*.parquet")) == [
        "2026-03",
        "2026-03-10",
        "2026-03-11",
    ]
    loaded = ff.market.load("ES", "5m", "2026-03-02", "2026-03-13").collect()
    assert computed.select(SIGNAL_BAR_COLUMNS.names()).equals(loaded)


def test_another_instruments_changed_bars_compute_the_features_reading_them_again() -> None:
    # The key names each instrument a feature reads: bitcoin's changed bars compute ES's feature
    # of them again, and leave ES's bars as they were.
    store_with("ohlcv-1m")
    store = Store(resolve_paths(os.environ).data_dir)
    ff.features.compute({"btc_age": btc_age()}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    cached = written()
    (bitcoin,) = (
        file.partition
        for file in store.list_partitions()
        if file.partition.dataset.root == "BTCUSDT-PERP"
        and file.partition.dataset.schema_name == MINUTES.schema_name
    )
    rows = store.scan_partition(bitcoin).collect()
    store.write_partition(bitcoin, rows.with_columns(volume=pl.col("volume") + 1))

    ff.features.compute({"btc_age": btc_age()}, "ES", "5m", "2026-03-06", "2026-03-09").collect()

    assert rewritten(cached) == {"btc_age/2026-03"}


def test_a_run_reads_the_values_a_computation_kept() -> None:
    # The kickoff (D-71): a feature previewed alone and the same feature in a backtest read the
    # same values, the run's from the cache the preview wrote.
    store_with("ohlcv-1m")
    slots = {"rsi": rsi(n=7)}
    computed = ff.features.compute(slots, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features=slots,
        long_entry=pl.col("rsi") < 40,
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)),
    )

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(FeatureGraph, "evaluate", refused)
        run = ff.backtest.run(strategy, "2026-03-09", "2026-03-09")

    monday = computed.filter(pl.col("trade_date") == date(2026, 3, 9))
    assert run.signals.select("ts_close", "rsi").equals(monday.select("ts_close", "rsi"))


def test_the_cache_status_lists_each_folder_and_pruning_removes_what_was_not_used() -> None:
    # The prompt: cache_status, and pruning by age, each partition's last use in its index.
    store_with("ohlcv-1m")
    slots = {"rsi": rsi(n=7), "cash": in_session_window()}
    ff.features.compute(slots, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    cache_dir = resolve_paths(os.environ).cache_dir
    now = datetime.now(UTC)

    status = ff.features.cache_status()
    kept = prune_feature_cache(cache_dir, timedelta(days=30), now)
    (bars,) = cache_folder().glob("synthetic/ES/5m/bars")
    index = read_cache_index(bars)
    assert index is not None
    old = index.partitions["2026-03"].model_copy(update={"last_used": now - timedelta(days=31)})
    write_cache_index(bars, index.with_partitions({"2026-03": old}))
    pruned = prune_feature_cache(cache_dir, timedelta(days=30), now)

    assert status.select(
        "provider", "instrument", "timeframe", "feature", "parameters", "partitions"
    ).rows() == [
        ("synthetic", "ES", "5m", "bars", "", 1),
        (
            "synthetic",
            "ES",
            "5m",
            "in_session_window",
            "start=08:30, end=15:00, time_zone=America/Chicago",
            1,
        ),
        ("synthetic", "ES", "5m", "rsi", "n=7", 1),
    ]
    assert status.get_column("first").to_list() == [date(2026, 3, 1)] * 3
    size = int(status.get_column("size_bytes").sum())
    assert kept == PrunedCache(removed=0, removed_bytes=0, kept=3, kept_bytes=size, held=())
    assert pruned.removed == 1 and pruned.kept == 2
    assert not bars.exists()
    assert prune_feature_cache(cache_dir, timedelta(0), now).kept == 0
    assert ff.features.cache_status().is_empty()
    assert list(cache_folder().iterdir()) == []


def test_pruning_keeps_the_partitions_another_program_holds_and_names_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The code review: Windows refuses to remove a file another program holds open, and pruning
    # goes on past it, keeping its partition, so that each index names the files that remain.
    store_with("ohlcv-1m")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    (rsi_file,) = cache_folder().glob("synthetic/ES/5m/rsi-*/2026-03.parquet")
    unlink = Path.unlink

    def held_open(path: Path, missing_ok: bool = False) -> None:
        if path == rsi_file:
            raise PermissionError("[WinError 32] The process cannot access the file")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held_open)

    pruned = prune_feature_cache(
        resolve_paths(os.environ).cache_dir, timedelta(0), datetime.now(UTC)
    )

    assert (pruned.removed, pruned.kept, pruned.held) == (1, 1, (rsi_file,))
    assert ff.features.cache_status().get_column("feature").to_list() == ["rsi"]
    assert sorted(path.name for path in rsi_file.parent.iterdir()) == [
        "2026-03.parquet",
        "index.json",
    ]


def test_a_damaged_file_or_index_of_the_cache_is_computed_again() -> None:
    # The code review: a file another program damaged reads as missing, and an index this code
    # cannot read as none, so that a computation writes them again; status and pruning pass over
    # such an index, and pruning removes its folder.
    store_with("ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")
    first = ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    (damaged,) = cache_folder().glob("synthetic/ES/5m/rsi-*/2026-03.parquet")
    damaged.write_bytes(b"not a parquet file")
    (unreadable,) = cache_folder().glob("synthetic/ES/5m/bars/index.json")

    again = ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    unreadable.write_text("{}", encoding="utf-8")
    listed = ff.features.cache_status()
    pruned = prune_feature_cache(
        resolve_paths(os.environ).cache_dir, timedelta(days=30), datetime.now(UTC)
    )

    assert again.equals(first)
    assert damaged.read_bytes() != b"not a parquet file"
    assert listed.get_column("feature").to_list() == ["rsi"]
    assert (pruned.removed, pruned.kept) == (0, 1)
    assert not unreadable.parent.exists()


def test_a_computation_read_back_within_the_hour_writes_no_index() -> None:
    # The code review: an index rewritten on every read is a write another process's read can
    # refuse on Windows; a partition's last use is kept to the hour, which pruning by days needs.
    store_with("ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    (bars,) = cache_folder().glob("synthetic/ES/5m/bars")
    index = read_cache_index(bars)
    assert index is not None
    written_at = (bars / "index.json").stat().st_mtime_ns

    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    unchanged = (bars / "index.json").stat().st_mtime_ns
    hours_ago = datetime.now(UTC) - timedelta(hours=2)
    old = index.partitions["2026-03"].model_copy(update={"last_used": hours_ago})
    write_cache_index(bars, index.with_partitions({"2026-03": old}))
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    renewed = read_cache_index(bars)

    assert unchanged == written_at
    assert renewed is not None
    assert renewed.partitions["2026-03"].last_used > hours_ago + timedelta(hours=1)


def test_a_computation_whose_write_another_program_refuses_gives_its_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ponytail review: Windows refuses to replace a file another process is reading; the
    # computation still gives its values, warns that it kept none, and leaves its partitions to
    # the next one, which writes them.
    store_with("ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")
    replace = Path.replace

    def held_open(path: Path, target: str | Path) -> Path:
        if cache_folder() in Path(target).parents:
            raise PermissionError("[WinError 5] Access is denied")
        return replace(path, target)

    with monkeypatch.context() as patched, pytest.warns(UserWarning, match="Expected to keep"):
        patched.setattr(Path, "replace", held_open)
        unwritten = ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    left = [path for path in cache_folder().rglob("*") if path.is_file()]
    computed = ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()

    assert unwritten.equals(computed)
    assert left == []
    assert set(written()) == {"bars/2026-03", "rsi/2026-03"}


def test_pruning_keeps_an_index_another_program_holds_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ponytail review: an index Windows refuses to replace stays as it was, named among the
    # files held, and pruning goes on past it; an index whose partitions all stay is not written.
    store_with("ohlcv-1m")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    (folder,) = cache_folder().glob("synthetic/ES/5m/rsi-*")
    index = read_cache_index(folder)
    assert index is not None
    march = index.partitions["2026-03"]
    february = march.model_copy(update={"last_used": march.last_used - timedelta(days=60)})
    write_cache_index(folder, index.with_partitions({"2026-02": february, "2026-03": march}))
    shutil.copy(folder / "2026-03.parquet", folder / "2026-02.parquet")

    def held_open(*_: object) -> None:
        raise PermissionError("[WinError 5] Access is denied")

    with monkeypatch.context() as patched:
        patched.setattr("fefat.features.cache_index.write_cache_index", held_open)
        pruned = prune_feature_cache(
            resolve_paths(os.environ).cache_dir, timedelta(days=30), datetime.now(UTC)
        )

    assert (pruned.removed, pruned.kept, pruned.held) == (1, 2, (folder / "index.json",))
    assert not (folder / "2026-02.parquet").exists()


def test_another_instrument_without_bars_where_a_feature_reads_it_is_refused() -> None:
    # The step review: each partition reads another instrument for its own dates, where a
    # window read it whole and refused it without bars (step 3.2); the fixtures' bitcoin trades
    # on 2026-03-07 alone.
    store_with("ohlcv-1m")

    with pytest.raises(ValueError, match="Expected bars of BTCUSDT-PERP from 2026-03-08 to"):
        ff.features.compute({"btc_age": btc_age()}, "ES", "5m", "2026-03-09", "2026-03-09")


def test_the_warnings_of_another_instruments_data_come_with_the_values_read_from_it() -> None:
    # The step review: what load warns of another instrument's data, here a continuous series,
    # comes with every computation and lands in a run's record, whether the cache computed the
    # values or read them back.
    store_with("ohlcv-1m")
    store = Store(resolve_paths(os.environ).data_dir)
    bitcoin = Dataset(provider="synthetic", schema_name=MINUTES.schema_name, root="BTCUSDT-PERP")
    continuous = store.dataset_metadata(bitcoin).model_copy(
        update={"series": SeriesKind.CONTINUOUS}
    )
    store.write_dataset_metadata(bitcoin, continuous)
    slots = {"btc_age": btc_age()}
    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features=slots,
        long_entry=pl.lit(False),
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)),
    )
    warned = "root=BTCUSDT-PERP is a continuous series"

    for _ in range(2):
        with pytest.warns(UserWarning, match=warned):
            ff.features.compute(slots, "ES", "5m", "2026-03-06", "2026-03-09")
    run = ff.backtest.run(strategy, "2026-03-06", "2026-03-09")

    assert [warning for warning in run.record.warnings if warned in warning]


def test_a_changed_session_table_or_roll_calendar_computes_each_partition_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The amendment: the key names the session table and, on a spliced series, the roll calendar
    # through the last date read, beside the store's partitions.
    store_with("ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    cached = written()

    with monkeypatch.context() as patched:
        patched.setattr(SessionTable, "key", "another calendar")
        ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    by_sessions = rewritten(cached)
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    cached = written()
    with monkeypatch.context() as patched:
        patched.setattr(RollCalendar, "key_through", lambda *_: "another roll calendar")
        ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", *window).collect()
    by_rolls = rewritten(cached)

    assert by_sessions == by_rolls == {"bars/2026-03", "rsi/2026-03"}


@ff.feature(outputs={"peek": "price"})
def month_end_peek(bars: pl.LazyFrame) -> pl.Expr:
    month = pl.col("trade_date").dt.month()
    return pl.when(month != month.shift(-1)).then(pl.col("close").shift(-1))


def test_a_partition_holds_what_its_own_dates_give_even_to_a_feature_that_reads_ahead() -> None:
    # The leakage audit: a month evaluated past its end for the warm-up check kept the next
    # month's first close in its last row for a feature that reads ahead, which a month computed
    # alone, or a store cut at that close, does not hold. The month keeps what its own dates give.
    write_minutes(SPRING)
    window = ("2026-01-05", "2026-04-30")
    together = ff.features.compute({"peek": month_end_peek()}, "ES", "5m", *window).collect()
    shutil.rmtree(cache_folder())
    march = ff.features.compute({"peek": month_end_peek()}, "ES", "5m", "2026-03-02", "2026-03-31")

    last_of_march = together.filter(pl.col("trade_date") == date(2026, 3, 31)).tail(1)
    assert last_of_march.get_column("peek").to_list() == [None]
    assert together.filter(pl.col("trade_date").dt.month() == 3).equals(march.collect())


def test_a_file_another_computation_wrote_under_another_key_is_computed_again() -> None:
    # The leakage audit: two processes writing one partition at once can leave the index naming
    # one key and the file holding another's values; the file carries its key, which a read
    # compares.
    store = write_minutes(SPRING[:1])
    window = ("2026-01-05", "2026-02-27")
    ff.features.compute({"rsi": rsi(n=14)}, "ES", "5m", *window).collect()
    (february,) = cache_folder().glob("synthetic/ES/5m/rsi-*/2026-02.parquet")
    old_values = february.read_bytes()
    partition = Partition(dataset=MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=2))
    rows = store.scan_partition(partition).collect()
    store.write_partition(partition, rows.with_columns(close=pl.col("close") + TICK))
    fresh = ff.features.compute({"rsi": rsi(n=14)}, "ES", "5m", *window).collect()
    february.write_bytes(old_values)

    served = ff.features.compute({"rsi": rsi(n=14)}, "ES", "5m", *window).collect()

    assert served.equals(fresh)
    assert february.read_bytes() != old_values


def test_a_store_cut_at_a_close_gives_what_the_whole_store_gives_before_it(
    tmp_path: Path,
) -> None:
    # The leakage audit's truncation check: the store cut at the close of a month's last session,
    # and of the session the front rolls at, gives every value the whole store gives before the
    # cut, its months read back from the cache the whole store filled.
    write_minutes(SPRING)
    whole = ff.features.compute(SLOTS, "ES", "5m", "2026-01-05", "2026-04-30").collect()

    for cut in (date(2026, 2, 27), date(2026, 3, 12)):
        held = tuple(
            Listing(
                each.contract,
                each.instrument_id,
                (each.trades[0], min(each.trades[1], cut)),
                each.leads,
            )
            for each in SPRING
            if each.trades[0] <= cut
        )
        with pytest.MonkeyPatch.context() as patched:
            patched.setenv("FEFAT_DATA_DIR", str(tmp_path / f"cut-{cut}"))
            write_minutes(held)
            computed = ff.features.compute(SLOTS, "ES", "5m", "2026-01-05", cut).collect()

        assert computed.equals(whole.filter(pl.col("trade_date") <= cut)), cut


def test_trades_after_a_stretch_without_data_compute_the_month_before_them_again() -> None:
    # The ponytail review: a load's grid runs to the end of every dataset that builds its bars,
    # so trades imported for April give the stretch after bitcoin's last 1-minute bars in March
    # its rows; March's key names where each dataset's data ends, even one without data in
    # March, while an end that stays before March's first session leaves the key as it was.
    store_with("ohlcv-1m")
    store = Store(resolve_paths(os.environ).data_dir)
    trades = Dataset(
        provider="synthetic", schema_name=parse_schema_name("trades"), root="BTCUSDT-PERP"
    )
    store.write_dataset_metadata(trades, FIXTURES.dataset_metadata(trades))
    saturday = date(2026, 3, 7)
    rows = FIXTURES.scan_partition(
        Partition(dataset=trades, contract="BTCUSDT-PERP", key=saturday)
    ).collect()

    def trades_on(day: date) -> None:
        moved = (day - saturday).days * 86_400_000_000_000
        shifted = rows.with_columns(pl.col("ts_recv") + moved, pl.col("ts_event") + moved)
        store.write_partition(Partition(dataset=trades, contract="BTCUSDT-PERP", key=day), shifted)

    trades_on(date(2026, 2, 10))
    slots, window = {"change": change()}, ("2026-03-07", "2026-03-20")
    before = ff.features.compute(slots, "BTCUSDT-PERP", "5m", *window).collect()
    cached = written()
    trades_on(date(2026, 2, 11))
    ff.features.compute(slots, "BTCUSDT-PERP", "5m", *window).collect()
    earlier = rewritten(cached)
    trades_on(date(2026, 4, 10))
    after = ff.features.compute(slots, "BTCUSDT-PERP", "5m", *window).collect()
    shutil.rmtree(cache_folder())
    fresh = ff.features.compute(slots, "BTCUSDT-PERP", "5m", *window).collect()

    assert before.get_column("trade_date").max() == saturday
    assert earlier == set()
    assert after.equals(fresh)
    assert after.get_column("trade_date").max() == date(2026, 3, 20)


def test_a_bucket_held_back_at_the_end_of_the_data_comes_back_with_the_data_after_it() -> None:
    # The ponytail review: a month whose data ends inside its last bucket holds the bucket back
    # (D-43), and data that comes later, in another file, completes it: the month's key names
    # where the data ends, so the month computes again and gains its last bar.
    first_months = (
        SPRING[0],
        listing("ESM2026", 1003, ("2026-02-23", "2026-03-31"), ("2026-03-11", "2026-03-31")),
    )
    store = write_minutes(first_months)
    march = Partition(dataset=MINUTES, contract="ESM2026", key=YearMonth(year=2026, month=3))
    rows = store.scan_partition(march).collect()
    store.write_partition(march, rows.filter(pl.col("ts_open") < pl.col("ts_open").max() - MINUTE))
    window = ("2026-03-02", "2026-03-31")
    before = ff.features.compute(SLOTS, "ES", "5m", *window).collect()
    cached = written()
    write_minutes(
        (listing("ESM2026", 1003, ("2026-04-01", "2026-04-30"), ("2026-04-01", "2026-04-30")),)
    )

    after = ff.features.compute(SLOTS, "ES", "5m", *window).collect()

    assert "bars/2026-03" in rewritten(cached)
    assert after.height == before.height + 1
    assert after.filter(pl.col("ts_close") > before.get_column("ts_close").max()).height == 1


def test_a_daily_warmup_of_hundreds_of_sessions_is_counted_back_in_milliseconds() -> None:
    # The ponytail review: each partition counts its features' warm-up back a session at a time
    # on every computation, read back too, and a session found by filtering the whole session
    # table made a daily RSI's 350 sessions a tenth of a second a partition.
    paths = resolve_paths(os.environ)
    sessions = sessions_of(instruments.get("ES").session_calendar(), paths.cache_dir)
    graph = FeatureGraph.of({"rsi": rsi(n=14)}, "ES", Timeframe.parse("1d"))
    sessions.preceding(date(2026, 3, 9))

    began = time.perf_counter()
    start = graph.lead_in(sessions, date(2026, 3, 9))
    took = time.perf_counter() - began

    assert sessions.between(start, date(2026, 3, 6)).height == 350
    assert took < 0.05


def test_the_warmup_check_compares_each_partition_with_the_next_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ponytail review: the check compared each partition evaluated with every other, a
    # filter each, which grows with the square of the months a first computation fills; each
    # is compared with the partitions holding the dates it read past its own alone.
    write_minutes(SPRING)
    compared: list[str] = []
    require_agreement = cache_evaluation._require_agreement

    def counted(*arguments: Any) -> None:
        compared.append(arguments[2].name)
        require_agreement(*arguments)

    monkeypatch.setattr(cache_evaluation, "_require_agreement", counted)
    ff.features.compute(SLOTS, "ES", "5m", "2026-01-05", "2026-04-30").collect()

    assert sorted(compared) == [month for month in ("2026-02", "2026-03", "2026-04") for _ in SLOTS]


@ff.feature(inputs=[change, rsi], outputs={"rsi_change": "ratio"})
def rsi_change(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("rsi") * pl.col("change")


def test_a_features_folder_is_the_same_whatever_order_the_slots_come_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ponytail review: a feature reading two that do not read each other named them in the
    # order its graph evaluated them, which followed the slots', so a backtest listing its
    # features in another order than a notebook computed them again in a folder of their own.
    store_with("ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")
    first = {"both": rsi_change(), "change": change(), "rsi": rsi(n=7)}
    ff.features.compute(first, "ES", "5m", *window).collect()
    monkeypatch.setattr(bar_source, "gridded_bars", refused)

    again = {"change": change(), "rsi": rsi(n=7), "both": rsi_change()}
    ff.features.compute(again, "ES", "5m", *window).collect()

    assert len(list(cache_folder().glob("synthetic/ES/5m/rsi_change-*"))) == 1


@ff.feature(warmup=1, inputs=[InstrumentInput(root="BTCUSDT-PERP")], outputs={"btc_wait": "other"})
def btc_wait(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("staleness_BTCUSDT-PERP")


def test_a_preview_checks_another_instruments_bars_from_its_warmup_as_a_run_does() -> None:
    # The ponytail review: a run checks another instrument's bars from its warm-up's start, as
    # step 3.2's preview did, and a preview from the window's start refused what the run read;
    # the fixtures' bitcoin trades on Saturday 2026-03-07 alone, after ES's Friday session,
    # which a warm-up of one bar reaches from Monday.
    store_with("ohlcv-1m")

    frame = ff.features.compute({"wait": btc_wait()}, "ES", "5m", "2026-03-09", "2026-03-09")

    assert frame.collect().get_column("wait").drop_nulls().len() > 0


@ff.feature(outputs={"noisy": "price"})
def noisy_close(bars: pl.LazyFrame) -> pl.Expr:
    warnings.warn("a warning of the feature's own code", UserWarning, stacklevel=2)
    return pl.col("close")


def test_a_features_own_warnings_reach_the_notebook() -> None:
    # The ponytail review: the cache hid every warning while it evaluated features, a feature's
    # own and Polars' among them, to keep `load`'s from coming once a partition.
    store_with("ohlcv-1m")

    with pytest.warns(UserWarning, match="a warning of the feature's own code"):
        ff.features.compute({"noisy": noisy_close()}, "ES", "5m", "2026-03-06", "2026-03-09")


def test_the_refusal_of_a_feature_remembering_more_quotes_no_value() -> None:
    # The security review of the Phase 3 exit: a feature's values can be prices of licensed data,
    # which no error carries (D-21), so the refusal says how far apart the two values lie instead.
    write_minutes(SPRING)

    with pytest.raises(ValueError, match="it remembers more than its warm-up") as refused:
        ff.features.compute({"slow": slow_mean()}, "ES", "5m", "2026-01-05", "2026-03-31")

    message = str(refused.value)
    assert re.search(r"two values apart by \d\.\de-\d+ of the larger", message), message
    assert not re.search(r"\d{7,}", message), message


def test_two_computations_of_one_folder_keep_each_others_partitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 5.3 (from step 3.3): backtest jobs compute features in several processes at once; a
    # computation of 2026-03-06 that writes its index while one of 2026-03-09 evaluates, which
    # read the folders' indexes before it, must not lose its partition to the second's write.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    meanwhile: list[str] = []

    def another_process_writing_first(*arguments: Any, **named: Any) -> Any:
        if not meanwhile:
            meanwhile.append("2026-03-06")
            ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-06").collect()
        return evaluated_features(*arguments, **named)

    monkeypatch.setattr(cache, "evaluated_features", another_process_writing_first)
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-09", "2026-03-09").collect()

    folders = sorted(cache_folder().glob("synthetic/ES/5m/*"))
    indexes = [read_cache_index(folder) for folder in folders]
    assert meanwhile == ["2026-03-06"]
    assert len(folders) == 2
    assert all(
        sorted(index.partitions) == ["2026-03-06", "2026-03-09"] for index in indexes if index
    )


def test_a_renewed_last_use_leaves_a_partition_another_process_computed_again() -> None:
    # Step 5.3: a computation that only read a partition renews its last use; where another
    # process computed it again under another key meanwhile, its entry stays the other's.
    store_with("ohlcv-1m")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    (folder,) = cache_folder().glob("synthetic/ES/5m/bars")
    read_before = read_cache_index(folder)
    assert read_before is not None
    computed_again = read_before.partitions["2026-03"].model_copy(update={"key": "a" * 64})
    write_cache_index(folder, read_before.with_partitions({"2026-03": computed_again}))
    later = datetime.now(UTC) + timedelta(hours=2)
    renewed = read_before.partitions["2026-03"].model_copy(update={"last_used": later})

    write_merged_index(folder, read_before, written={}, renewed={"2026-03": renewed})

    after = read_cache_index(folder)
    assert after is not None
    assert after.partitions == {"2026-03": computed_again}


def test_pruning_removes_what_a_write_left_a_day_ago_and_passes_over_one_under_way() -> None:
    # Step 5.3 (the code review of the Phase 3 exit): a folder whose first write never wrote its
    # index, and the `.tmp` files a refused write leaves, were never pruned; a write under way
    # may hold them for a moment, so only what is a day old goes.
    store_with("ohlcv-1m")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    (feature,) = cache_folder().glob("synthetic/ES/5m/rsi-*")
    two_days_ago = time.time() - timedelta(days=2).total_seconds()
    left, under_way = feature.with_name("rsi-left"), feature.with_name("rsi-under-way")
    for folder in (left, under_way):
        folder.mkdir()
        (folder / "2026-03.parquet").write_bytes(b"a partition written without its index")
    left_tmp, writing_tmp = feature / "2026-03.k1.tmp", feature / "2026-03.k2.tmp"
    for path in (left_tmp, writing_tmp):
        path.write_bytes(b"half a partition")
    for path in (left / "2026-03.parquet", left_tmp):
        os.utime(path, (two_days_ago, two_days_ago))

    pruned = prune_feature_cache(
        resolve_paths(os.environ).cache_dir, timedelta(days=30), datetime.now(UTC)
    )

    assert not left.exists()
    assert (under_way / "2026-03.parquet").is_file()
    assert not left_tmp.exists()
    assert writing_tmp.is_file()
    assert (pruned.removed, pruned.kept) == (1, 2)


def test_pruning_passes_over_a_file_gone_while_it_reads_its_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 5.3 (its code review): a file a writer renames, or another prune removes, between
    # pruning's look at its time and its size must not stop the prune.
    store_with("ohlcv-1m")
    ff.features.compute({"rsi": rsi(n=7)}, "ES", "5m", "2026-03-06", "2026-03-09").collect()
    (feature,) = cache_folder().glob("synthetic/ES/5m/rsi-*")
    left = feature.with_name("rsi-left")
    left.mkdir()
    (left / "2026-03.parquet").write_bytes(b"a partition written without its index")
    written_before = cache_index._written_before

    def gone_once_read(path: Path, instant: datetime) -> bool:
        before = written_before(path, instant + timedelta(days=2))
        path.unlink(missing_ok=True)
        return before

    monkeypatch.setattr(cache_index, "_written_before", gone_once_read)

    pruned = prune_feature_cache(
        resolve_paths(os.environ).cache_dir, timedelta(days=30), datetime.now(UTC)
    )

    assert not left.exists()
    assert pruned.removed == 0
