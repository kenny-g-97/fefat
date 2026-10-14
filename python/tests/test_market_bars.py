from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.bars import BAR_COLUMNS, GRID_COLUMNS, build_bars, resample_bars, session_grid
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name, polars_schema
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Store(ROOT / "fixtures")
SECOND = Timeframe(count=1, unit=TimeUnit.SECOND)
MINUTE = Timeframe(count=1, unit=TimeUnit.MINUTE)
FIVE_MINUTES = Timeframe(count=5, unit=TimeUnit.MINUTE)
DAY = Timeframe(count=1, unit=TimeUnit.DAY)
NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
EQUITY_INDEX = CalendarId.CME_EQUITY_INDEX
MARCH_5, MARCH_6, MARCH_9 = date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)


def utc(*fields: int) -> int:
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * NANOSECONDS_PER_SECOND


# The fixture sessions with the open of the session after each: every print of a trade date is
# received before the next session opens (the planted print 400 ms after the close of 03-06
# too), so its bars are complete then.
FIXTURE_DAYS = [
    ("ES", "ESH2026", EQUITY_INDEX, MARCH_5, utc(2026, 3, 5, 23)),
    ("ES", "ESH2026", EQUITY_INDEX, MARCH_6, utc(2026, 3, 8, 22)),
    ("ES", "ESH2026", EQUITY_INDEX, date(2026, 3, 9), utc(2026, 3, 9, 22)),
    ("BTCUSDT-PERP", "BTCUSDT-PERP", CalendarId.CRYPTO_24X7, date(2026, 3, 7), utc(2026, 3, 8)),
]
NEXT_OPEN_AFTER_MARCH_6 = utc(2026, 3, 8, 22)


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> dict[CalendarId, SessionTable]:
    cache_folder = tmp_path_factory.mktemp("cache")
    return {
        identity: sessions_of(calendar, cache_folder) for identity, calendar in BUILT_IN.items()
    }


def fixture_rows(schema: str, root: str, contract: str, day: date) -> pl.DataFrame:
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root=root)
    key = YearMonth(year=day.year, month=day.month) if schema == "ohlcv-1m" else day
    rows = FIXTURES.scan_partition(Partition(dataset=dataset, contract=contract, key=key))
    if schema == "trades":
        return rows.collect()
    return rows.filter(pl.col("trade_date") == day).collect()


def assert_equal_but_a_vwap_rounded_down(
    resampled: pl.DataFrame, built: pl.DataFrame, resamplings: int
) -> None:
    """Equal bars, but for a vwap that each resampling of rounded vwaps can lower by a unit."""
    assert_frame_equal(resampled.drop("vwap"), built.drop("vwap"))
    shortfall = built.get_column("vwap") - resampled.get_column("vwap")
    assert shortfall.null_count() == 0
    assert shortfall.is_between(0, resamplings).all()


@pytest.mark.parametrize(("root", "contract", "calendar_id", "day", "next_open"), FIXTURE_DAYS)
def test_bars_built_from_trades_equal_the_fixtures_1_second_and_1_minute_bars(
    tables: dict[CalendarId, SessionTable],
    root: str,
    contract: str,
    calendar_id: CalendarId,
    day: date,
    next_open: int,
) -> None:
    trades = fixture_rows("trades", root, contract, day)
    table = tables[calendar_id]

    seconds = build_bars(trades, SECOND, table, next_open)
    minutes = build_bars(trades, MINUTE, table, next_open)

    assert_frame_equal(seconds, fixture_rows("ohlcv-1s", root, contract, day))
    assert_frame_equal(minutes, fixture_rows("ohlcv-1m", root, contract, day))


@pytest.mark.parametrize(("root", "contract", "calendar_id", "day", "next_open"), FIXTURE_DAYS)
def test_bars_resampled_from_finer_bars_equal_bars_built_from_trades(
    tables: dict[CalendarId, SessionTable],
    root: str,
    contract: str,
    calendar_id: CalendarId,
    day: date,
    next_open: int,
) -> None:
    trades = fixture_rows("trades", root, contract, day)
    seconds = fixture_rows("ohlcv-1s", root, contract, day)
    minutes = fixture_rows("ohlcv-1m", root, contract, day)
    table = tables[calendar_id]
    session = table.session(day)

    built_minutes = build_bars(trades, MINUTE, table, next_open)
    built_five_minutes = build_bars(trades, FIVE_MINUTES, table, next_open)
    built_day = build_bars(trades, DAY, table, next_open)
    five_minutes = resample_bars(minutes, FIVE_MINUTES, table, next_open)

    assert_equal_but_a_vwap_rounded_down(
        resample_bars(seconds, MINUTE, table, next_open), built_minutes, 1
    )
    assert_equal_but_a_vwap_rounded_down(five_minutes, built_five_minutes, 1)
    assert_equal_but_a_vwap_rounded_down(
        resample_bars(minutes, DAY, table, next_open), built_day, 1
    )
    assert_equal_but_a_vwap_rounded_down(
        resample_bars(seconds, DAY, table, next_open), built_day, 1
    )
    assert_equal_but_a_vwap_rounded_down(
        resample_bars(five_minutes, DAY, table, next_open), built_day, 2
    )
    # A daily bar is the session, and holds the prints received inside it only.
    in_the_session = trades.filter(pl.col("ts_recv") < session.close).get_column("size").sum()
    assert built_day.select("ts_open", "ts_close", "trade_date", "volume").rows() == [
        (session.open, session.close, day, in_the_session)
    ]


@pytest.mark.parametrize(
    ("width", "timeframe"), [(NANOSECONDS_PER_SECOND, SECOND), (NANOSECONDS_PER_MINUTE, MINUTE)]
)
@pytest.mark.parametrize(("root", "contract", "calendar_id", "day", "next_open"), FIXTURE_DAYS)
def test_a_print_on_a_boundary_opens_its_bar_and_one_in_the_last_slot_ends_at_the_close(
    tables: dict[CalendarId, SessionTable],
    root: str,
    contract: str,
    calendar_id: CalendarId,
    day: date,
    next_open: int,
    width: int,
    timeframe: Timeframe,
) -> None:
    # The fixtures plant a print received exactly 90 minutes after each open and one 50 ms
    # before each close (step 1.5). A bar is [t, t + width): the print at t is its first.
    trades = fixture_rows("trades", root, contract, day)
    table = tables[calendar_id]
    session = table.session(day)
    boundary = session.open + 90 * NANOSECONDS_PER_MINUTE
    received = pl.col("ts_recv")

    bars = build_bars(trades, timeframe, table, next_open)

    def bar_at(ts_open: int) -> tuple[int, ...]:
        return bars.filter(pl.col("ts_open") == ts_open).select("trade_count", "close").row(0)

    def prints_in(start: int) -> int:
        return trades.filter((received >= start) & (received < start + width)).height

    last_slot = trades.filter(received == session.close - 50_000_000).get_column("price").item()
    assert bar_at(boundary)[0] == prints_in(boundary)
    assert trades.filter(received == boundary).height == 1
    assert bars.filter(pl.col("ts_close") == boundary).get_column("trade_count").sum() == prints_in(
        boundary - width
    )
    assert bar_at(session.close - width) == (prints_in(session.close - width), last_slot)


def test_a_print_received_after_the_close_keeps_its_trade_date_in_a_bar_of_its_own(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # 400 ms after the close of Friday 2026-03-06, 22:00 UTC, a print arrives in the break: it
    # keeps Friday's trade date in a bar opening at the close, as the vendor's bars do, joins
    # no daily bar, and lies outside the grid.
    trades = fixture_rows("trades", "ES", "ESH2026", MARCH_6)
    table = tables[EQUITY_INDEX]
    close = table.session(MARCH_6).close
    late = trades.filter(pl.col("ts_recv") >= close)

    minutes = build_bars(trades, MINUTE, table, NEXT_OPEN_AFTER_MARCH_6)
    day = build_bars(trades, DAY, table, NEXT_OPEN_AFTER_MARCH_6)
    grid = session_grid(minutes, MINUTE, table, NEXT_OPEN_AFTER_MARCH_6, MARCH_6, MARCH_6)

    assert late.get_column("ts_recv").to_list() == [close + 400_000_000]
    assert minutes.filter(pl.col("ts_open") >= close).select(
        "ts_open", "ts_close", "trade_date", "volume", "trade_count"
    ).rows() == [(close, close + NANOSECONDS_PER_MINUTE, MARCH_6, late.item(0, "size"), 1)]
    assert day.item(0, "volume") == trades.get_column("size").sum() - late.item(0, "size")
    assert grid.filter(pl.col("ts_open") >= close).is_empty()
    assert grid.height == 23 * 60


def test_a_bar_whose_close_lies_after_the_end_of_the_data_is_held_back(
    tables: dict[CalendarId, SessionTable],
) -> None:
    trades = fixture_rows("trades", "ES", "ESH2026", MARCH_5)
    table = tables[EQUITY_INDEX]
    close = table.session(MARCH_5).close

    complete = build_bars(trades, MINUTE, table, close)
    held_back = build_bars(trades, MINUTE, table, close - 1)

    assert complete.get_column("ts_close").max() == close
    assert_frame_equal(held_back, complete.filter(pl.col("ts_close") < close))
    assert resample_bars(complete, DAY, table, close - 1).is_empty()
    assert resample_bars(complete, DAY, table, close).height == 1


def test_a_print_in_the_break_after_a_regular_close_gets_a_coarse_bar_of_its_own(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Four-hour buckets from 23:00 UTC do not divide a 23-hour session: the last runs from
    # 19:00 to the close at 22:00 UTC, and the print received at 22:00:00.4 on 2026-03-06
    # opens a bar of its own from the close to 23:00, outside the daily bar.
    trades = fixture_rows("trades", "ES", "ESH2026", MARCH_6)
    table = tables[EQUITY_INDEX]
    four_hours = Timeframe(count=4, unit=TimeUnit.HOUR)

    bars = build_bars(trades, four_hours, table, NEXT_OPEN_AFTER_MARCH_6)

    assert bars.select("ts_open", "ts_close").rows()[-2:] == [
        (utc(2026, 3, 6, 19), utc(2026, 3, 6, 22)),
        (utc(2026, 3, 6, 22), utc(2026, 3, 6, 23)),
    ]
    assert_frame_equal(
        resample_bars(bars, DAY, table, NEXT_OPEN_AFTER_MARCH_6),
        build_bars(trades, DAY, table, NEXT_OPEN_AFTER_MARCH_6),
    )


def test_the_vwap_of_negative_prices_rounds_down_toward_minus_infinity(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Crude oil traded below zero in April 2020: prints at -37.63, -37.62, and -37.62 in one
    # minute weigh to -37.62333..., rounded down to -37.623333334, not truncated to ...333.
    table = tables[EQUITY_INDEX]
    minute = utc(2026, 3, 5, 15)
    trades = trades_of(
        (minute + 1, -37_630_000_000), (minute + 2, -37_620_000_000), (minute + 3, -37_620_000_000)
    )

    bars = build_bars(trades, MINUTE, table, table.following(MARCH_5).open)

    assert bars.select("low", "high", "vwap").rows() == [
        (-37_630_000_000, -37_620_000_000, -37_623_333_334)
    ]


def test_bars_that_straddle_the_buckets_asked_for_are_refused(
    tables: dict[CalendarId, SessionTable],
) -> None:
    table = tables[EQUITY_INDEX]
    minutes = fixture_rows("ohlcv-1m", "ES", "ESH2026", MARCH_5)
    five_minutes = resample_bars(minutes, FIVE_MINUTES, table, utc(2026, 3, 5, 23))

    with pytest.raises(ValueError, match="Expected bars nested in the buckets of 7m, got"):
        resample_bars(five_minutes, Timeframe(count=7, unit=TimeUnit.MINUTE), table, 0)
    with pytest.raises(ValueError, match="Expected bars nested in the buckets of 1m, got"):
        resample_bars(five_minutes, MINUTE, table, 0)
    with pytest.raises(ValueError, match="Expected 1d, a session's bar, or an intraday"):
        resample_bars(minutes, Timeframe(count=2, unit=TimeUnit.DAY), table, 0)


def test_the_grid_holds_every_second_of_the_session_and_flags_the_empty_ones(
    tables: dict[CalendarId, SessionTable],
) -> None:
    table = tables[EQUITY_INDEX]
    session = table.session(MARCH_5)
    seconds = fixture_rows("ohlcv-1s", "ES", "ESH2026", MARCH_5)

    grid = session_grid(seconds, SECOND, table, table.following(MARCH_5).open, MARCH_5, MARCH_5)

    empty = grid.with_columns(previous_close=pl.col("close").shift(1)).filter("zero_volume")
    assert grid.schema == GRID_COLUMNS
    assert grid.get_column("ts_open").to_list() == list(
        range(session.open, session.close, NANOSECONDS_PER_SECOND)
    )
    assert_frame_equal(grid.filter(~pl.col("zero_volume")).drop("zero_volume"), seconds)
    assert empty.height == 23 * 3600 - seconds.height
    assert empty.select(
        flat=(pl.col("open") == pl.col("close"))
        & (pl.col("high") == pl.col("close"))
        & (pl.col("low") == pl.col("close"))
        & (pl.col("close") == pl.col("previous_close")),
        quiet=(pl.col("volume") == 0) & (pl.col("trade_count") == 0) & pl.col("vwap").is_null(),
    ).select(pl.all().all()).row(0) == (True, True)


def one_minute_bars(*bars: tuple[int, date, int, int]) -> pl.DataFrame:
    """Bars of one minute, each (ts_open, trade_date, instrument_id, price), of one print."""
    return pl.DataFrame(
        [
            (
                ts_open,
                ts_open + NANOSECONDS_PER_MINUTE,
                trade_date,
                instrument_id,
                *(price,) * 4,
                1,
                1,
                price,
            )
            for ts_open, trade_date, instrument_id, price in bars
        ],
        schema=BAR_COLUMNS,
        orient="row",
    )


def test_the_grid_starts_each_instrument_at_its_first_bar_and_carries_its_close_forward(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Instrument 1 trades in the second minute of 2026-03-05's session and the first of
    # 03-09's: its rows start at its first bar, stay at 100 through 03-06, a day without bars,
    # and turn 300 at its bar on 03-09. Instrument 2 trades once, at 03-06's open: its rows
    # start there and carry its close to the end of the range, since no bar says it stopped.
    table = tables[EQUITY_INDEX]
    march_5, march_6, march_9 = (table.session(day) for day in (MARCH_5, MARCH_6, MARCH_9))
    bars = one_minute_bars(
        (march_5.open + NANOSECONDS_PER_MINUTE, MARCH_5, 1, 100),
        (march_9.open, MARCH_9, 1, 300),
        (march_6.open, MARCH_6, 2, 200),
    )
    per_session = 23 * 60
    until = table.following(MARCH_9).open

    grid = session_grid(bars, MINUTE, table, until, MARCH_5, MARCH_9)
    days = session_grid(resample_bars(bars, DAY, table, until), DAY, table, until, MARCH_5, MARCH_9)

    first = grid.filter(pl.col("instrument_id") == 1).get_column("close").to_list()
    second = grid.filter(pl.col("instrument_id") == 2).get_column("close").to_list()
    assert first == [100] * (2 * per_session - 1) + [300] * per_session
    assert second == [200] * 2 * per_session
    assert days.select("instrument_id", "trade_date", "close", "zero_volume").rows() == [
        (1, MARCH_5, 100, False),
        (1, MARCH_6, 100, True),
        (1, MARCH_9, 300, False),
        (2, MARCH_6, 200, False),
        (2, MARCH_9, 200, True),
    ]


def test_the_grid_up_to_an_instant_never_changes_when_later_bars_are_removed(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # The truncation test of D-12 on the grid: instrument 1 trades on 2026-03-05 and 03-09 and
    # not on 03-06, instrument 2 first on 03-09. With the data ending at 12:00 UTC on Friday
    # 03-06, the grid holds exactly the rows of the whole data closing by then: no row exists,
    # is missing, or holds a value because of a bar to come, and none runs past the end.
    table = tables[EQUITY_INDEX]
    march_5, march_9 = table.session(MARCH_5), table.session(MARCH_9)
    bars = one_minute_bars(
        (march_5.open + NANOSECONDS_PER_MINUTE, MARCH_5, 1, 100),
        (march_9.open, MARCH_9, 1, 300),
        (march_9.open, MARCH_9, 2, 200),
    )
    cut = utc(2026, 3, 6, 12)
    whole = session_grid(bars, MINUTE, table, table.following(MARCH_9).open, MARCH_5, MARCH_9)
    in_hand = bars.filter(pl.col("ts_close") <= cut)
    truncated = session_grid(in_hand, MINUTE, table, cut, MARCH_5, MARCH_9)

    before_the_cut = whole.filter(pl.col("ts_close") <= cut)
    assert before_the_cut.filter(pl.col("trade_date") == MARCH_6).height > 0
    assert_frame_equal(truncated, before_the_cut)


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


def test_a_bucket_the_close_cuts_in_two_is_two_bars(tables: dict[CalendarId, SessionTable]) -> None:
    # Friday 2026-11-27 closes early at 12:15 CST, 18:15 UTC, inside the hourly bucket from
    # 12:00 to 13:00: a print at 12:05 is in the bar from 12:00 to the close, and one received
    # at 12:20, in the break, opens a bar of its own at the close, outside the daily bar.
    table = tables[EQUITY_INDEX]
    friday = date(2026, 11, 27)
    session = table.session(friday)
    hour = Timeframe(count=1, unit=TimeUnit.HOUR)
    trades = trades_of((utc(2026, 11, 27, 18, 5), 100), (utc(2026, 11, 27, 18, 20), 200))
    received_until = table.following(friday).open

    hours = build_bars(trades, hour, table, received_until)
    day = resample_bars(hours, DAY, table, received_until)
    grid = session_grid(hours, hour, table, received_until, friday, friday)

    assert session.close == utc(2026, 11, 27, 18, 15)
    assert hours.select("ts_open", "ts_close", "trade_date", "close", "volume").rows() == [
        (utc(2026, 11, 27, 18), session.close, friday, 100, 1),
        (session.close, utc(2026, 11, 27, 19), friday, 200, 1),
    ]
    assert_frame_equal(day, build_bars(trades, DAY, table, received_until))
    assert day.select("ts_close", "close", "volume").rows() == [(session.close, 100, 1)]
    assert grid.select("ts_open", "ts_close").row(-1) == (utc(2026, 11, 27, 18), session.close)


def test_bars_outside_their_sessions_and_bars_twice_in_the_grid_are_refused(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # A bar on Saturday 2026-03-07, which has no session; a bar dated 03-05 opening at 16:59
    # CST on 03-04, a minute before that session opens; and one bar given twice to the grid.
    table = tables[EQUITY_INDEX]
    saturday = one_minute_bars((utc(2026, 3, 7, 12), date(2026, 3, 7), 1, 100))
    early = one_minute_bars((utc(2026, 3, 4, 22, 59), MARCH_5, 1, 100))
    twice = one_minute_bars(*[(table.session(MARCH_5).open, MARCH_5, 1, 100)] * 2)
    until = table.following(MARCH_5).open

    with pytest.raises(ValueError, match="Expected a session on the trade date of every bar"):
        resample_bars(saturday, FIVE_MINUTES, table, until)
    with pytest.raises(ValueError, match="at or after the open of their session, got one at"):
        resample_bars(early, DAY, table, until)
    with pytest.raises(ValueError, match="Expected one bar for each instrument and ts_open"):
        session_grid(twice, MINUTE, table, until, MARCH_5, MARCH_5)


def test_the_grid_leaves_out_the_hours_a_halt_closes(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Friday 2025-11-28's session runs from Wednesday 17:00 CST to Friday's early close at 12:15,
    # 2,595 minutes, less Thanksgiving's halt from 12:00 to 17:00, 300 minutes. Friday
    # 2021-06-25's 1,380 minutes lose the daily halt from 15:15 to 15:30 CDT, 20:15 to 20:30
    # UTC, where a bar at 15:20 stays out of the grid but counts in the day's bar, as the
    # vendor's prints inside halts do; Monday 06-28's keep them all.
    table = tables[EQUITY_INDEX]
    thanksgiving, june_25, june_28 = date(2025, 11, 28), date(2021, 6, 25), date(2021, 6, 28)
    bars = one_minute_bars(
        (table.session(thanksgiving).open, thanksgiving, 1, 100),
        (table.session(june_25).open, june_25, 1, 100),
        (utc(2021, 6, 25, 20, 20), june_25, 1, 101),
    )
    halt = table.session(thanksgiving).halts[0]

    until_thanksgiving = table.following(thanksgiving).open
    until_june = table.following(june_28).open

    after_thanksgiving = session_grid(
        bars, MINUTE, table, until_thanksgiving, thanksgiving, thanksgiving
    )
    june = session_grid(bars, MINUTE, table, until_june, june_25, june_28)
    june_25_day = resample_bars(
        bars.filter(pl.col("trade_date") == june_25), DAY, table, table.following(june_25).open
    )

    assert after_thanksgiving.height == 2_295
    assert after_thanksgiving.filter(
        pl.col("ts_open").is_between(halt.start, halt.end, closed="left")
    ).is_empty()
    assert june.group_by("trade_date").len().sort("trade_date").rows() == [
        (june_25, 1_365),
        (june_28, 1_380),
    ]
    assert june.filter(pl.col("ts_open") == utc(2021, 6, 25, 20, 20)).is_empty()
    assert june_25_day.select("volume", "close").rows() == [(2, 101)]


def test_the_grid_refuses_bars_of_another_timeframe(tables: dict[CalendarId, SessionTable]) -> None:
    # The fixture's 1-minute bars in a 5-minute grid, and a 1-second bar that no 1-minute
    # bucket starts at in a 1-minute grid.
    table = tables[EQUITY_INDEX]
    minutes = fixture_rows("ohlcv-1m", "ES", "ESH2026", MARCH_5)
    since_the_open = pl.col("ts_open") - table.session(MARCH_5).open
    second = (
        fixture_rows("ohlcv-1s", "ES", "ESH2026", MARCH_5)
        .filter(since_the_open % NANOSECONDS_PER_MINUTE != 0)
        .head(1)
    )
    until = table.following(MARCH_5).open

    with pytest.raises(ValueError, match="Expected bars of 5m in the buckets of their sessions"):
        session_grid(minutes, FIVE_MINUTES, table, until, MARCH_5, MARCH_5)
    with pytest.raises(ValueError, match="Expected bars of 1m in the buckets of their sessions"):
        session_grid(second, MINUTE, table, until, MARCH_5, MARCH_5)
    assert second.height == 1
