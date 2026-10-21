import gzip
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from export_samples import (
    ESH2026_MARCH_6_TRADES,
    HOUR,
    IMPORTED_ON,
    MINUTE,
    PRESETS,
    SAMPLES,
    a_new_product_profile,
    expected_minutes,
    five_minute_file,
    imported,
    minutes_of,
    rolled_databento_lines,
    sample_lines,
    sample_request,
    store_files,
    written_export,
)
from fefat.market.api import load
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.calendar_offset import CalendarOffset, OffsetCause
from fefat.market.importers.file_import import (
    AlreadyImported,
    FileImportReport,
    FileImportRequest,
    import_file,
    preview_file,
)
from fefat.market.importers.profile_contracts import ImportFacts
from fefat.market.importers.profile_records import mapped_records
from fefat.market.importers.profile_values import ProblemKind
from fefat.market.importers.profiles import BarStamp, ImportProfile
from fefat.market.importers.tabular import read_table
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    SeriesKind,
    SizeUnit,
)
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.store import Store


@pytest.mark.parametrize("preset", SAMPLES)
def test_each_preset_imports_its_sample_to_the_expected_canonical_frame(
    tmp_path: Path, preset: str
) -> None:
    store = imported(tmp_path, sample_request(preset))

    stored = store.scan_partition(minutes_of(preset)).collect()

    assert_frame_equal(stored, expected_minutes(preset))
    assert store.dataset_metadata(minutes_of(preset).dataset) == DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=SOURCE_GUIDE.source_of_preset(preset).licence_scope,
    )


def test_an_import_keeps_the_original_under_raw_user_with_a_manifest_entry(
    tmp_path: Path,
) -> None:
    path, _ = SAMPLES["ninjatrader"]
    store = imported(tmp_path, sample_request("ninjatrader"))

    (recorded,) = store.raw_manifest().files

    assert recorded.path.startswith("user/") and recorded.path.endswith("/ES 03-26.Last.txt")
    assert (recorded.provider, recorded.roots, recorded.imported_on) == (
        "ninjatrader",
        ("ES",),
        IMPORTED_ON,
    )
    assert recorded.vendor_version == "import profile ninjatrader"
    assert store.raw_file(PurePosixPath(recorded.path)) == path.read_bytes()


def test_a_sample_read_in_the_wrong_time_zone_is_flagged_with_the_offset_the_check_detected(
    tmp_path: Path,
) -> None:
    # NinjaTrader writes UTC. Read as Chicago time, CST until 2026-03-08, the bars run 6 hours
    # late on 03-05 and 03-06 and 5 on 03-09; the calendar check names the offset of most.
    request = sample_request("ninjatrader", time_zone="America/Chicago")

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    assert preview.reading.calendar.offsets == (
        CalendarOffset(
            dataset=minutes_of("ninjatrader").dataset,
            nanoseconds=6 * HOUR,
            cause=OffsetCause.TIME_ZONE,
            first_trade_date=date(2026, 3, 5),
            last_trade_date=date(2026, 3, 9),
        ),
    )
    with pytest.raises(ValueError, match="its records run 6 hours late against the calendar"):
        imported(tmp_path, request)
    assert not (tmp_path / "data").exists()


def test_a_sample_read_with_the_wrong_bar_stamping_is_flagged_with_one_bar(
    tmp_path: Path,
) -> None:
    # NinjaTrader stamps each bar at its close; read as stamped at the open, each session's
    # last bar opens at the close.
    timestamp = PRESETS["ninjatrader"].timestamp.model_copy(update={"stamp": BarStamp.OPEN})
    profile = PRESETS["ninjatrader"].model_copy(update={"timestamp": timestamp})
    request = sample_request("ninjatrader", profile=profile)

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    assert preview.reading.calendar.offsets == (
        CalendarOffset(
            dataset=minutes_of("ninjatrader").dataset,
            nanoseconds=MINUTE,
            cause=OffsetCause.BAR_STAMPING,
            first_trade_date=date(2026, 3, 5),
            last_trade_date=date(2026, 3, 9),
        ),
    )
    assert "It would be refused" in preview.summary()


def test_a_product_with_a_new_instrument_on_a_calendar_of_its_own_loads_at_its_fidelity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())
    store = imported(tmp_path, request)
    monkeypatch.setenv("FEFAT_DATA_DIR", str(store.folder))
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path))

    with pytest.warns(UserWarning, match="ohlcv-5m/root=XES holds 5-minute bars"):
        bars = load("XES", "5m", "2026-03-05", "2026-03-09", origin="import").collect()

    assert instrument_table(store.folder).get("XES").session_calendar().name == "XES-sessions"
    assert (store.folder / "instruments" / "XES.json").is_file()
    assert bars.get_column("contract").unique().to_list() == ["XESH2026"]
    assert bars.group_by("trade_date").len().sort("trade_date").rows() == [
        (date(2026, 3, 6), 276),
        (date(2026, 3, 9), 276),
    ]


def test_a_second_import_of_a_new_product_keeps_its_saved_instrument(tmp_path: Path) -> None:
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())
    imported(tmp_path, request)
    saved = (tmp_path / "data" / "instruments" / "XES.json").read_bytes()
    again = request.path.with_name("XESH2026 again, 5.csv")
    again.write_bytes(request.path.read_bytes() + b"\n")

    imported(tmp_path, FileImportRequest(path=again, profile=a_new_product_profile()))

    assert (tmp_path / "data" / "instruments" / "XES.json").read_bytes() == saved


def test_a_continuous_back_adjusted_file_is_one_synthetic_contract_that_warns_on_every_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = PRESETS["tradingview"].model_copy(
        update={
            "name": "es-back-adjusted",
            "series": SeriesKind.CONTINUOUS_BACK_ADJUSTED,
            "instrument": "ES",
            "contract_in_file_name": None,
        }
    )
    store = imported(tmp_path, FileImportRequest(path=SAMPLES["tradingview"][0], profile=profile))
    dataset = minutes_of("tradingview").dataset
    monkeypatch.setenv("FEFAT_DATA_DIR", str(store.folder))
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path))

    with pytest.warns(UserWarning, match="back-adjusted prices distort price levels"):
        bars = load("ES", "1m", "2026-03-06", "2026-03-06").collect()
    with pytest.warns(UserWarning, match="back-adjusted prices distort price levels"):
        load("ES", "1m", "2026-03-09", "2026-03-09")

    assert store.dataset_metadata(dataset).series is SeriesKind.CONTINUOUS_BACK_ADJUSTED
    assert [file.partition.contract for file in store.list_partitions()] == ["ES-CONTINUOUS"]
    assert bars.get_column("contract").unique().to_list() == ["ES-CONTINUOUS"]
    assert not bars.get_column("roll_flag").any()
    assert bars.get_column("close_raw").null_count() == bars.height
    assert bars.get_column("adj_offset").null_count() == bars.height
    with pytest.raises(ValueError, match="Expected continuous=False or no continuous"):
        load("ES", "1m", "2026-03-06", "2026-03-06", continuous=True)


def test_a_preview_writes_nothing_to_the_data_folder(tmp_path: Path) -> None:
    data_folder = tmp_path / "data"
    data_folder.mkdir()
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())

    preview = preview_file(request, instrument_table(data_folder), tmp_path / "cache")

    assert store_files(data_folder) == {}
    assert "nothing was written" in preview.summary()
    assert preview.first_rows[0].startswith("    2026-03-04T23:00:00Z to 2026-03-04T23:05:00Z")
    assert not any("could not check" in warning for warning in preview.reading.warnings)


def test_a_re_import_changes_nothing(tmp_path: Path) -> None:
    store = imported(tmp_path, sample_request("ninjatrader"))
    before = store_files(store.folder)

    report = import_file(
        sample_request("ninjatrader"),
        store,
        tmp_path / "cache",
        imported_on=date(2026, 10, 21),
        instruments=STATIC_TABLE,
    )

    assert isinstance(report, AlreadyImported)
    assert report.summary().startswith("Nothing to import from")
    assert store_files(store.folder) == before


def test_a_catalog_product_that_several_providers_hold_loads_from_its_recommended_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The catalog recommends Interactive Brokers for MES, after vendors this store lacks, and
    # not TradingView, so IBKR's dataset is read: its bars carry their trade counts.
    imported(tmp_path, sample_request("ibkr", contract="MESH2026"))
    imported(tmp_path, sample_request("tradingview", contract="MESH2026"))
    monkeypatch.setenv("FEFAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path))

    bars = load("MES", "1m", "2026-03-06", "2026-03-06", continuous=False).collect()

    traded = bars.filter(~pl.col("zero_volume"))
    assert traded.height > 0 and traded.get_column("trade_count").null_count() == 0
    with pytest.raises(ValueError, match="Expected one provider of MES in the store, got none"):
        load("MES", "1m", "2026-03-06", "2026-03-06", origin="sync")
    with pytest.raises(ValueError, match="Expected an origin of import, sync, got 'mine'"):
        load("MES", "1m", "2026-03-06", "2026-03-06", origin="mine")


def test_imported_and_other_datasets_of_one_root_are_kept_apart(tmp_path: Path) -> None:
    store = imported(tmp_path, sample_request("ninjatrader"))
    imported(tmp_path, sample_request("tradingview"))

    assert {dataset.provider for dataset in store.list_datasets()} == {"ninjatrader", "tradingview"}


@pytest.mark.parametrize("packing", ["zip", "gz", "crlf"])
def test_a_zipped_gzipped_or_crlf_sample_imports_to_the_same_frame(
    tmp_path: Path, packing: str
) -> None:
    path, _ = SAMPLES["tradingview"]
    packed = tmp_path / "exports" / f"{path.name}.{packing}"
    packed.parent.mkdir()
    if packing == "zip":
        with zipfile.ZipFile(packed, "w") as archive:
            archive.write(path, path.name)
    if packing == "gz":
        packed.write_bytes(gzip.compress(path.read_bytes()))
    if packing == "crlf":
        packed = packed.with_name(path.name)
        packed.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    store = imported(tmp_path, sample_request("tradingview", path=packed))

    stored = store.scan_partition(minutes_of("tradingview")).collect()
    assert_frame_equal(stored, expected_minutes("tradingview"))


def test_rows_that_cannot_be_read_are_problems_that_refuse_the_import(tmp_path: Path) -> None:
    lines = SAMPLES["ninjatrader"][0].read_bytes().decode().splitlines()
    lines[2] = "2026-03-04 23:03;6849.5;6849.5;6849.5;6849.5;14"
    lines[3] = "20260304 230400;6849.6;6849.75;6849.5;6849.75;7"
    lines[4] = "20260304 230500;6849.75;6849.75;6849.5;6849.5;2.5"
    broken = tmp_path / "ES 03-26.Last.txt"
    broken.write_bytes("\n".join(lines).encode())
    request = sample_request("ninjatrader", path=broken)

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    kinds = [problem.split(",")[0] for problem in preview.reading.problems]
    assert kinds == [
        ProblemKind.UNREADABLE_TIMESTAMP,
        ProblemKind.OFF_THE_TICK,
        ProblemKind.PART_VOLUME,
    ]
    assert "the first is data row 3, '2026-03-04 23:03;" in preview.reading.problems[0]
    with pytest.raises(ValueError, match="Nothing was written"):
        imported(tmp_path, request)


def test_coarser_bars_read_with_a_finer_profile_are_refused(tmp_path: Path) -> None:
    profile = a_new_product_profile().model_copy(
        update={"timeframe": Timeframe(count=1, unit=TimeUnit.MINUTE)}
    )
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=profile)

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    assert any(problem.startswith("other-timeframe") for problem in preview.reading.problems)


def test_a_databento_trades_export_imports_its_ticks(tmp_path: Path) -> None:
    trades = pl.read_parquet(ESH2026_MARCH_6_TRADES)
    lines = [
        "ts_recv,ts_event,rtype,publisher_id,instrument_id,action,side,depth,price,size,flags,"
        "ts_in_delta,sequence,symbol",
        *(
            f"{row['ts_recv']},{row['ts_event']},0,1,1001,T,{row['side']},0,{row['price']},"
            f"{row['size']},0,0,{row['sequence']},ESH6"
            for row in trades.iter_rows(named=True)
        ),
    ]
    path = tmp_path / "glbx-mdp3-20260306.trades.csv"
    path.write_bytes(("\n".join(lines) + "\n").encode())
    profile = ImportProfile.model_validate(
        {
            **PRESETS["databento-csv"].model_dump(),
            "name": "databento-trades",
            "timeframe": "ticks",
            "columns": {
                "timestamp": "ts_recv",
                "ticks": {
                    "price": "price",
                    "size": "size",
                    "side": "side",
                    "event_time": "ts_event",
                    "sequence": "sequence",
                },
                "instrument_id": "instrument_id",
                "symbol": "symbol",
            },
        }
    )

    store = imported(tmp_path, FileImportRequest(path=path, profile=profile))

    dataset = Dataset(provider="databento-csv", schema_name=parse_schema_name("trades"), root="ES")
    partition = Partition(dataset=dataset, contract="ESH2026", key=date(2026, 3, 6))
    assert_frame_equal(store.scan_partition(partition).collect(), trades)


def test_a_spot_pair_named_by_its_root_imports_as_its_one_contract(tmp_path: Path) -> None:
    # A product that never expires has no contract to name, so its records are the root's. On
    # a calendar without breaks, the calendar check cannot test the file's timing.
    path = written_export(
        tmp_path / "exports", "BINANCE_ETHUSDT, 1.csv", sample_lines("tradingview")
    )
    store = Store(tmp_path / "data")

    report = import_file(
        sample_request("tradingview", path=path, root="ETHUSDT"),
        store,
        tmp_path / "cache",
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
    )

    assert [file.partition.contract for file in store.list_partitions()] == ["ETHUSDT"]
    assert isinstance(report, FileImportReport)
    assert any("could not check" in warning for warning in report.reading.warnings)


def test_an_hourly_bar_at_an_early_close_ends_at_the_close(tmp_path: Path) -> None:
    # The day after Thanksgiving, CME's equity session closes at 12:15 Chicago time: the bar
    # opening at 12:00 is the bucket from 12:00 to the close, as the bar builder cuts it.
    session = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path / "cache").session(
        date(2026, 11, 27)
    )
    rows = [
        f"{instant // 1_000_000_000},6850,6851,6849.75,6850.5,10"
        for instant in range(session.open, session.close, HOUR)
    ]
    path = written_export(
        tmp_path / "exports",
        "CME_MINI_ESZ2026, 60.csv",
        ["time,open,high,low,close,Volume", *rows],
    )
    profile = PRESETS["tradingview"].model_copy(
        update={"name": "tradingview-hourly", "timeframe": Timeframe(count=1, unit=TimeUnit.HOUR)}
    )

    store = imported(tmp_path, FileImportRequest(path=path, profile=profile))

    [stored] = [store.scan_partition(file.partition).collect() for file in store.list_partitions()]
    last = stored.row(-1, named=True)
    assert (last["ts_open"], last["ts_close"]) == (session.close - 15 * MINUTE, session.close)


def test_an_ibkr_average_with_more_decimals_than_the_store_keeps_is_cut_to_them(
    tmp_path: Path,
) -> None:
    # The TWS API writes the average as a float, with more digits than the nine decimals the
    # store keeps: the first row's are cut after the ninth.
    header, first, *rows = sample_lines("ibkr")
    fields = first.split(",")
    whole, _, part = fields[6].partition(".")
    fields[6] = f"{whole}.{part.ljust(9, '0')}000033"
    path = written_export(
        tmp_path / "exports", "ESH2026-1min.csv", [header, ",".join(fields), *rows]
    )

    store = imported(tmp_path, sample_request("ibkr", path=path))

    stored = store.scan_partition(minutes_of("ibkr")).collect()
    assert_frame_equal(stored, expected_minutes("ibkr"))


def test_a_continuous_series_takes_instrument_id_1_whatever_ids_its_file_gives(
    tmp_path: Path,
) -> None:
    path = written_export(
        tmp_path / "exports",
        "glbx-mdp3-20260304-20260309.ohlcv-1m.csv",
        rolled_databento_lines(),
    )
    profile = PRESETS["databento-csv"].model_copy(
        update={"name": "es-continuous-csv", "series": SeriesKind.CONTINUOUS, "instrument": "ES"}
    )

    store = imported(tmp_path, FileImportRequest(path=path, profile=profile))

    [partition] = [file.partition for file in store.list_partitions()]
    instrument_ids = store.scan_partition(partition).collect().get_column("instrument_id")
    assert (partition.contract, instrument_ids.unique().to_list()) == ("ES-CONTINUOUS", [1])


def databento_parquet(folder: Path, *, empty_close_in_row: int | None = None) -> Path:
    """The Databento sample as its Parquet export writes it, with typed columns and instants in
    UTC, and, where `empty_close_in_row` names a row, no close in that row."""
    table = pl.read_csv(SAMPLES["databento-csv"][0], infer_schema=False).with_columns(
        pl.col("ts_event").str.to_datetime(
            "%Y-%m-%dT%H:%M:%S%.fZ", time_unit="ns", time_zone="UTC"
        ),
        pl.col("rtype").cast(pl.UInt8),
        pl.col("publisher_id").cast(pl.UInt16),
        pl.col("instrument_id").cast(pl.UInt32),
        pl.col("open", "high", "low", "close").cast(pl.Float64),
        pl.col("volume").cast(pl.UInt64),
    )
    if empty_close_in_row is not None:
        emptied = pl.int_range(pl.len()) == empty_close_in_row
        table = table.with_columns(close=pl.when(~emptied).then(pl.col("close")))
    path = folder / "exports" / "glbx-mdp3-20260304-20260309.ohlcv-1m.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    table.write_parquet(path)
    return path


def test_a_parquet_export_imports_to_the_same_frame(tmp_path: Path) -> None:
    request = sample_request("databento-csv", path=databento_parquet(tmp_path))

    store = imported(tmp_path, request)

    stored = store.scan_partition(minutes_of("databento-csv")).collect()
    assert_frame_equal(stored, expected_minutes("databento-csv"))


def test_an_empty_value_in_a_parquet_export_is_a_problem(tmp_path: Path) -> None:
    request = sample_request(
        "databento-csv", path=databento_parquet(tmp_path, empty_close_in_row=0)
    )

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    assert preview.reading.problems[0].startswith("unreadable-value, 1 row: ")


def test_a_symbol_seen_ten_years_apart_names_a_contract_in_each_decade(tmp_path: Path) -> None:
    # ESH6 names the March contract of 2016 and of 2026: each run of its rows is dated alone.
    rows = [
        f"{day}T15:00:00.000000000Z,33,1,{instrument_id},6850.25,6850.25,6850.25,6850.25,1,ESH6"
        for day, instrument_id in (("2016-03-01", 1001), ("2026-03-02", 1002))
    ]
    path = written_export(
        tmp_path / "exports",
        "glbx-mdp3-20160301-20260302.ohlcv-1m.csv",
        [sample_lines("databento-csv")[0], *rows],
    )

    preview = preview_file(
        sample_request("databento-csv", path=path), STATIC_TABLE, tmp_path / "cache"
    )

    assert preview.reading.contracts == ("ESH2016", "ESH2026")


@pytest.mark.parametrize("preset", SAMPLES)
def test_the_records_of_a_files_first_half_are_those_the_whole_file_gives_them(
    tmp_path: Path, preset: str
) -> None:
    # No look-ahead inside a file (D-12): a record never depends on the rows after it.
    path, time_zone = SAMPLES[preset]
    lines = path.read_bytes().splitlines(keepends=True)
    prefix = tmp_path / path.name
    prefix.write_bytes(b"".join(lines[: len(lines) // 2]))

    def records_of(file: Path) -> pl.DataFrame:
        name, table = read_table(file, file.read_bytes(), PRESETS[preset].layout)
        facts = ImportFacts(file_name=name, contract=None, root=None, time_zone=time_zone)
        mapped = mapped_records(table, PRESETS[preset], facts, STATIC_TABLE, tmp_path / "cache")
        return mapped.records

    cut = records_of(prefix)
    whole = records_of(path).filter(pl.col("ts_close") <= cut.get_column("ts_close").max())
    assert_frame_equal(cut, whole)


def test_a_close_stamped_hourly_bar_straddling_an_early_close_goes_in_the_cut_bucket(
    tmp_path: Path,
) -> None:
    # The same session from a platform that stamps each bar at its nominal end and does not cut
    # at the early close: its last bar, stamped 13:00 Chicago time, holds the prints from 12:00
    # to the 12:15 close and goes in the bar builder's cut bucket, not in the break after it.
    session = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path / "cache").session(
        date(2026, 11, 27)
    )
    rows = [
        f"{datetime.fromtimestamp(instant // 1_000_000_000, UTC):%Y%m%d %H%M%S}"
        ";6850;6851;6849.75;6850.5;10"
        for instant in range(session.open + HOUR, session.close + HOUR, HOUR)
    ]
    path = written_export(tmp_path / "exports", "ES 12-26.Last.txt", rows)
    profile = PRESETS["ninjatrader"].model_copy(
        update={"name": "ninjatrader-hourly", "timeframe": Timeframe(count=1, unit=TimeUnit.HOUR)}
    )

    store = imported(tmp_path, FileImportRequest(path=path, profile=profile))

    [stored] = [store.scan_partition(file.partition).collect() for file in store.list_partitions()]
    assert stored.height == len(rows)
    last = stored.row(-1, named=True)
    assert (last["ts_open"], last["ts_close"]) == (session.close - 15 * MINUTE, session.close)


def test_a_file_imported_before_with_other_arguments_is_refused_not_passed_over(
    tmp_path: Path,
) -> None:
    # A re-import with a corrected time zone must not pass as "already imported": the stored
    # dataset would keep the wrong records, since a store merges and rewrites nothing.
    store = imported(tmp_path, sample_request("tradestation"))
    before = store_files(store.folder)

    with pytest.raises(ValueError, match="imported as it was"):
        import_file(
            sample_request("tradestation", time_zone="America/New_York"),
            store,
            tmp_path / "cache",
            imported_on=date(2026, 10, 21),
            instruments=STATIC_TABLE,
        )

    assert store_files(store.folder) == before


def test_a_twelve_hour_clock_with_am_and_pm_keeps_its_time_of_day(tmp_path: Path) -> None:
    # An export saved through a spreadsheet writes `06:00:00 PM`: a pattern with `%I` and `%p`
    # names a time of day as `%H` does, and must not be read as a date alone.
    header, *rows = sample_lines("ibkr")
    twelve_hour = []
    for row in rows:
        stamp, _, rest = row.partition(",")
        clock = datetime.strptime(stamp[:17], "%Y%m%d %H:%M:%S").strftime("%Y%m%d %I:%M:%S %p")
        twelve_hour.append(f"{clock}{stamp[17:]},{rest}")
    path = written_export(tmp_path / "exports", "ESH2026-1min.csv", [header, *twelve_hour])
    timestamp = PRESETS["ibkr"].timestamp.model_copy(update={"format": "%Y%m%d %I:%M:%S %p"})
    profile = PRESETS["ibkr"].model_copy(update={"name": "ibkr-12h", "timestamp": timestamp})

    preview = preview_file(
        sample_request("ibkr", path=path, profile=profile), STATIC_TABLE, tmp_path / "cache"
    )

    assert preview.reading.problems == ()
    assert preview.reading.records == len(rows)
