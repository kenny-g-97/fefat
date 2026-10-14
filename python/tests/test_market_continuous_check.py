"""The roll check against a vendor's continuous mapping (step 1.7): a response of the
symbology endpoint parsed, and the fixtures' roll calendar compared with mappings that agree,
roll a session later or earlier, or name a contract the bars lack."""

import json
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.continuous import volume_rolls
from fefat.market.continuous_check import (
    VENDOR_MAPPING_COLUMNS,
    DifferenceKind,
    FrontDifference,
    compare_fronts,
    parse_databento_mapping,
)
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
MARCH_5, MARCH_6, MARCH_9, MARCH_10, MARCH_11 = (date(2026, 3, day) for day in (5, 6, 9, 10, 11))


@pytest.fixture(scope="module")
def table(tmp_path_factory: pytest.TempPathFactory) -> SessionTable:
    return sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path_factory.mktemp("cache"))


@pytest.fixture(scope="module")
def bars() -> pl.DataFrame:
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    request = PartitionRequest(dataset=dataset, start=MARCH_5, end=MARCH_9)
    return Store(ROOT / "fixtures").scan_contracts(request).collect()


def response(symbol: str, *intervals: tuple[date, date, int]) -> bytes:
    """A response of the symbology endpoint, mapping `symbol` to an instrument_id by interval."""
    result = {
        symbol: [
            {"d0": str(d0), "d1": str(d1), "s": str(instrument_id)}
            for d0, d1, instrument_id in intervals
        ]
    }
    content = {
        "result": result,
        "symbols": [symbol],
        "stype_in": "continuous",
        "stype_out": "instrument_id",
        "start_date": str(intervals[0][0]),
        "end_date": str(intervals[-1][1]),
        "partial": [],
        "not_found": [],
        "message": "OK",
        "status": 0,
    }
    return json.dumps(content).encode()


def test_a_response_of_the_symbology_endpoint_gives_its_intervals() -> None:
    content = response("ES.v.0", (MARCH_5, MARCH_9, 1001), (MARCH_9, MARCH_11, 1003))

    mapping = parse_databento_mapping(content, "ES.v.0")

    assert mapping.schema == VENDOR_MAPPING_COLUMNS
    assert mapping.rows() == [(MARCH_5, MARCH_9, 1001), (MARCH_9, MARCH_11, 1003)]


def test_a_response_without_the_symbol_or_with_a_symbol_that_is_no_id_is_refused() -> None:
    expected = "Expected ES.v.0 in the result of the symbology response, got NQ.v.0."
    with pytest.raises(ValueError, match=re.escape(expected)):
        parse_databento_mapping(response("NQ.v.0", (MARCH_5, MARCH_9, 1001)), "ES.v.0")

    content = response("ES.v.0", (MARCH_5, MARCH_9, 1001)).replace(b'"1001"', b'""')
    expected = "Expected an instrument_id for ES.v.0 from 2026-03-05 to before 2026-03-09, got ''."
    with pytest.raises(ValueError, match=re.escape(expected)):
        parse_databento_mapping(content, "ES.v.0")


def test_a_vendor_mapping_that_rolls_where_the_calendar_does_shows_no_difference(
    table: SessionTable, bars: pl.DataFrame
) -> None:
    calendar = volume_rolls(bars, table, instruments.get("ES"), table.following(MARCH_9).open)
    mapping = parse_databento_mapping(
        response("ES.v.0", (MARCH_5, MARCH_9, 1001), (MARCH_9, MARCH_11, 1003)), "ES.v.0"
    )

    comparison = compare_fronts(calendar, mapping, bars, "ES.v.0")

    assert comparison.trade_dates_compared == 3
    assert comparison.differences == ()
    assert (
        comparison.summary() == "Fronts of ES against ES.v.0: 3 trade dates compared, none differ."
    )


@pytest.mark.parametrize(
    ("vendor_rolls_on", "different_day", "ours", "theirs", "kind"),
    [
        (MARCH_10, MARCH_9, "ESM2026", "ESH2026", DifferenceKind.VENDOR_A_SESSION_LATER),
        (MARCH_6, MARCH_6, "ESH2026", "ESM2026", DifferenceKind.VENDOR_A_SESSION_EARLIER),
    ],
)
def test_a_vendor_mapping_a_session_off_lists_the_day_with_its_kind(
    table: SessionTable,
    bars: pl.DataFrame,
    vendor_rolls_on: date,
    different_day: date,
    ours: str,
    theirs: str,
    kind: DifferenceKind,
) -> None:
    calendar = volume_rolls(bars, table, instruments.get("ES"), table.following(MARCH_9).open)
    intervals = ((MARCH_5, vendor_rolls_on, 1001), (vendor_rolls_on, MARCH_11, 1003))
    mapping = parse_databento_mapping(response("ES.v.0", *intervals), "ES.v.0")

    comparison = compare_fronts(calendar, mapping, bars, "ES.v.0")

    assert comparison.differences == (
        FrontDifference(trade_date=different_day, ours=ours, vendors=theirs, kind=kind),
    )
    assert comparison.summary().splitlines() == [
        "Fronts of ES against ES.v.0: 3 trade dates compared, 1 differs.",
        f"  {different_day}: ours {ours}, ES.v.0 {theirs} ({kind})",
    ]


def test_an_instrument_the_bars_lack_is_named_by_its_id(
    table: SessionTable, bars: pl.DataFrame
) -> None:
    calendar = volume_rolls(bars, table, instruments.get("ES"), table.following(MARCH_9).open)
    intervals = ((MARCH_5, MARCH_10, 1001), (MARCH_10, MARCH_11, 1999))
    mapping = parse_databento_mapping(response("ES.v.0", *intervals), "ES.v.0")

    comparison = compare_fronts(calendar, mapping, bars, "ES.v.0")

    assert [difference.vendors for difference in comparison.differences] == [
        "ESH2026",
        "instrument_id 1999, in none of the bars",
    ]
    assert [difference.kind for difference in comparison.differences] == [
        DifferenceKind.VENDOR_A_SESSION_LATER,
        DifferenceKind.OTHER,
    ]


def test_an_instrument_id_that_names_two_contracts_in_the_bars_is_refused(
    table: SessionTable, bars: pl.DataFrame
) -> None:
    calendar = volume_rolls(bars, table, instruments.get("ES"), table.following(MARCH_9).open)
    mapping = parse_databento_mapping(response("ES.v.0", (MARCH_5, MARCH_11, 1001)), "ES.v.0")
    reused = bars.with_columns(instrument_id=pl.lit(1001, dtype=pl.UInt32))

    with pytest.raises(ValueError, match="Expected each instrument_id of the bars to name one"):
        compare_fronts(calendar, mapping, reused, "ES.v.0")
