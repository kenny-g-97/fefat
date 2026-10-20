import gzip
import zipfile
from datetime import date, time
from decimal import Decimal
from pathlib import Path, PurePosixPath

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.api import load
from fefat.market.bars import resample_bars
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import sessions_of
from fefat.market.calendar_definition import CalendarId, SessionHours, Weekday
from fefat.market.calendar_offset import CalendarOffset, OffsetCause
from fefat.market.importers.file_import import (
    FileImportRequest,
    import_file,
    preview_file,
)
from fefat.market.importers.profile_values import ProblemKind
from fefat.market.importers.profiles import (
    BarStamp,
    ImportProfile,
    NewInstrument,
    preset_profiles,
)
from fefat.market.instruments import STATIC_TABLE, Currency, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    SeriesKind,
    SizeUnit,
    YearMonth,
)
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "fixtures" / "synthetic"
EXPORTS = SYNTHETIC / "exports"
ESH2026_MINUTES = (
    SYNTHETIC / "ohlcv-1m" / "root=ES" / "contract=ESH2026" / "month=2026-03" / "part.parquet"
)
ESH2026_MARCH_6_TRADES = (
    SYNTHETIC / "trades" / "root=ES" / "contract=ESH2026" / "date=2026-03-06" / "part.parquet"
)
IMPORTED_ON = date(2026, 10, 20)
HOUR = 3_600_000_000_000
MINUTE = 60_000_000_000
PRESETS = preset_profiles()
SAMPLES = {
    "ninjatrader": (EXPORTS / "ninjatrader" / "ES 03-26.Last.txt", None),
    "tradingview": (EXPORTS / "tradingview" / "CME_MINI_ESH2026, 1.csv", None),
    "databento-csv": (
        EXPORTS / "databento-csv" / "glbx-mdp3-20260304-20260309.ohlcv-1m.csv",
        None,
    ),
    "ibkr": (EXPORTS / "ibkr" / "ESH2026-1min.csv", "America/New_York"),
    "sierra-chart": (EXPORTS / "sierra-chart" / "ESH26-CME.txt", None),
    "tradestation": (EXPORTS / "tradestation" / "ESH26.txt", "America/Chicago"),
}
"""Each preset's sample of the fixtures' ESH2026 1-minute bars, and the time zone the import
names where the preset leaves it to the import."""


def sample_request(preset: str, **changes: object) -> FileImportRequest:
    path, time_zone = SAMPLES[preset]
    request = FileImportRequest(path=path, profile=PRESETS[preset], time_zone=time_zone)
    return FileImportRequest(**{**request.__dict__, **changes})


def imported(folder: Path, request: FileImportRequest) -> Store:
    store = Store(folder / "data")
    import_file(
        request,
        store,
        folder / "cache",
        imported_on=IMPORTED_ON,
        instruments=instrument_table(store.folder),
    )
    return store


def minutes_of(provider: str) -> Partition:
    dataset = Dataset(provider=provider, schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    return Partition(dataset=dataset, contract="ESH2026", key=YearMonth(year=2026, month=3))


def expected_minutes(preset: str) -> pl.DataFrame:
    """The fixtures' ESH2026 1-minute bars as the preset's sample gives them: the vendor's
    instrument id from Databento's file, else the contract's, and the trade count and vwap
    only where the layout carries them."""
    bars = pl.read_parquet(ESH2026_MINUTES)
    instrument_id = 1001 if preset == "databento-csv" else 202603
    keeps_count = preset in ("ibkr", "sierra-chart")
    return bars.with_columns(
        instrument_id=pl.lit(instrument_id, dtype=pl.UInt32),
        trade_count=pl.col("trade_count") if keeps_count else pl.lit(None, dtype=pl.UInt32),
        vwap=pl.col("vwap") if preset == "ibkr" else pl.lit(None, dtype=pl.Int64),
    )


def store_files(folder: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in folder.rglob("*")
        if path.is_file()
    }


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
        ),
    )
    assert "It would be refused" in preview.summary()


XES_HOURS = SessionHours(
    time_zone="America/Chicago",
    opens_at=time(17, 0),
    closes_at=time(16, 0),
    opens_on_previous_day=True,
    weekdays=frozenset(
        {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
    ),
)


def a_new_product_profile() -> ImportProfile:
    """A TradingView export of 5-minute bars of XES, a product FEFAT does not know, on hours of
    its own: 17:00 to 16:00 Chicago, Monday to Friday, without holidays."""
    return PRESETS["tradingview"].model_copy(
        update={
            "name": "xes-5m",
            "timeframe": Timeframe(count=5, unit=TimeUnit.MINUTE),
            "instrument": NewInstrument(
                root="XES",
                kind=InstrumentKind.FUTURES,
                tick_size=Decimal("0.25"),
                point_value=Decimal(50),
                currency=Currency.USD,
                last_trade_rule=ThirdFriday(),
                calendar=XES_HOURS,
                first_trade_date=date(2026, 3, 2),
            ),
        }
    )


def five_minute_file(folder: Path) -> Path:
    """The fixtures' ESH2026 bars resampled to 5 minutes by the bar builder, written as
    TradingView writes a 5-minute chart of XES March 2026."""
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], folder / "cache")
    minutes = pl.read_parquet(ESH2026_MINUTES)
    five = resample_bars(minutes, Timeframe(count=5, unit=TimeUnit.MINUTE), sessions, 2**62)
    rows = [
        f"{bar['ts_open'] // 1_000_000_000},{bar['open'] / 1e9},{bar['high'] / 1e9},"
        f"{bar['low'] / 1e9},{bar['close'] / 1e9},{bar['volume']}\n"
        for bar in five.iter_rows(named=True)
    ]
    path = folder / "exports" / "XESH2026, 5.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(("time,open,high,low,close,Volume\n" + "".join(rows)).encode())
    return path


def test_a_product_with_a_new_instrument_on_a_calendar_of_its_own_loads_at_its_fidelity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())
    store = imported(tmp_path, request)
    monkeypatch.setenv("FEFAT_DATA_DIR", str(store.folder))
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path))

    with pytest.warns(UserWarning, match="finest data of XES from tradingview is 5-minute bars"):
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
    with pytest.raises(ValueError, match="Expected continuous=False or no continuous"):
        load("ES", "1m", "2026-03-06", "2026-03-06", continuous=True)


def test_a_preview_writes_nothing_to_the_data_folder(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())

    preview = preview_file(request, instrument_table(data), tmp_path / "cache")

    assert store_files(data) == {}
    assert "nothing was written" in preview.summary()
    assert preview.first_rows[0].startswith("    2026-03-04T23:00:00Z to 2026-03-04T23:05:00Z")


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

    assert report.already_imported
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
