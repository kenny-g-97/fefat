import polars as pl
import pytest

from fefat.market.schema import parse_schema_name, polars_schema

SCHEMA_NAMES = [
    "trades",
    "tbbo",
    "definitions",
    "statistics",
    "funding",
    "ohlcv-1s",
    "ohlcv-10s",
    "ohlcv-1m",
    "ohlcv-5m",
    "ohlcv-1h",
    "ohlcv-1d",
]
PRICE_COLUMNS = {
    "price",
    "open",
    "high",
    "low",
    "close",
    "bid_px_00",
    "ask_px_00",
    "min_price_increment",
}


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_a_schema_name_reads_back_as_the_folder_name_it_came_from(name: str) -> None:
    assert str(parse_schema_name(name)) == name


@pytest.mark.parametrize(
    "name", ["ohlcv", "ohlcv-0m", "ohlcv-05m", "ohlcv-1w", "Trades", "trade", "mbp-1", ""]
)
def test_a_folder_that_names_no_schema_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="Expected a schema name"):
        parse_schema_name(name)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_timestamps_are_int64_nanoseconds_and_prices_int64_units_of_1e_9(name: str) -> None:
    columns = polars_schema(parse_schema_name(name))
    timestamps = {column for column in columns if column.startswith("ts_")}
    prices = PRICE_COLUMNS & set(columns)

    assert timestamps & {"ts_recv", "ts_open"}
    assert all(columns[column] == pl.Int64 for column in timestamps | prices)


def test_bars_of_every_timeframe_share_one_schema_with_their_trade_date() -> None:
    bars = [polars_schema(parse_schema_name(name)) for name in SCHEMA_NAMES if "ohlcv" in name]
    one_minute = polars_schema(parse_schema_name("ohlcv-1m"))

    assert all(columns == one_minute for columns in bars)
    assert list(one_minute)[:3] == ["ts_open", "ts_close", "trade_date"]
    assert one_minute["trade_date"] == pl.Date


def test_tbbo_rows_are_trades_with_the_best_bid_and_ask_before_them() -> None:
    trades = polars_schema(parse_schema_name("trades"))
    tbbo = polars_schema(parse_schema_name("tbbo"))

    assert list(tbbo.items())[: len(trades)] == list(trades.items())
    assert list(tbbo)[len(trades) :] == ["bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]


def test_statistics_carry_the_vendors_reference_time_beside_the_receive_time() -> None:
    statistics = polars_schema(parse_schema_name("statistics"))

    assert {"ts_recv", "ts_event", "ts_ref", "stat_type", "price", "quantity"} <= set(statistics)


def test_a_schema_hands_out_a_copy_of_its_columns() -> None:
    trades = parse_schema_name("trades")
    polars_schema(trades)["extra"] = pl.Int64

    assert "extra" not in polars_schema(trades)
