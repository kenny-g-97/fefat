"""What reads the store after a merge (step 5.14, ADR-0021, Done means 4 and 5): a snapshot
taken before it refuses the merged partition by its path, a clean quality report reads stale,
the engine's cache, the features' cache, and the roll calendar build again for what changed and
for nothing before it, and the leak detector passes on a store two overlapping files built. The
store is ES's dense 1-minute bars of `generated_minutes`, written as two DBN files that overlap
in February: the first holds ESH2026 up to 2026-02-20, the second carries it on from 02-10 to
its last trade date and brings ESM2026, which leads from 03-11, so the merge changes February,
adds March, and gives the series its roll."""

import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from databento_dbn import OHLCVMsg, RType, Schema
from polars.testing import assert_frame_equal

import fefat as ff
from dbn_files import dbn_content, mapping, utc, write_dbn
from fefat.config import resolve_paths
from fefat.features.examples import rsi
from fefat.market import instruments
from fefat.market.api import SIGNAL_BAR_COLUMNS, roll_calendar
from fefat.market.calendar import sessions_of
from fefat.market.engine_cache import MonthOutcome, build_engine_cache
from fefat.market.importers.databento import import_databento
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.quality import assess_quality
from fefat.market.quality_report import QualityStatus, write_quality_report
from fefat.market.schema import parse_schema_name
from fefat.market.status import dataset_standing
from fefat.market.store import Store
from generated_minutes import listing, minutes_of
from test_features_cache import cache_folder, rewritten, written
from test_market_importers_merge_properties import es_bars, march_file

ONE_MINUTE = int(RType.from_str("ohlcv-1m"))
IMPORTED_ON = date(2026, 11, 14)
MINUTES = Dataset(provider="databento", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
LISTINGS = (
    listing("ESH2026", 1001, ("2026-01-02", "2026-03-20"), ("2026-01-02", "2026-03-10")),
    listing("ESM2026", 1003, ("2026-02-23", "2026-03-31"), ("2026-03-11", "2026-03-31")),
)
SYMBOLOGY = [
    mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21)),
    mapping("ESM6", 1003, date(2025, 6, 20), date(2026, 6, 20)),
]
FIRST_ENDS, SECOND_STARTS = date(2026, 2, 20), date(2026, 2, 10)


@dataclass(frozen=True)
class OverlappingFiles:
    """Two DBN files of one stream of bars: `first` up to `FIRST_ENDS`, and `second` from
    `SECOND_STARTS` on."""

    first: Path
    second: Path


def dbn_file(path: Path, bars: pl.DataFrame) -> Path:
    records = [
        OHLCVMsg(ONE_MINUTE, 1, instrument_id, ts_open, opened, high, low, close, volume)
        for ts_open, instrument_id, opened, high, low, close, volume in bars.select(
            "ts_open", "instrument_id", "open", "high", "low", "close", "volume"
        ).iter_rows()
    ]
    return write_dbn(path, dbn_content(Schema("ohlcv-1m"), SYMBOLOGY, records))


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> OverlappingFiles:
    folder = tmp_path_factory.mktemp("overlapping")
    sessions = sessions_of(instruments.get("ES").session_calendar(), folder / "cache")
    bars = pl.concat([minutes_of(each, sessions.between(*each.trades)) for each in LISTINGS]).sort(
        "ts_open", "instrument_id"
    )
    return OverlappingFiles(
        first=dbn_file(
            folder / "first" / "es.ohlcv-1m.dbn", bars.filter(pl.col("trade_date") <= FIRST_ENDS)
        ),
        second=dbn_file(
            folder / "second" / "es.ohlcv-1m.dbn",
            bars.filter(pl.col("trade_date") >= SECOND_STARTS),
        ),
    )


def imported(*sources: Path) -> Store:
    """The files imported, in order, into the test's data folder."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    for source in sources:
        import_databento(source, store, paths.cache_dir, imported_on=IMPORTED_ON)
    return store


def month_outcomes(store: Store) -> dict[tuple[str, str], MonthOutcome]:
    build = build_engine_cache(store, resolve_paths(os.environ).cache_dir, "ES", 2026)
    assert build.refused == ()
    return {(month.index.contract, str(month.index.month)): month.outcome for month in build.months}


def test_the_engines_cache_builds_the_contract_months_a_merge_changed_alone(
    files: OverlappingFiles,
) -> None:
    store = imported(files.first)
    built = month_outcomes(store)

    imported(files.second)

    assert built == {
        ("ESH2026", "2026-01"): MonthOutcome.BUILT,
        ("ESH2026", "2026-02"): MonthOutcome.BUILT,
    }
    assert month_outcomes(store) == {
        ("ESH2026", "2026-01"): MonthOutcome.UP_TO_DATE,
        ("ESH2026", "2026-02"): MonthOutcome.BUILT,
        ("ESH2026", "2026-03"): MonthOutcome.BUILT,
        ("ESM2026", "2026-02"): MonthOutcome.BUILT,
        ("ESM2026", "2026-03"): MonthOutcome.BUILT,
    }


def test_the_features_cache_computes_what_a_merge_changed_and_nothing_before_it(
    files: OverlappingFiles,
) -> None:
    # February's partitions read a month whose file changed, and March's are new; January's read
    # nothing that changed and stay. The values up to the first file's end are the ones computed
    # before the merge: later data never changes them.
    slots = {"rsi": rsi(n=14)}
    imported(files.first)
    before = ff.features.compute(slots, "ES", "5m", "2026-01-05", FIRST_ENDS).collect()
    cached = written()

    imported(files.second)
    after = ff.features.compute(slots, "ES", "5m", "2026-01-05", "2026-03-20").collect()

    assert rewritten(cached) == {
        f"{folder}/{month}" for folder in ("bars", "rsi") for month in ("2026-02", "2026-03")
    }
    up_to_the_join = after.filter(pl.col("trade_date") <= FIRST_ENDS)
    bars = list(SIGNAL_BAR_COLUMNS)
    assert up_to_the_join.select(bars).equals(before.select(bars))
    assert_frame_equal(up_to_the_join.select("rsi"), before.select("rsi"), rel_tol=1e-9, abs_tol=0)
    assert after.filter(pl.col("trade_date") > FIRST_ENDS).height > 0


def test_the_features_cache_computes_again_what_a_backfill_reaches(files: OverlappingFiles) -> None:
    # The leakage audit of step 5.14: the second file alone starts on 02-10, so its first bars'
    # values wait for their warm-up; the first file then brings the sessions before them, and
    # what was cached is computed again, to the values a clean cache gives.
    slots, window = {"rsi": rsi(n=14)}, ("2026-02-11", "2026-03-20")
    imported(files.second)
    before = ff.features.compute(slots, "ES", "5m", *window).collect()
    cached = written()

    imported(files.first)
    after = ff.features.compute(slots, "ES", "5m", *window).collect()
    computed_again = rewritten(cached)
    shutil.rmtree(cache_folder())
    clean = ff.features.compute(slots, "ES", "5m", *window).collect()

    assert before.item(0, "rsi") is None and clean.item(0, "rsi") is not None
    assert_frame_equal(after, clean)
    assert computed_again == {
        f"{folder}/{month}" for folder in ("bars", "rsi") for month in ("2026-02", "2026-03")
    }


def test_a_session_carried_on_gives_its_held_back_bucket_and_changes_nothing_before_it(
    files: OverlappingFiles, tmp_path: Path
) -> None:
    # The leakage audit of step 5.14: the first file stops inside a session, at 15:03 of 02-20,
    # so the 5-minute bucket from 15:00 is held back as unfinished. The file that carries the
    # session on completes it, and no bar or value before the stop changes.
    sessions = sessions_of(instruments.get("ES").session_calendar(), tmp_path / "cache")
    minutes = pl.concat(
        [minutes_of(each, sessions.between(*each.trades)) for each in LISTINGS]
    ).sort("ts_open", "instrument_id")
    stops = utc(2026, 2, 20, 15, 3)
    cut_short = dbn_file(
        tmp_path / "cut-short" / "es.ohlcv-1m.dbn", minutes.filter(pl.col("ts_close") <= stops)
    )
    slots = {"rsi": rsi(n=14)}
    imported(cut_short)
    before = ff.features.compute(slots, "ES", "5m", "2026-01-05", FIRST_ENDS).collect()
    cached = written()

    imported(files.second)
    after = ff.features.compute(slots, "ES", "5m", "2026-01-05", FIRST_ENDS).collect()

    assert before.get_column("ts_close").max() == utc(2026, 2, 20, 15, 0)
    assert after.filter(pl.col("ts_close") == utc(2026, 2, 20, 15, 5)).height == 1
    up_to_the_stop = after.filter(pl.col("ts_close") <= stops)
    bars = list(SIGNAL_BAR_COLUMNS)
    assert up_to_the_stop.select(bars).equals(before.select(bars))
    assert_frame_equal(up_to_the_stop.select("rsi"), before.select("rsi"), rel_tol=1e-9, abs_tol=0)
    assert rewritten(cached) == {"bars/2026-02", "rsi/2026-02"}


def test_the_roll_calendar_is_built_again_once_a_merge_brings_the_next_contract(
    files: OverlappingFiles,
) -> None:
    imported(files.first)
    alone = roll_calendar("ES").rolls()

    imported(files.second)
    rolls = roll_calendar("ES").rolls()

    assert alone.is_empty()
    assert rolls.select("trade_date", "rolled_from", "contract").rows() == [
        (date(2026, 3, 12), "ESH2026", "ESM2026")
    ]


def test_the_leak_detector_passes_on_a_merged_store(files: OverlappingFiles) -> None:
    # The window spans the join of the two files, on 02-20, and the roll the second file brings.
    imported(files.first, files.second)

    report = ff.features.validate(rsi(n=14), "ES", "5m", "2026-02-11", "2026-03-18", seed=3)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0


def stored_bars(store: Store) -> dict[str, list[tuple[object, ...]]]:
    return {
        file.partition.relative_path().as_posix(): store.scan_partition(file.partition)
        .collect()
        .rows()
        for file in store.list_partitions()
    }


def test_two_files_merged_in_either_order_hold_the_bars_of_both(
    files: OverlappingFiles, tmp_path: Path
) -> None:
    def stored(name: str, sources: Sequence[Path]) -> dict[str, list[tuple[object, ...]]]:
        store = Store(tmp_path / name)
        for source in sources:
            import_databento(source, store, tmp_path / "cache", imported_on=IMPORTED_ON)
        return stored_bars(store)

    forward = stored("forward", [files.first, files.second])

    assert stored("backward", [files.second, files.first]) == forward
    assert sorted(path.split("/", 3)[3] for path in forward) == [
        "contract=ESH2026/month=2026-01/part.parquet",
        "contract=ESH2026/month=2026-02/part.parquet",
        "contract=ESH2026/month=2026-03/part.parquet",
        "contract=ESM2026/month=2026-02/part.parquet",
        "contract=ESM2026/month=2026-03/part.parquet",
    ]


def test_a_snapshot_taken_before_a_merge_refuses_the_merged_month_by_its_path(
    files: OverlappingFiles,
) -> None:
    # Done means 4, at the store: January gains nothing and is not written again, so its pin
    # still reads; February's file is another, so the snapshot's reader is refused with its
    # path, and the same request pins anew.
    store = imported(files.first)
    request = PartitionRequest(dataset=MINUTES, start=date(2026, 1, 2), end=FIRST_ENDS)
    before = store.snapshot(request)
    january, february = before.partitions

    imported(files.second)

    folder = "databento/ohlcv-1m/root=ES"
    assert february.path == f"{folder}/contract=ESH2026/month=2026-02/part.parquet"
    assert store.read_pinned_partition(before, january).height > 0
    with pytest.raises(ValueError, match=rf"pinned {february.path}, got .* changed after the snap"):
        store.read(before)
    after = store.snapshot(request)
    assert after.sha256 != before.sha256
    assert after.partitions[0] == january
    assert [digest.path for digest in after.partitions[1:]] == [
        february.path,
        f"{folder}/contract=ESM2026/month=2026-02/part.parquet",
    ]


def test_a_clean_quality_report_reads_stale_once_a_merge_fills_an_earlier_session(
    tmp_path: Path,
) -> None:
    # Done means 4: the file adds the session before the stored ones to a month the store holds,
    # so the dataset's last trade date stays, and only the month's file, which the merge writes
    # again, is newer than the report (D-94). The times are the writes' own.
    store, cache, reports = Store(tmp_path / "data"), tmp_path / "cache", tmp_path / "reports"
    stored = es_bars(utc(2026, 3, 9, 14, 30), utc(2026, 3, 10, 14, 30))
    import_databento(march_file(tmp_path, "first", stored), store, cache, imported_on=IMPORTED_ON)
    write_quality_report(assess_quality(store, "databento", "ES", cache), reports)
    checked = dataset_standing(store, MINUTES, date(2026, 3, 10), reports)
    time.sleep(0.05)  # Windows' clock moves in ticks of up to 15.6 ms: the merge writes later

    earlier = es_bars(utc(2026, 3, 6, 14, 30), utc(2026, 3, 9, 14, 30))
    import_databento(
        march_file(tmp_path, "earlier", earlier), store, cache, imported_on=IMPORTED_ON
    )
    merged = dataset_standing(store, MINUTES, date(2026, 3, 10), reports)

    assert (checked.status, checked.checked_through) == (QualityStatus.CLEAN, date(2026, 3, 10))
    assert (merged.status, merged.checked_through) == (QualityStatus.STALE, date(2026, 3, 10))
