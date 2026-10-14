import hashlib
import json
import os
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from databento_dbn import (
    F_BAD_TS_RECV,
    F_LAST,
    Action,
    BidAskPair,
    DBNRecord,
    InstrumentClass,
    InstrumentDefMsg,
    MBP1Msg,
    OHLCVMsg,
    RType,
    Schema,
    SecurityUpdateAction,
    Side,
    StatMsg,
    StatType,
    StatUpdateAction,
    TradeMsg,
)
from polars.testing import assert_frame_equal

from dbn_files import NANOSECONDS_PER_MINUTE, dbn_content, mapping, utc, write_dbn
from fefat.market.calendar import utc_text
from fefat.market.importers.databento import import_databento, vendor_conditions
from fefat.market.importers.report import DatabentoImport, DayRecords, EarlySymbol, SymbolRecords
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.raw_manifest import BatchJob, RawFile, RawManifest
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
JOB = "GLBX-20260310-SYNTHETIC0"
BATCH = FIXTURES / "synthetic" / "databento-batch" / JOB
DATA_FILE = "glbx-mdp3-20260304-20260309.ohlcv-1m.dbn"
SYNTHETIC_MINUTES = Partition(
    dataset=Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES"),
    contract="ESH2026",
    key=YearMonth(year=2026, month=3),
)
IMPORTED_MINUTES = Partition(
    dataset=Dataset(provider="databento", schema_name=parse_schema_name("ohlcv-1m"), root="ES"),
    contract="ESH2026",
    key=YearMonth(year=2026, month=3),
)
ONE_MINUTE = int(RType.from_str("ohlcv-1m"))
ONE_DAY = int(RType.from_str("ohlcv-1d"))
ESH6 = [mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21))]


def imported(folder: Path, source: Path = BATCH) -> tuple[Store, DatabentoImport]:
    store = Store(folder / "data")
    return store, import_databento(source, store, folder / "cache")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def published_hashes(folder: Path) -> dict[str, str]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    return {entry["filename"]: entry["hash"].removeprefix("sha256:") for entry in manifest["files"]}


def store_files(folder: Path) -> dict[str, tuple[int, int]]:
    """Every file under the store folder with its size and modification time."""
    return {
        path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in folder.rglob("*")
        if path.is_file()
    }


def test_a_batch_download_is_imported_with_its_raw_files_in_the_manifest(tmp_path: Path) -> None:
    store, report = imported(tmp_path)

    bars = store.scan_partition(IMPORTED_MINUTES).collect().sort("ts_open")
    synthetic = Store(FIXTURES).scan_partition(SYNTHETIC_MINUTES).collect().sort("ts_open")
    published = published_hashes(BATCH)
    names = sorted((DATA_FILE, "condition.json", "manifest.json", "metadata.json"))
    first, last = utc_text(bars.item(0, "ts_open")), utc_text(bars.item(-1, "ts_open"))
    assert [file.partition for file in store.list_partitions()] == [IMPORTED_MINUTES]
    assert_frame_equal(bars.drop("trade_count", "vwap"), synthetic.drop("trade_count", "vwap"))
    assert bars.get_column("trade_count").null_count() == bars.height
    assert bars.get_column("vwap").null_count() == bars.height
    assert store.raw_manifest() == RawManifest(
        files=tuple(
            RawFile(
                path=f"databento/{JOB}/{name}",
                size_bytes=(BATCH / name).stat().st_size,
                sha256=sha256_of(BATCH / name),
                provider="databento",
                vendor_version=f"{'DBN 3, ' if name == DATA_FILE else ''}revised 2026-03-09",
                downloaded_on=date(2026, 3, 10),
                batch_job=None
                if name == "manifest.json"
                else BatchJob(job_id=JOB, published_sha256=published[name]),
            )
            for name in names
        )
    )
    # 4,141 ES bars and 42 bars of the calendar spread, one beside every hundredth. The bar
    # opening at 16:00 CST on Friday 03-06 holds the print received after the close (step 1.5),
    # outside every session and dated by the session before it.
    assert report.summary().splitlines() == [
        f"Imported 1 file from {BATCH}.",
        f"Databento batch {JOB}, data revised up to 2026-03-09.",
        "Days the vendor marks degraded (1): 2026-03-06",
        f"databento/{JOB}/{DATA_FILE}: ohlcv-1m, DBN version 3, 4,183 records from {first} to "
        f"{last}",
        f"  ES: 1 contract, ESH2026, 4,141 records from {first} to {last}",
        "  Spreads and strategies set aside: 1 symbol, 42 records",
        "  Before their product's first trade date: none",
        "  Outside every session: 1 record on 1 trade date: 2026-03-06 (1)",
        "  Clock: never decreases",
        "  Partitions: 1 written, 0 already stored",
    ]


def test_importing_the_same_batch_again_imports_nothing_and_says_so(tmp_path: Path) -> None:
    imported(tmp_path)
    before = store_files(tmp_path / "data")

    _, again = imported(tmp_path)

    assert again.files == ()
    assert again.already_imported == (f"databento/{JOB}/{DATA_FILE}",)
    assert again.summary().splitlines() == [
        f"Nothing to import from {BATCH}: every file is already imported.",
        f"Databento batch {JOB}, data revised up to 2026-03-09.",
        "Days the vendor marks degraded (1): 2026-03-06",
        f"Already imported: databento/{JOB}/{DATA_FILE}",
    ]
    assert store_files(tmp_path / "data") == before


def test_a_file_whose_sha256_differs_from_the_vendors_manifest_is_refused_with_both_hashes(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "batch"
    shutil.copytree(BATCH, batch)
    data_file = batch / DATA_FILE
    content = bytearray(data_file.read_bytes())
    content[-1] ^= 0xFF
    data_file.write_bytes(bytes(content))
    published, actual = published_hashes(batch)[DATA_FILE], sha256_of(data_file)

    with pytest.raises(ValueError, match=f"SHA-256 {published} .* got {actual}"):
        imported(tmp_path, batch)

    store = Store(tmp_path / "data")
    assert store.list_partitions() == ()
    assert store.raw_manifest() == RawManifest()


def test_a_recorded_file_whose_bytes_changed_is_refused_with_both_hashes(tmp_path: Path) -> None:
    # A re-normalised download under the same job and name, with a manifest.json to match it:
    # the vendor's hash agrees, but the raw file the store recorded never changes.
    store, _ = imported(tmp_path / "first")
    before = store_files(tmp_path / "first" / "data")
    batch = tmp_path / "batch"
    shutil.copytree(BATCH, batch)
    data_file = batch / DATA_FILE
    content = bytearray(data_file.read_bytes())
    content[-1] ^= 0xFF
    data_file.write_bytes(bytes(content))
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["filename"] == DATA_FILE:
            entry["hash"] = f"sha256:{sha256_of(data_file)}"
    (batch / "manifest.json").write_text(json.dumps(manifest, indent=4), encoding="utf-8")
    recorded, changed = sha256_of(BATCH / DATA_FILE), sha256_of(data_file)

    with pytest.raises(ValueError, match=f"recorded with the SHA-256 {recorded}, got {changed}"):
        import_databento(batch, store, tmp_path / "first" / "cache")

    assert store_files(tmp_path / "first" / "data") == before


def test_the_vendors_conditions_are_stored_and_the_summary_lists_the_degraded_days(
    tmp_path: Path,
) -> None:
    store, report = imported(tmp_path)

    conditions = vendor_conditions(store, JOB)

    expected = pl.DataFrame(
        {
            "date": [date(2026, 3, day) for day in (4, 5, 6, 8, 9)],
            "condition": ["available", "available", "degraded", "available", "available"],
            "last_modified_date": [date(2026, 3, 8)] * 4 + [date(2026, 3, 9)],
        }
    )
    assert_frame_equal(conditions, expected)
    assert "Days the vendor marks degraded (1): 2026-03-06" in report.summary().splitlines()


def es_bars(*instants: int) -> list[OHLCVMsg]:
    return [
        OHLCVMsg(ONE_MINUTE, 1, 1001, instant, 6_750_000_000_000, 6_751_000_000_000, 6_749_000_000_000, 6_750_500_000_000, 10)
        for instant in instants
    ]  # fmt: skip


def loose_file(folder: Path, name: str, content: bytes) -> Path:
    return write_dbn(folder / "files" / name, content)


def test_a_bar_outside_every_session_takes_the_session_before_it_and_is_counted(
    tmp_path: Path,
) -> None:
    # Friday 2026-03-06 15:00 CST is 21:00 UTC, inside Friday's session; Saturday noon is
    # outside every session and takes Friday's trade date; Monday 03-09 14:30 UTC is inside.
    friday, saturday, monday = utc(2026, 3, 6, 21), utc(2026, 3, 7, 12), utc(2026, 3, 9, 14, 30)
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(friday, saturday, monday))
    store, report = imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1m.dbn", content))

    bars = store.scan_partition(IMPORTED_MINUTES).collect()

    assert bars.get_column("trade_date").to_list() == [
        date(2026, 3, 6),
        date(2026, 3, 6),
        date(2026, 3, 9),
    ]
    assert report.files[0].outside_sessions == (DayRecords(trade_date=date(2026, 3, 6), records=1),)
    assert store.raw_manifest().files[0].path == (
        f"databento/{hashlib.sha256(content).hexdigest()}/es.ohlcv-1m.dbn"
    )
    assert store.raw_manifest().files[0].batch_job is None


def test_records_out_of_clock_order_are_counted_and_still_stored_in_order(tmp_path: Path) -> None:
    later, earlier = utc(2026, 3, 9, 14, 31), utc(2026, 3, 9, 14, 30)
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(later, earlier))
    store, report = imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1m.dbn", content))

    stored = store.scan_partition(IMPORTED_MINUTES).collect()

    assert report.files[0].clock_decreases == 1
    first = report.files[0].first_clock_decrease
    assert first is not None
    assert (first.record, first.instant, first.before) == (1, earlier, later)
    assert stored.get_column("ts_open").to_list() == [earlier, later]
    assert f"Clock: decreases 1 time, the first at record 1: {utc_text(earlier)}" in (
        report.summary()
    )


def test_bars_before_their_products_first_trade_date_are_set_aside_with_a_count(
    tmp_path: Path,
) -> None:
    # Micro E-mini S&P 500 began trading on 2019-05-06, but the vendor maps MESM9 from
    # 2019-04-14: a bar of Thursday 2019-05-02 is set aside, one of Monday 2019-05-06 is kept.
    mesm9 = [mapping("MESM9", 7001, date(2019, 4, 14), date(2019, 6, 22))]
    thursday, monday = utc(2019, 5, 2, 14, 30), utc(2019, 5, 6, 14, 30)
    bars = [OHLCVMsg(ONE_MINUTE, 1, 7001, instant, 1, 1, 1, 1, 1) for instant in (thursday, monday)]
    content = dbn_content(Schema("ohlcv-1m"), mesm9, bars)
    store, report = imported(tmp_path, loose_file(tmp_path, "mes.ohlcv-1m.dbn", content))

    mes = Partition(
        dataset=Dataset(
            provider="databento", schema_name=parse_schema_name("ohlcv-1m"), root="MES"
        ),
        contract="MESM2019",
        key=YearMonth(year=2019, month=5),
    )

    assert store.scan_partition(mes).collect().get_column("ts_open").to_list() == [monday]
    assert report.files[0].before_first_trade_date == (
        EarlySymbol(
            raw_symbol="MESM9",
            records=1,
            first_trade_date=date(2019, 5, 2),
            last_trade_date=date(2019, 5, 2),
        ),
    )


def test_the_vendors_daily_bars_are_skipped_with_a_count(tmp_path: Path) -> None:
    daily = [OHLCVMsg(ONE_DAY, 1, 1001, utc(2026, 3, 9), 1, 1, 1, 1, 1)]
    content = dbn_content(Schema("ohlcv-1d"), ESH6, daily)
    store, report = imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1d.dbn", content))

    assert report.files == ()
    sha256 = hashlib.sha256(content).hexdigest()
    assert report.daily_bars_skipped == (f"databento/{sha256}/es.ohlcv-1d.dbn",)
    assert store.list_partitions() == ()
    assert store.raw_manifest() == RawManifest()


def test_a_zstd_file_imports_the_same_partition_as_the_plain_one(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 9, 14, 30)))
    plain, _ = imported(tmp_path / "plain", loose_file(tmp_path, "es.ohlcv-1m.dbn", content))
    compressed_file = loose_file(tmp_path, "es.ohlcv-1m.dbn.zst", content)
    compressed, _ = imported(tmp_path / "zstd", compressed_file)

    assert_frame_equal(
        compressed.scan_partition(IMPORTED_MINUTES).collect(),
        plain.scan_partition(IMPORTED_MINUTES).collect(),
    )


def test_ticks_go_to_their_sessions_trade_date_and_unreliable_receive_times_are_counted(
    tmp_path: Path,
) -> None:
    # Sunday 2026-03-08 22:00:00.5 UTC is 17:00:00.5 CDT, the first second of Monday 03-09's
    # session, on the UTC date before it; its flags mark its ts_recv unreliable.
    sunday_evening, monday = utc(2026, 3, 8, 22) + 500_000_000, utc(2026, 3, 9, 14, 30)
    trades = [
        TradeMsg(publisher_id=1, instrument_id=1001, ts_event=instant - 1_000, price=6_750_000_000_000, size=1, action=Action("T"), side=Side("B"), depth=0, ts_recv=instant, flags=flags, sequence=sequence)
        for sequence, (instant, flags) in enumerate(((sunday_evening, F_LAST | F_BAD_TS_RECV), (monday, F_LAST)))
    ]  # fmt: skip
    content = dbn_content(Schema("trades"), ESH6, trades)
    store, report = imported(tmp_path, loose_file(tmp_path, "es.trades.dbn", content))

    monday_trades = Partition(
        dataset=Dataset(provider="databento", schema_name=parse_schema_name("trades"), root="ES"),
        contract="ESH2026",
        key=date(2026, 3, 9),
    )

    assert [file.partition for file in store.list_partitions()] == [monday_trades]
    assert store.scan_partition(monday_trades).collect().get_column("ts_recv").to_list() == [
        sunday_evening,
        monday,
    ]
    assert report.files[0].unreliable_ts_recv == (
        DayRecords(trade_date=date(2026, 3, 9), records=1),
    )


def test_a_path_that_is_neither_a_batch_folder_nor_a_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Expected a Databento batch folder or DBN file"):
        imported(tmp_path, tmp_path / "missing")


def batch_copy(folder: Path) -> Path:
    batch = folder / "batch"
    shutil.copytree(BATCH, batch)
    return batch


def publish(batch: Path, name: str) -> None:
    """List `name` in the batch's manifest.json with its size and SHA-256, as the vendor would."""
    manifest_path = batch / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = {
        "filename": name,
        "size": (batch / name).stat().st_size,
        "hash": f"sha256:{sha256_of(batch / name)}",
    }
    files = [file for file in manifest["files"] if file["filename"] != name]
    manifest["files"] = [*files, entry]
    manifest_path.write_text(json.dumps(manifest, indent=4), encoding="utf-8")


def test_a_file_of_spreads_only_writes_nothing_and_counts_them(tmp_path: Path) -> None:
    spread = [OHLCVMsg(ONE_MINUTE, 1, 1002, utc(2026, 3, 9, 14, 30), -1, -1, -1, -1, 2)]
    content = dbn_content(Schema("ohlcv-1m"), ESH6_AND_SPREAD, spread)

    store, report = imported(tmp_path, loose_file(tmp_path, "spread.ohlcv-1m.dbn", content))

    assert store.list_partitions() == ()
    assert report.files[0].spreads == (SymbolRecords(raw_symbol="ESH6-ESM6", records=1),)


def test_a_batch_split_into_several_data_files_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # A batch split by day or month gives two files rows of one partition, which the importer
    # does not merge, so it refuses the batch rather than stop after its first file.
    batch = batch_copy(tmp_path)
    shutil.copyfile(batch / DATA_FILE, batch / "glbx-mdp3-20260310-20260310.ohlcv-1m.dbn")
    publish(batch, "glbx-mdp3-20260310-20260310.ohlcv-1m.dbn")

    with pytest.raises(ValueError, match="Expected one DBN file in the batch"):
        imported(tmp_path, batch)

    assert not (tmp_path / "data").exists()


def test_a_refused_file_leaves_no_copy_under_raw(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 21, 14, 30)))

    with pytest.raises(ValueError, match="got none for instrument_id 1001"):
        imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1m.dbn", content))

    assert list((tmp_path / "data").rglob("*.dbn")) == []


def test_a_batch_without_revision_dates_imports_and_says_so(tmp_path: Path) -> None:
    batch = batch_copy(tmp_path)
    conditions = json.loads((batch / "condition.json").read_text(encoding="utf-8"))
    for day in conditions:
        day["condition"], day["last_modified_date"] = "pending", None
    (batch / "condition.json").write_text(json.dumps(conditions, indent=4), encoding="utf-8")
    publish(batch, "condition.json")

    store, report = imported(tmp_path, batch)

    data_file = store.raw_manifest().file_at(f"databento/{JOB}/{DATA_FILE}")
    assert data_file is not None
    assert data_file.vendor_version == "DBN 3, no revision date"
    assert report.summary().splitlines()[1:3] == [
        f"Databento batch {JOB}, no revision date in its conditions.",
        "Days the vendor marks pending (5): 2026-03-04, 2026-03-05, 2026-03-06, 2026-03-08, "
        "2026-03-09",
    ]


def test_a_rerun_reads_no_file_the_raw_manifest_already_records(tmp_path: Path) -> None:
    # The store keeps its own verified copy, so a re-run checks the vendor's published hash
    # against the recorded one and never reads the batch's files again.
    batch = batch_copy(tmp_path)
    imported(tmp_path, batch)
    (batch / DATA_FILE).write_bytes(b"a later copy that was cut short")

    _, again = imported(tmp_path, batch)

    assert again.already_imported == (f"databento/{JOB}/{DATA_FILE}",)


def test_a_single_files_download_date_is_the_utc_date_it_was_last_written(
    tmp_path: Path,
) -> None:
    # An instant whose local date differs from its UTC date on this machine: 23:30 UTC is the
    # next day east of UTC, 00:30 UTC the day before west of it, so the date must come from UTC.
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 9, 14, 30)))
    source = loose_file(tmp_path, "es.ohlcv-1m.dbn", content)
    east = time.localtime(utc(2026, 3, 10, 12) // 1_000_000_000).tm_gmtoff > 0
    written = utc(2026, 3, 10, 23, 30) if east else utc(2026, 3, 10, 0, 30)
    os.utime(source, (written // 1_000_000_000, written // 1_000_000_000))

    store, _ = imported(tmp_path, source)

    assert store.raw_manifest().files[0].downloaded_on == date(2026, 3, 10)


def test_a_bar_whose_instrument_id_the_symbology_does_not_cover_is_refused(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 21, 14, 30)))

    with pytest.raises(ValueError, match="got none for instrument_id 1001 on 2026-03-21"):
        imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1m.dbn", content))


def test_single_files_of_one_name_are_told_apart_by_their_content(tmp_path: Path) -> None:
    # Databento names a file by dataset, dates, and schema, not by product, so a second
    # purchase of another product over the same dates has the same name.
    mesh6 = [mapping("MESH6", 7001, date(2025, 3, 21), date(2026, 3, 21))]
    mes_bars = [OHLCVMsg(ONE_MINUTE, 1, 7001, utc(2026, 3, 9, 14, 30), 1, 1, 1, 1, 1)]
    es_content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 9, 14, 30)))
    mes_content = dbn_content(Schema("ohlcv-1m"), mesh6, mes_bars)
    store = Store(tmp_path / "data")
    name = "glbx-mdp3-20260309-20260309.ohlcv-1m.dbn"

    import_databento(write_dbn(tmp_path / "es" / name, es_content), store, tmp_path / "cache")
    mes = import_databento(
        write_dbn(tmp_path / "mes" / name, mes_content), store, tmp_path / "cache"
    )
    again = import_databento(tmp_path / "es" / name, store, tmp_path / "cache")

    assert [file.partition.dataset.root for file in store.list_partitions()] == ["ES", "MES"]
    assert mes.files[0].contracts[0].contract == "MESH2026"
    assert again.already_imported == (f"databento/{hashlib.sha256(es_content).hexdigest()}/{name}",)


def test_bars_a_minute_apart_are_one_minute_long(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), ESH6, es_bars(utc(2026, 3, 9, 14, 30)))
    store, _ = imported(tmp_path, loose_file(tmp_path, "es.ohlcv-1m.dbn", content))

    bar = store.scan_partition(IMPORTED_MINUTES).collect().row(0, named=True)

    assert bar["ts_close"] - bar["ts_open"] == NANOSECONDS_PER_MINUTE


MONDAY = utc(2026, 3, 9, 14, 30)
ESH6_AND_SPREAD = [*ESH6, mapping("ESH6-ESM6", 1002, date(2025, 12, 12), date(2026, 3, 21))]


def tbbo_record(**fields: Any) -> MBP1Msg:
    """A TBBO record: the decoder's stub types `levels` as a list, while it takes one pair."""
    return MBP1Msg(**fields)


SCHEMA_FILES: list[tuple[str, list[DBNRecord], str]] = [
    (
        "tbbo",
        [tbbo_record(publisher_id=1, instrument_id=1001, ts_event=MONDAY, price=6_750_250_000_000, size=2, action=Action("T"), side=Side("B"), depth=0, ts_recv=MONDAY + 50_000, flags=F_LAST, sequence=11, levels=BidAskPair(bid_px=6_750_000_000_000, ask_px=6_750_250_000_000, bid_sz=8, ask_sz=1))],
        "databento/tbbo/root=ES/contract=ESH2026/date=2026-03-09/part.parquet",
    ),
    (
        "ohlcv-1s",
        [OHLCVMsg(int(RType.from_str("ohlcv-1s")), 1, 1001, MONDAY, 1, 2, 0, 1, 5)],
        "databento/ohlcv-1s/root=ES/contract=ESH2026/date=2026-03-09/part.parquet",
    ),
    (
        "definition",
        [
            InstrumentDefMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, ts_recv=MONDAY + 1, min_price_increment=250_000_000, display_factor=1_000_000_000, raw_symbol="ESH6", asset="ES", security_type="FUT", instrument_class=InstrumentClass("F"), security_update_action=SecurityUpdateAction("A"), expiration=utc(2026, 3, 20, 13, 30), activation=utc(2025, 3, 21, 22), maturity_year=2026, maturity_month=3),
            InstrumentDefMsg(publisher_id=1, instrument_id=1002, ts_event=MONDAY, ts_recv=MONDAY + 2, min_price_increment=50_000_000, display_factor=1_000_000_000, raw_symbol="ESH6-ESM6", asset="ES", security_type="FUT", instrument_class=InstrumentClass("S"), security_update_action=SecurityUpdateAction("A")),
        ],
        "databento/definitions/root=ES/contract=ESH2026/part.parquet",
    ),
    (
        "statistics",
        [StatMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, ts_recv=MONDAY + 3, ts_ref=utc(2026, 3, 9), price=6_751_000_000_000, quantity=0, stat_type=StatType(3), sequence=21, update_action=StatUpdateAction(1), stat_flags=1)],
        "databento/statistics/root=ES/contract=ESH2026/part.parquet",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("schema", "records", "stored_at"), SCHEMA_FILES)
def test_each_schema_lands_in_its_partition_with_the_store_columns(
    tmp_path: Path, schema: str, records: list[DBNRecord], stored_at: str
) -> None:
    content = dbn_content(Schema(schema), ESH6_AND_SPREAD, records)
    store, report = imported(tmp_path, loose_file(tmp_path, f"es.{schema}.dbn", content))

    partitions = [file.partition for file in store.list_partitions()]

    assert [partition.relative_path().as_posix() for partition in partitions] == [stored_at]
    assert store.scan_partition(partitions[0]).collect().height == 1
    assert report.files[0].contracts[0].contract == "ESH2026"


def test_a_spreads_definition_is_set_aside_with_a_count(tmp_path: Path) -> None:
    _, records, _ = SCHEMA_FILES[2]
    content = dbn_content(Schema("definition"), ESH6_AND_SPREAD, records)

    _, report = imported(tmp_path, loose_file(tmp_path, "es.definition.dbn", content))

    assert report.files[0].spreads == (SymbolRecords(raw_symbol="ESH6-ESM6", records=1),)


def test_a_contract_whose_symbology_runs_on_past_its_bars_is_named_by_its_bars(
    tmp_path: Path,
) -> None:
    # The MNQ batch on this PC maps MNQM3 until the end of its query, 2026-09-23, three years
    # after the contract expired; its bars end on its last trade date, 2023-06-16 (08:29 CDT).
    mnqm3 = [mapping("MNQM3", 4973, date(2022, 3, 6), date(2026, 9, 23))]
    bars = [OHLCVMsg(ONE_MINUTE, 1, 4973, utc(2023, 6, 16, 13, 29), 1, 1, 1, 1, 1)]
    content = dbn_content(Schema("ohlcv-1m"), mnqm3, bars)

    store, report = imported(tmp_path, loose_file(tmp_path, "mnq.ohlcv-1m.dbn", content))

    assert [file.partition.contract for file in store.list_partitions()] == ["MNQM2023"]
    assert report.files[0].contracts[0].expiry == "2023-06"
