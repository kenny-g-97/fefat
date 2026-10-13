from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from databento_dbn import (
    F_BAD_TS_RECV,
    F_LAST,
    UNDEF_ORDER_SIZE,
    UNDEF_PRICE,
    UNDEF_STAT_QUANTITY,
    UNDEF_TIMESTAMP,
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
    SType,
    TradeMsg,
)
from polars.testing import assert_frame_equal

from dbn_files import NANOSECONDS_PER_MINUTE, dbn_content, mapping, utc, write_dbn
from fefat.market.contracts import SYMBOLOGY_COLUMNS
from fefat.market.importers.dbn import DbnMetadata, read_dbn
from fefat.market.schema import parse_schema_name, polars_schema

ONE_MINUTE = int(RType.from_str("ohlcv-1m"))
ONE_SECOND = int(RType.from_str("ohlcv-1s"))
TRADE = Action("T")
BUYER = Side("B")
NO_AGGRESSOR = Side("N")
FUTURE = InstrumentClass("F")
SPREAD = InstrumentClass("S")
ADDED = SecurityUpdateAction("A")
SETTLEMENT_PRICE = StatType(3)
OPEN_INTEREST = StatType(9)
NEW_VALUE = StatUpdateAction(1)
# 09:30 CDT on Monday 2026-03-09, inside the session of that trade date.
MONDAY = utc(2026, 3, 9, 14, 30)
MAPPINGS = [
    mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21)),
    mapping("ESH6-ESM6", 1002, date(2025, 12, 12), date(2026, 3, 21)),
]
MINUTE_BARS = [
    OHLCVMsg(ONE_MINUTE, 1, 1001, MONDAY, 6_750_000_000_000, 6_751_250_000_000, 6_749_500_000_000, 6_750_500_000_000, 42),
    OHLCVMsg(ONE_MINUTE, 1, 1002, MONDAY, -45_250_000_000, -45_000_000_000, -45_250_000_000, -45_000_000_000, 3),
    OHLCVMsg(ONE_MINUTE, 1, 1001, MONDAY + NANOSECONDS_PER_MINUTE, 6_750_500_000_000, 6_752_000_000_000, 6_750_250_000_000, 6_751_750_000_000, 17),
]  # fmt: skip
RAW_BAR_COLUMNS = {
    "ts_event": pl.Int64,
    "instrument_id": pl.UInt32,
    "open": pl.Int64,
    "high": pl.Int64,
    "low": pl.Int64,
    "close": pl.Int64,
    "volume": pl.UInt64,
}
EXPECTED_BARS = pl.DataFrame(
    {
        "ts_event": [MONDAY, MONDAY, MONDAY + NANOSECONDS_PER_MINUTE],
        "instrument_id": [1001, 1002, 1001],
        "open": [6_750_000_000_000, -45_250_000_000, 6_750_500_000_000],
        "high": [6_751_250_000_000, -45_000_000_000, 6_752_000_000_000],
        "low": [6_749_500_000_000, -45_250_000_000, 6_750_250_000_000],
        "close": [6_750_500_000_000, -45_000_000_000, 6_751_750_000_000],
        "volume": [42, 3, 17],
    },
    schema=RAW_BAR_COLUMNS,
)


def minute_bars_file(folder: Path, name: str = "bars.ohlcv-1m.dbn") -> Path:
    return write_dbn(folder / name, dbn_content(Schema("ohlcv-1m"), MAPPINGS, MINUTE_BARS))


def frames_of(path: Path, chunk_bytes: int = 8_000_000) -> tuple[DbnMetadata, pl.DataFrame]:
    metadata, frames = read_dbn(path, chunk_bytes)
    return metadata, pl.concat(list(frames))


def test_a_file_gives_its_metadata_then_its_records_as_columns(tmp_path: Path) -> None:
    metadata, bars = frames_of(minute_bars_file(tmp_path))

    expected_symbology = pl.DataFrame(
        [
            ("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21)),
            ("ESH6-ESM6", 1002, date(2025, 12, 12), date(2026, 3, 21)),
        ],
        schema=SYMBOLOGY_COLUMNS,
        orient="row",
    )
    assert (metadata.dataset, metadata.schema_name, metadata.version) == (
        "GLBX.MDP3",
        parse_schema_name("ohlcv-1m"),
        3,
    )
    assert_frame_equal(metadata.symbology.sort("raw_symbol"), expected_symbology)
    assert_frame_equal(bars, EXPECTED_BARS)


def test_a_file_of_an_older_dbn_version_gives_that_version_and_its_records_upgraded(
    tmp_path: Path,
) -> None:
    content = dbn_content(Schema("ohlcv-1m"), MAPPINGS, MINUTE_BARS, version=2)
    path = write_dbn(tmp_path / "bars.dbn", content)

    metadata, bars = frames_of(path)

    assert content[:4] == b"DBN"
    assert metadata.version == 2
    assert_frame_equal(bars, EXPECTED_BARS)


def test_a_file_streams_in_chunks_that_split_records(tmp_path: Path) -> None:
    # 100 bytes split the header and every 56-byte bar, so the decoder must carry the partial
    # record into the next chunk: the 873 MB file on this PC is read the same way, 8 MB at a time.
    _, bars = frames_of(minute_bars_file(tmp_path), chunk_bytes=100)

    assert_frame_equal(bars, EXPECTED_BARS)


def test_a_zstd_file_reads_like_the_plain_one(tmp_path: Path) -> None:
    _, bars = frames_of(minute_bars_file(tmp_path, "bars.ohlcv-1m.dbn.zst"))

    assert_frame_equal(bars, EXPECTED_BARS)


def tbbo_record(**fields: Any) -> MBP1Msg:
    """A TBBO record: the decoder's stub types `levels` as a list, while it takes one pair."""
    return MBP1Msg(**fields)


TRADES = [
    TradeMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, price=6_750_250_000_000, size=2, action=TRADE, side=BUYER, depth=0, ts_recv=MONDAY + 50_000, flags=F_LAST, sequence=11),
    TradeMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY + 1, price=UNDEF_PRICE, size=UNDEF_ORDER_SIZE, action=TRADE, side=NO_AGGRESSOR, depth=0, ts_recv=MONDAY + 60_000, flags=F_LAST | F_BAD_TS_RECV, sequence=12),
]  # fmt: skip
TRADE_COLUMNS: dict[str, list[Any]] = {
    "ts_recv": [MONDAY + 50_000, MONDAY + 60_000],
    "ts_event": [MONDAY, MONDAY + 1],
    "instrument_id": [1001, 1001],
    "price": [6_750_250_000_000, None],
    "size": [2, None],
    "side": ["B", "N"],
    "sequence": [11, 12],
}
TBBO = [
    tbbo_record(publisher_id=1, instrument_id=1001, ts_event=MONDAY, price=6_750_250_000_000, size=2, action=TRADE, side=BUYER, depth=0, ts_recv=MONDAY + 50_000, flags=F_LAST, sequence=11, levels=BidAskPair(bid_px=6_750_000_000_000, ask_px=6_750_250_000_000, bid_sz=8, ask_sz=1)),
    tbbo_record(publisher_id=1, instrument_id=1001, ts_event=MONDAY + 1, price=UNDEF_PRICE, size=UNDEF_ORDER_SIZE, action=TRADE, side=NO_AGGRESSOR, depth=0, ts_recv=MONDAY + 60_000, flags=F_LAST | F_BAD_TS_RECV, sequence=12, levels=BidAskPair(bid_px=6_750_000_000_000, ask_px=UNDEF_PRICE, bid_sz=9, ask_sz=0)),
]  # fmt: skip
DEFINITIONS = [
    InstrumentDefMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, ts_recv=MONDAY + 1, min_price_increment=250_000_000, display_factor=1_000_000_000, raw_symbol="ESH6", asset="ES", security_type="FUT", instrument_class=FUTURE, security_update_action=ADDED, expiration=utc(2026, 3, 20, 13, 30), activation=utc(2025, 3, 21, 22), unit_of_measure_qty=50_000_000_000, maturity_year=2026, maturity_month=3, currency="USD", exchange="XCME", unit_of_measure="IPNT"),
    InstrumentDefMsg(publisher_id=1, instrument_id=1002, ts_event=MONDAY, ts_recv=MONDAY + 2, min_price_increment=UNDEF_PRICE, display_factor=1_000_000_000, raw_symbol="ESH6-ESM6", asset="ES", security_type="", instrument_class=SPREAD, security_update_action=ADDED),
]  # fmt: skip
STATISTICS = [
    StatMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, ts_recv=MONDAY + 3, ts_ref=utc(2026, 3, 9), price=6_751_000_000_000, quantity=UNDEF_STAT_QUANTITY, stat_type=SETTLEMENT_PRICE, sequence=21, update_action=NEW_VALUE, stat_flags=1),
    StatMsg(publisher_id=1, instrument_id=1001, ts_event=MONDAY, ts_recv=MONDAY + 4, ts_ref=UNDEF_TIMESTAMP, price=UNDEF_PRICE, quantity=2_345_678, stat_type=OPEN_INTEREST, sequence=22, update_action=NEW_VALUE, stat_flags=0),
]  # fmt: skip


def store_columns(schema: str, **extra: type[pl.DataType]) -> pl.Schema:
    return pl.Schema({**polars_schema(parse_schema_name(schema)), **extra})


SCHEMA_CASES = [
    (
        Schema("trades"),
        TRADES,
        pl.DataFrame(
            {**TRADE_COLUMNS, "bad_ts_recv": [False, True]},
            schema=store_columns("trades", bad_ts_recv=pl.Boolean),
        ),
    ),
    (
        Schema("tbbo"),
        TBBO,
        pl.DataFrame(
            {
                **TRADE_COLUMNS,
                "bid_px_00": [6_750_000_000_000, 6_750_000_000_000],
                "ask_px_00": [6_750_250_000_000, None],
                "bid_sz_00": [8, 9],
                "ask_sz_00": [1, 0],
                "bad_ts_recv": [False, True],
            },
            schema=store_columns("tbbo", bad_ts_recv=pl.Boolean),
        ),
    ),
    (
        Schema("definition"),
        DEFINITIONS,
        pl.DataFrame(
            {
                "ts_recv": [MONDAY + 1, MONDAY + 2],
                "ts_event": [MONDAY, MONDAY],
                "instrument_id": [1001, 1002],
                "raw_symbol": ["ESH6", "ESH6-ESM6"],
                "asset": ["ES", "ES"],
                "exchange": ["XCME", None],
                "currency": ["USD", None],
                "instrument_class": ["F", "S"],
                "security_type": ["FUT", None],
                "min_price_increment": [250_000_000, None],
                "display_factor": [1_000_000_000, 1_000_000_000],
                "unit_of_measure": ["IPNT", None],
                "unit_of_measure_qty": [50_000_000_000, None],
                "expiration": [utc(2026, 3, 20, 13, 30), None],
                "activation": [utc(2025, 3, 21, 22), None],
                "maturity_year": [2026, None],
                "maturity_month": [3, None],
            },
            schema=store_columns("definitions"),
        ),
    ),
    (
        Schema("statistics"),
        STATISTICS,
        pl.DataFrame(
            {
                "ts_recv": [MONDAY + 3, MONDAY + 4],
                "ts_event": [MONDAY, MONDAY],
                "ts_ref": [utc(2026, 3, 9), None],
                "instrument_id": [1001, 1001],
                "stat_type": [3, 9],
                "price": [6_751_000_000_000, None],
                "quantity": [None, 2_345_678],
                "update_action": [1, 1],
                "stat_flags": [1, 0],
                "sequence": [21, 22],
            },
            schema=store_columns("statistics"),
        ),
    ),
]


@pytest.mark.parametrize(("schema", "records", "expected"), SCHEMA_CASES)
def test_each_schema_keeps_the_store_columns_with_undefined_values_as_null(
    tmp_path: Path, schema: Schema, records: Sequence[DBNRecord], expected: pl.DataFrame
) -> None:
    path = write_dbn(tmp_path / "records.dbn", dbn_content(schema, MAPPINGS, records))

    _, frame = frames_of(path)

    assert_frame_equal(frame, expected)


def test_a_file_without_a_symbology_to_instrument_ids_is_refused(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), [], MINUTE_BARS, stype_out=SType("instrument_id"))
    path = write_dbn(tmp_path / "bars.dbn", content)

    with pytest.raises(ValueError, match="Expected raw symbols mapped to instrument_id"):
        frames_of(path)


def test_a_record_of_another_schema_than_the_header_names_is_refused(tmp_path: Path) -> None:
    second_bar = OHLCVMsg(ONE_SECOND, 1, 1001, MONDAY, 1, 1, 1, 1, 1)
    content = dbn_content(Schema("ohlcv-1m"), MAPPINGS, [*MINUTE_BARS, second_bar])
    path = write_dbn(tmp_path / "bars.dbn", content)

    with pytest.raises(
        ValueError, match=r"Expected OHLCVMsg records of ohlcv-1m .* got a OHLCVMsg"
    ):
        frames_of(path)


def test_a_schema_the_store_does_not_hold_is_refused(tmp_path: Path) -> None:
    path = write_dbn(tmp_path / "book.dbn", dbn_content(Schema("mbp-10"), MAPPINGS, []))

    with pytest.raises(ValueError, match="got the schema mbp-10"):
        frames_of(path)


def test_a_file_cut_short_in_a_record_is_refused(tmp_path: Path) -> None:
    content = dbn_content(Schema("ohlcv-1m"), MAPPINGS, MINUTE_BARS)
    path = write_dbn(tmp_path / "bars.dbn", content[:-10])

    with pytest.raises(ValueError, match="got 46 bytes after the last one"):
        frames_of(path)


def test_a_file_that_is_not_dbn_is_refused_with_its_name(tmp_path: Path) -> None:
    path = tmp_path / "notes.dbn"
    path.write_bytes(b"ts_event,open,high,low,close\n" * 4)

    with pytest.raises(ValueError, match=r"Expected a DBN file, got .*notes\.dbn"):
        frames_of(path)
