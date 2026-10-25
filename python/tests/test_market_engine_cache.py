"""The engine cache of the synthetic fixtures (`fefat.market.engine_cache`, step 2.5): each
level holds the store's records, each descent counts the finer records before each bar (Done
means 1), a month is rebuilt when its partitions change, and the status lists each cached
contract-month with its levels (Done means 3)."""

import json
import re
import shutil
from datetime import date
from pathlib import Path, PurePosixPath

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.engine_cache import (
    ENGINE_CACHE_FOLDER_NAME,
    MonthOutcome,
    build_engine_cache,
    engine_cache_status,
    read_cache_month_index,
)
from fefat.market.layout import Dataset, Partition
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store
from fefat.market.store_files import DIGEST_SUFFIX

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
FIXTURE_STORE = Store(FIXTURES)
MANIFEST_SHA256 = {
    f"synthetic/{entry['path']}": entry["sha256"]
    for entry in json.loads((FIXTURES / "synthetic" / "MANIFEST.json").read_text("utf-8"))["files"]
}
CONTRACTS = ("ESH2026", "ESM2026")
TRADE_DATES = (date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9))
SCHEMAS = {"trades": "trades", "1s": "ohlcv-1s", "1m": "ohlcv-1m"}
BAR_COLUMNS = ("ts_open", "ts_close", "open", "high", "low", "close", "volume")
CACHE_COLUMNS = {"trades": ("ts_recv", "price", "size"), "1s": BAR_COLUMNS, "1m": BAR_COLUMNS}
DESCENTS = [("1m", "1s"), ("1m", "trades"), ("1s", "trades")]


def store_copy(folder: Path) -> Store:
    shutil.copytree(FIXTURES / "synthetic", folder / "data" / "synthetic")
    return Store(folder / "data")


def month_folder(cache: Path, contract: str, provider: str = "synthetic") -> Path:
    return cache / ENGINE_CACHE_FOLDER_NAME / provider / "ES" / contract / "2026-03"


def stored_on(level: str, contract: str, trade_date: date) -> pl.DataFrame:
    """The fixtures' records of a level, contract, and trade date, in the cache's columns."""
    dataset = Dataset(
        provider="synthetic", schema_name=parse_schema_name(SCHEMAS[level]), root="ES"
    )
    files = [
        file
        for file in FIXTURE_STORE.list_partitions(dataset)
        if file.partition.contract == contract
    ]
    records = pl.concat([FIXTURE_STORE.scan_partition(file.partition).collect() for file in files])
    if level != "trades":
        records = records.filter(pl.col("trade_date") == trade_date)
    else:
        dated = [file.partition for file in files if file.partition.key == trade_date]
        records = FIXTURE_STORE.scan_partition(dated[0]).collect()
    return records.select(pl.col(column).cast(pl.Int64) for column in CACHE_COLUMNS[level])


def cached_file(cache: Path, contract: str, name: str) -> pl.DataFrame:
    return pl.read_ipc((month_folder(cache, contract) / name).read_bytes())


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("engine-cache")
    build_engine_cache(store_copy(folder), folder / "cache", "ES", 2026)
    return folder / "cache"


@pytest.mark.parametrize("contract", CONTRACTS)
@pytest.mark.parametrize("level", ["trades", "1s", "1m"])
def test_each_level_of_the_cache_holds_the_records_of_the_store(
    cache: Path, contract: str, level: str
) -> None:
    expected = pl.concat([stored_on(level, contract, trade_date) for trade_date in TRADE_DATES])

    read = cached_file(cache, contract, f"{level}.arrow")

    assert read.height > 0
    assert_frame_equal(read, expected)


@pytest.mark.parametrize("contract", CONTRACTS)
@pytest.mark.parametrize(("coarser", "finer"), DESCENTS)
def test_each_descent_counts_the_finer_records_before_each_bar_of_each_trade_date(
    cache: Path, contract: str, coarser: str, finer: str
) -> None:
    expected: list[int] = []
    for trade_date in TRADE_DATES:
        bars = stored_on(coarser, contract, trade_date).get_column("ts_open")
        records = stored_on(finer, contract, trade_date)
        starts = records.get_column("ts_recv" if finer == "trades" else "ts_open")
        expected += [*starts.search_sorted(bars, side="left").to_list(), records.height]

    read = cached_file(cache, contract, f"{coarser}-to-{finer}.arrow")

    assert read.get_column("offset").to_list() == expected


def test_the_index_lists_each_trade_date_with_its_levels_and_the_partitions_it_was_built_from(
    cache: Path,
) -> None:
    index = read_cache_month_index(month_folder(cache, "ESH2026"))

    assert index is not None
    assert [day.trade_date for day in index.trade_dates] == list(TRADE_DATES)
    assert all(day.levels == ("trades", "1s", "1m") for day in index.trade_dates)
    assert all(not day.cut and not day.left_out for day in index.trade_dates)
    sources = {source.path: source.sha256 for source in index.sources}
    assert sources == {
        path: sha256
        for path, sha256 in MANIFEST_SHA256.items()
        if "/root=ES/contract=ESH2026/" in path and path.endswith(".parquet")
    }
    assert len(sources) == 7


def test_the_build_records_the_digest_of_each_partition_it_read(tmp_path: Path) -> None:
    store = store_copy(tmp_path)

    build_engine_cache(store, tmp_path / "cache", "ES", 2026)

    read = sorted((tmp_path / "data" / "synthetic").glob("*/root=ES/*/**/part.parquet"))
    assert len(read) == 14
    assert all(path.with_suffix(DIGEST_SUFFIX).is_file() for path in read)


def test_a_second_build_finds_each_month_up_to_date_and_reads_no_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_copy(tmp_path)
    build_engine_cache(store, tmp_path / "cache", "ES", 2026)
    files = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}

    def no_read(*arguments: object) -> pl.DataFrame:
        raise AssertionError("a build of months up to date read a partition")

    monkeypatch.setattr(Store, "read_pinned_partition", no_read)
    again = build_engine_cache(store, tmp_path / "cache", "ES", 2026)

    assert [month.outcome for month in again.months] == [MonthOutcome.UP_TO_DATE] * 2
    assert {
        path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()
    } == files


def test_a_rewritten_partition_rebuilds_its_contract_month_alone(tmp_path: Path) -> None:
    store = store_copy(tmp_path)
    build_engine_cache(store, tmp_path / "cache", "ES", 2026)
    partition = Partition.from_relative_path(
        PurePosixPath("synthetic/trades/root=ES/contract=ESM2026/date=2026-03-06/part.parquet")
    )
    trades = store.scan_partition(partition).collect()
    tick_higher = pl.when(pl.int_range(pl.len()) == 100).then(pl.col("price") + 250_000_000)
    store.write_partition(partition, trades.with_columns(tick_higher.otherwise(pl.col("price"))))

    again = build_engine_cache(store, tmp_path / "cache", "ES", 2026)

    outcomes = {month.index.contract: month.outcome for month in again.months}
    assert outcomes == {"ESH2026": MonthOutcome.UP_TO_DATE, "ESM2026": MonthOutcome.BUILT}
    rebuilt = cached_file(tmp_path / "cache", "ESM2026", "trades.arrow")
    prices = rebuilt.get_column("price")
    expected = pl.concat([stored_on("trades", "ESM2026", day) for day in TRADE_DATES]).get_column(
        "price"
    )
    assert (prices - expected).to_list().count(250_000_000) == 1


def test_trades_after_the_last_minute_bar_of_the_data_are_cut_and_reported(tmp_path: Path) -> None:
    # D-43 and D-45 hold back the bar of the bucket a dataset ends in but keep its ticks, which
    # no coarser bar leads to; the cache cuts them.
    store = store_copy(tmp_path)
    partition = Partition.from_relative_path(
        PurePosixPath("synthetic/trades/root=ES/contract=ESH2026/date=2026-03-09/part.parquet")
    )
    trades = store.scan_partition(partition).collect()
    last_close = stored_on("1m", "ESH2026", date(2026, 3, 9)).get_column("ts_close").max()
    at_the_close = pl.lit(last_close, dtype=pl.Int64)
    late = trades.tail(1).with_columns(ts_recv=at_the_close, ts_event=at_the_close)
    store.write_partition(partition, pl.concat([trades, late]))

    build = build_engine_cache(store, tmp_path / "cache", "ES", 2026)

    index = read_cache_month_index(month_folder(tmp_path / "cache", "ESH2026"))
    assert index is not None
    assert index.trade_dates[-1].cut == {"trades": 1}
    assert (
        cached_file(tmp_path / "cache", "ESH2026", "trades.arrow").height
        == pl.concat([stored_on("trades", "ESH2026", day) for day in TRADE_DATES]).height
    )
    note = "    2026-03-09: cut 1 record of trades after the last bar that holds them"
    assert note in build.summary().splitlines()


def test_a_root_that_two_providers_hold_needs_one_named(tmp_path: Path) -> None:
    store = store_copy(tmp_path)
    shutil.copytree(tmp_path / "data" / "synthetic", tmp_path / "data" / "copy")

    with pytest.raises(
        ValueError, match="Expected one provider of ES in the store, got copy and synthetic"
    ):
        build_engine_cache(store, tmp_path / "cache", "ES", 2026)
    build = build_engine_cache(store, tmp_path / "cache", "ES", 2026, provider="copy")

    assert build.provider == "copy"
    assert read_cache_month_index(month_folder(tmp_path / "cache", "ESH2026", "copy")) is not None
    assert not (tmp_path / "cache" / ENGINE_CACHE_FOLDER_NAME / "synthetic").exists()


def test_a_year_without_trade_dates_caches_nothing(tmp_path: Path) -> None:
    build = build_engine_cache(store_copy(tmp_path), tmp_path / "cache", "ES", 2025)

    assert build.months == ()
    assert (
        build.summary() == "ES (synthetic) 2025: no trade dates in the store, so nothing to cache."
    )
    assert not (tmp_path / "cache").exists()


def test_a_crypto_perpetual_caches_its_day_of_trades_seconds_and_minutes(tmp_path: Path) -> None:
    build = build_engine_cache(store_copy(tmp_path), tmp_path / "cache", "BTCUSDT-PERP", 2026)

    (month,) = build.months
    assert month.index.levels_summary() == "1m 1 day, 1s 1 day, trades 1 day"
    assert build.summary().startswith(
        "BTCUSDT-PERP (synthetic) 2026: 1 contract-month built, 0 up to date, 1 trade date, "
    )


def test_the_status_lists_each_cached_contract_month_with_its_levels(cache: Path) -> None:
    lines = [month.summary() for month in engine_cache_status(cache)]

    assert len(lines) == 2
    for line, contract in zip(lines, CONTRACTS, strict=True):
        levels = "1m 3 days, 1s 3 days, trades 3 days"
        pattern = f"synthetic ES {contract} 2026-03: {levels}, [0-9]+[.][0-9] MB"
        assert re.fullmatch(pattern, line), line
    assert engine_cache_status(cache, root="MES") == ()
    assert engine_cache_status(cache.parent / "nothing") == ()
