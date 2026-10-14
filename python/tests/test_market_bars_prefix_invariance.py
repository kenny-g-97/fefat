"""Prefix invariance of the bar builder (D-12): the bars and grid rows that close by an instant
are the same whether the data runs past it or stops there, cut inside a session, on a bucket's
boundary, at and just after a close, in the break, on a weekend, and inside halts."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.bars import build_bars, resample_bars, session_grid
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name, polars_schema
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Store(ROOT / "fixtures")
NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
NANOSECONDS_PER_HOUR = 60 * NANOSECONDS_PER_MINUTE
ES_DAYS = (date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9))


def timeframe(text: str) -> Timeframe:
    return Timeframe(count=int(text[:-1]), unit=TimeUnit(text[-1]))


def utc(*fields: int) -> int:
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * NANOSECONDS_PER_SECOND


@pytest.fixture(scope="module")
def table(tmp_path_factory: pytest.TempPathFactory) -> SessionTable:
    return sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path_factory.mktemp("cache"))


def es_rows(schema: str) -> pl.DataFrame:
    """The fixture's ES rows of `schema` on its three trade dates."""
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root="ES")
    keys = [YearMonth(year=2026, month=3)] if schema == "ohlcv-1m" else list(ES_DAYS)
    partitions = [Partition(dataset=dataset, contract="ESH2026", key=key) for key in keys]
    return pl.concat([FIXTURES.scan_partition(partition).collect() for partition in partitions])


def the_end(table: SessionTable) -> int:
    return table.following(ES_DAYS[-1]).open


def cuts(table: SessionTable) -> list[int]:
    """Instants to cut the fixture's data at: an open; the planted print on a minute boundary
    and just after it; inside a session; just before, at, and after a close; in a break; the
    planted print after the close of 2026-03-06 and just after it; the weekend and its clock
    change; and the end of the data."""
    march_5, march_6, march_9 = (table.session(day) for day in ES_DAYS)
    boundary = march_5.open + 90 * NANOSECONDS_PER_MINUTE
    after_the_close = march_6.close + 400_000_000
    return [
        march_5.open,
        boundary,
        boundary + 1,
        march_5.open + 7 * NANOSECONDS_PER_HOUR + 123_456_789,
        march_5.close - 1,
        march_5.close,
        march_5.close + 30 * NANOSECONDS_PER_MINUTE,
        march_6.open,
        after_the_close,
        after_the_close + 1,
        utc(2026, 3, 7, 12),
        utc(2026, 3, 8, 21, 59),
        march_9.open + 5 * NANOSECONDS_PER_HOUR,
        the_end(table),
    ]


@pytest.mark.parametrize("width", ["1s", "1m", "7m", "1h", "5h", "1d"])
def test_bars_closing_by_an_instant_stay_the_same_when_the_trades_stop_there(
    table: SessionTable, width: str
) -> None:
    trades = es_rows("trades")
    whole = build_bars(trades, timeframe(width), table, the_end(table))

    for cut in cuts(table):
        in_hand = trades.filter(pl.col("ts_recv") <= cut)
        assert_frame_equal(
            build_bars(in_hand, timeframe(width), table, cut),
            whole.filter(pl.col("ts_close") <= cut),
        )


@pytest.mark.parametrize(
    ("schema", "width"), [("ohlcv-1s", "1m"), ("ohlcv-1m", "5h"), ("ohlcv-1m", "1d")]
)
def test_resampled_bars_closing_by_an_instant_stay_the_same_when_the_bars_stop_there(
    table: SessionTable, schema: str, width: str
) -> None:
    finer = es_rows(schema)
    whole = resample_bars(finer, timeframe(width), table, the_end(table))

    for cut in cuts(table):
        in_hand = finer.filter(pl.col("ts_close") <= cut)
        assert_frame_equal(
            resample_bars(in_hand, timeframe(width), table, cut),
            whole.filter(pl.col("ts_close") <= cut),
        )


@pytest.mark.parametrize("width", ["1m", "7m", "1d"])
def test_grid_rows_closing_by_an_instant_stay_the_same_when_the_trades_stop_there(
    table: SessionTable, width: str
) -> None:
    trades = es_rows("trades")
    first, last = ES_DAYS[0], ES_DAYS[-1]
    bars = build_bars(trades, timeframe(width), table, the_end(table))
    whole = session_grid(bars, timeframe(width), table, the_end(table), first, last)

    for cut in cuts(table):
        in_hand = build_bars(trades.filter(pl.col("ts_recv") <= cut), timeframe(width), table, cut)
        assert_frame_equal(
            session_grid(in_hand, timeframe(width), table, cut, first, last),
            whole.filter(pl.col("ts_close") <= cut),
        )


def trades_of(*prints: tuple[int, int]) -> pl.DataFrame:
    """Trades of instrument 1001, each (ts_recv, price), of one contract each."""
    return pl.DataFrame(
        [
            (ts_recv, ts_recv - 150_000, 1001, price, 1, "B", sequence)
            for sequence, (ts_recv, price) in enumerate(prints, start=1)
        ],
        schema=polars_schema(parse_schema_name("trades")),
        orient="row",
    )


def test_cuts_inside_a_holiday_halt_an_early_close_and_its_break(table: SessionTable) -> None:
    # Friday 2025-11-28's session holds Thanksgiving's halt and closes early at 12:15 CST:
    # prints before, inside, and after the halt, in the last slot, and in the break after it.
    friday = date(2025, 11, 28)
    session = table.session(friday)
    halt = session.halts[0]
    until = table.following(friday).open
    trades = trades_of(
        (session.open + 5 * NANOSECONDS_PER_MINUTE, 100),
        (halt.start - 30 * NANOSECONDS_PER_SECOND, 101),
        (halt.start + 30 * NANOSECONDS_PER_MINUTE, 102),
        (halt.end + 10 * NANOSECONDS_PER_SECOND, 103),
        (session.close - 50_000_000, 104),
        (session.close + 400_000_000, 105),
    )
    instants = (halt.start, halt.start + 30 * NANOSECONDS_PER_MINUTE + 1, halt.end, session.close)

    for width in ("1m", "7m", "1h", "1d"):
        bars = build_bars(trades, timeframe(width), table, until)
        grid = session_grid(bars, timeframe(width), table, until, friday, friday)
        for cut in (*instants, session.close + NANOSECONDS_PER_MINUTE, until):
            in_hand = build_bars(
                trades.filter(pl.col("ts_recv") <= cut), timeframe(width), table, cut
            )
            assert_frame_equal(in_hand, bars.filter(pl.col("ts_close") <= cut))
            assert_frame_equal(
                session_grid(in_hand, timeframe(width), table, cut, friday, friday),
                grid.filter(pl.col("ts_close") <= cut),
            )


def test_a_bar_in_the_break_closes_by_the_next_open(table: SessionTable) -> None:
    # Five-hour buckets from 23:00 UTC put a print received at 22:30, in the hour's break
    # after 2026-03-05's close at 22:00, in the bucket from 19:00 to midnight: its part after
    # the close closes at 23:00, when 03-06's session opens, so a trade date's bars are
    # complete then and building it alone gives the bars of the whole range. Four-hour buckets
    # put a print at 21:59 UTC on Sunday 03-08, in the weekend after Friday's close, in the
    # bucket from 19:00, which closes at 22:00, when Monday's session opens, an hour earlier in
    # UTC since the clocks changed.
    five_hours, four_hours = timeframe("5h"), timeframe("4h")
    next_open = table.following(ES_DAYS[0]).open
    trades = trades_of(
        (utc(2026, 3, 5, 22, 30), 100), (next_open + 10 * NANOSECONDS_PER_MINUTE, 101)
    )
    weekend = trades_of((utc(2026, 3, 8, 21, 59), 100))

    whole = build_bars(trades, five_hours, table, table.following(ES_DAYS[1]).open)
    alone = build_bars(trades.filter(pl.col("ts_recv") < next_open), five_hours, table, next_open)
    sunday = build_bars(weekend, four_hours, table, table.following(ES_DAYS[1]).open)

    assert whole.select("ts_open", "ts_close", "trade_date").rows() == [
        (utc(2026, 3, 5, 22), next_open, ES_DAYS[0]),
        (next_open, utc(2026, 3, 6, 4), ES_DAYS[1]),
    ]
    assert_frame_equal(alone, whole.head(1))
    assert sunday.select("ts_open", "ts_close", "trade_date").rows() == [
        (utc(2026, 3, 8, 19), utc(2026, 3, 8, 22), ES_DAYS[1])
    ]
