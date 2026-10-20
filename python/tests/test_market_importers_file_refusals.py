"""Files the file importer refuses, or reads with a problem or a warning (step 1.10): records it
cannot place in time, products it cannot name, Databento's daily bars, times written in another
zone than the import's, and timing the calendar check cannot test."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from export_samples import (
    ESH2026_MINUTES,
    PRESETS,
    XES,
    a_new_product_profile,
    five_minute_file,
    imported,
    rolled_databento_lines,
    sample_lines,
    sample_request,
    store_files,
    written_export,
)
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.importers.file_import import FileImportRequest, preview_file
from fefat.market.importers.profiles import BarStamp
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import Dataset, DatasetMetadata, DatasetOrigin, SeriesKind, SizeUnit
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name
from fefat.market.store import Store


@pytest.mark.parametrize(
    ("preset", "name", "lines", "refusal"),
    [
        (
            "ninjatrader",
            "ES 03-26.Last.txt",
            [f"XX{line}" for line in sample_lines("ninjatrader")],
            "got none:\n  unreadable-timestamp, 4,141 rows: ",
        ),
        (
            "ninjatrader",
            "ES 03-26.Last.txt",
            [],
            "Expected rows in ES 03-26.Last.txt, got an empty",
        ),
        (
            "tradingview",
            "CME_MINI_ESH2026, 1.csv",
            ["time,open,high,low,close,Volume"],
            "got none: no data rows, or only bars without volume",
        ),
    ],
    ids=["unreadable", "empty", "header-only"],
)
def test_a_file_that_leaves_no_record_is_refused_with_the_problems_of_its_rows(
    tmp_path: Path, preset: str, name: str, lines: list[str], refusal: str
) -> None:
    request = sample_request(preset, path=written_export(tmp_path, name, lines))

    with pytest.raises(ValueError, match=re.escape(refusal)):
        preview_file(request, STATIC_TABLE, tmp_path / "cache")


def test_a_timestamp_outside_the_calendars_sessions_is_a_problem(tmp_path: Path) -> None:
    # A wrong century, or Unix seconds read as milliseconds, falls outside the session table.
    first, *rows = sample_lines("ninjatrader")
    path = written_export(tmp_path, "ES 03-26.Last.txt", [f"1990{first[4:]}", *rows])

    preview = preview_file(
        sample_request("ninjatrader", path=path), STATIC_TABLE, tmp_path / "cache"
    )

    assert preview.reading.problems[0].startswith("outside-the-calendar, 1 row: ")
    assert "It would be refused" in preview.summary()


def test_a_futures_file_that_names_no_contract_is_refused(tmp_path: Path) -> None:
    # TradingView names its continuous chart ES1!, no contract: a futures product's records
    # need one, or a profile of a continuous series.
    path = written_export(tmp_path, "CME_MINI_ES1!, 1.csv", sample_lines("tradingview"))
    request = sample_request("tradingview", path=path, root="ES")

    with pytest.raises(ValueError, match="or import it with a profile of series continuous"):
        preview_file(request, STATIC_TABLE, tmp_path / "cache")


def test_an_impossible_month_in_a_file_name_is_refused(tmp_path: Path) -> None:
    path = written_export(tmp_path, "ES 13-26.Last.txt", sample_lines("ninjatrader"))
    refusal = "Expected a month from 1 to 12 in ES 13-26.Last.txt, got '13'."

    with pytest.raises(ValueError, match=re.escape(refusal)):
        preview_file(sample_request("ninjatrader", path=path), STATIC_TABLE, tmp_path / "cache")


def test_a_contract_with_several_instrument_ids_is_refused(tmp_path: Path) -> None:
    path = written_export(
        tmp_path, "glbx-mdp3-20260304-20260309.ohlcv-1m.csv", rolled_databento_lines()
    )

    with pytest.raises(ValueError, match="the contract ESH2026 with more than one instrument_id"):
        preview_file(sample_request("databento-csv", path=path), STATIC_TABLE, tmp_path / "cache")


def test_a_refused_import_of_a_new_product_saves_no_instrument(tmp_path: Path) -> None:
    # The store holds a continuous series of XES, which dated contracts never join.
    store = Store(tmp_path / "data")
    dataset = Dataset(provider="tradingview", schema_name=parse_schema_name("ohlcv-5m"), root="XES")
    store.write_dataset_metadata(
        dataset,
        DatasetMetadata(
            size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
            origin=DatasetOrigin.IMPORT,
            licence_scope="Synthetic test data; no licence applies",
            series=SeriesKind.CONTINUOUS,
        ),
    )
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())

    with pytest.raises(ValueError, match="Expected a continuous series"):
        imported(tmp_path, request)

    assert not (store.folder / "instruments").exists()


def test_a_profile_that_gives_a_saved_product_another_specification_writes_nothing(
    tmp_path: Path,
) -> None:
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())
    store = imported(tmp_path, request)
    before = store_files(store.folder)
    again = written_export(
        tmp_path / "exports",
        "XESH2026 again, 5.csv",
        request.path.read_bytes().decode().splitlines(),
    )
    other = a_new_product_profile(XES.model_copy(update={"point_value": Decimal(100)}))

    with pytest.raises(ValueError, match="Expected the specification of XES that the store holds"):
        imported(tmp_path, FileImportRequest(path=again, profile=other))

    assert store_files(store.folder) == before


def test_ibkr_times_in_another_zone_than_the_imports_are_refused(tmp_path: Path) -> None:
    # The TWS API writes its login's zone after each time, US/Eastern in the sample.
    request = sample_request("ibkr", time_zone="America/Chicago")

    with pytest.raises(ValueError, match="name --time-zone US/Eastern"):
        preview_file(request, STATIC_TABLE, tmp_path / "cache")


def test_databento_daily_bars_are_refused_as_another_record_type(tmp_path: Path) -> None:
    # Databento's ohlcv-1d bars, rtype 35, run 00:00 to 24:00 UTC, which is no session (02 §1.1).
    day = pl.from_epoch("ts_open", time_unit="ns").dt.date().alias("day")
    days = (
        pl.read_parquet(ESH2026_MINUTES)
        .sort("ts_open")
        .group_by(day, maintain_order=True)
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
        .filter(pl.col("day").dt.weekday() <= 5)
    )
    rows = [
        f"{bar['day']}T00:00:00.000000000Z,35,1,1001,{bar['open']},{bar['high']},"
        f"{bar['low']},{bar['close']},{bar['volume']},ESH6"
        for bar in days.iter_rows(named=True)
    ]
    path = written_export(
        tmp_path,
        "glbx-mdp3-20260304-20260309.ohlcv-1d.csv",
        [sample_lines("databento-csv")[0], *rows],
    )
    profile = PRESETS["databento-csv"].model_copy(
        update={"name": "databento-daily", "timeframe": Timeframe(count=1, unit=TimeUnit.DAY)}
    )

    with pytest.raises(ValueError, match="other-record-type, 4 rows"):
        preview_file(
            FileImportRequest(path=path, profile=profile), STATIC_TABLE, tmp_path / "cache"
        )


@pytest.mark.parametrize(
    ("stamped_at", "problems"),
    [("date", []), ("open", ["off-the-buckets, 3 rows"]), ("close", [])],
)
def test_a_daily_bar_is_dated_by_its_session_and_refused_at_a_time_of_day(
    tmp_path: Path, stamped_at: str, problems: list[str]
) -> None:
    # A daily bar names its session by its date, or by its close where the profile stamps the
    # close. One stamped at another time of day, such as its session's open on the evening
    # before, would take the wrong day's session.
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path / "cache")
    closes = sessions.between(date(2026, 3, 5), date(2026, 3, 9)).select(
        "trade_date", session_close="close"
    )
    days = (
        pl.read_parquet(ESH2026_MINUTES)
        .sort("ts_open")
        .group_by("trade_date", maintain_order=True)
        .agg(
            pl.col("ts_open").first(),
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
        .join(closes, on="trade_date", maintain_order="left")
    )
    stamps = {
        "date": pl.col("trade_date").cast(pl.Datetime("ns")).dt.epoch("s"),
        "open": pl.col("ts_open") // 1_000_000_000,
        "close": pl.col("session_close") // 1_000_000_000,
    }
    bars = days.select(
        stamps[stamped_at].alias("time"), pl.col("open", "high", "low", "close") / 1e9, "volume"
    )
    lines = [",".join(str(value) for value in bar) for bar in bars.iter_rows()]
    path = written_export(
        tmp_path, "CME_MINI_ESH2026, 1D.csv", ["time,open,high,low,close,Volume", *lines]
    )
    stamp = BarStamp.CLOSE if stamped_at == "close" else BarStamp.OPEN
    profile = PRESETS["tradingview"].model_copy(
        update={
            "name": "tradingview-daily",
            "timeframe": Timeframe(count=1, unit=TimeUnit.DAY),
            "timestamp": PRESETS["tradingview"].timestamp.model_copy(update={"stamp": stamp}),
        }
    )

    preview = preview_file(
        FileImportRequest(path=path, profile=profile), STATIC_TABLE, tmp_path / "cache"
    )

    assert [problem.split(":")[0] for problem in preview.reading.problems] == problems


def test_regular_hours_bars_whose_timing_the_calendar_cannot_check_are_warned_of(
    tmp_path: Path,
) -> None:
    # TradeStation's sample is in Chicago time; read as New York's, its regular-hours bars,
    # closing 08:31 to 15:00, run an hour early and never leave the Globex session.
    header, *rows = sample_lines("tradestation")
    regular = [row for row in rows if 831 <= int(row.split(",")[1]) <= 1500]
    path = written_export(tmp_path, "ESH26.txt", [header, *regular])
    request = sample_request("tradestation", path=path, time_zone="America/New_York")

    preview = preview_file(request, STATIC_TABLE, tmp_path / "cache")

    assert preview.reading.calendar.offsets == ()
    assert any("could not check" in warning for warning in preview.reading.warnings)
