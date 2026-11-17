"""Bars in a break against an offset (step 5.15, ADR-0022): a file that holds bars through a
break, a bar in the minute before an open, or bars before the open of a session it ends inside
shows no offset, while a file stamped a bar early, wholly or in a part of whole sessions, or a
part of it read hours off, still does. The fixtures' ESH2026 1-minute bars hold three whole
sessions, 2026-03-05, 03-06, and 03-09, across the clock change of 2026-03-08; the bars of
longer spans are generated on the calendar."""

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_check import check_records
from fefat.market.calendar_definition import CalendarId
from fefat.market.calendar_offset import OffsetCause
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

FIXTURES = Store(Path(__file__).resolve().parents[2] / "fixtures")
ES_MINUTES = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
ES_HOURS = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1h"), root="ES")
ESH2026_MINUTES = Partition(
    dataset=ES_MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=3)
)
MINUTE = 60_000_000_000
HOUR = 60 * MINUTE
MARCH_5, MARCH_6, MARCH_9 = date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)

type Offsets = list[tuple[int, OffsetCause, date, date]]


@pytest.fixture
def sessions(tmp_path: Path) -> SessionTable:
    return sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path)


def fixture_bars() -> pl.DataFrame:
    """The fixtures' ESH2026 1-minute bars, as stored."""
    return FIXTURES.scan_partition(ESH2026_MINUTES).collect()


def dated_again(bars: pl.DataFrame, sessions: SessionTable) -> pl.LazyFrame:
    """`bars` dated again by their `ts_open`, as an import dates them."""
    dated = sessions.assign_trade_dates_or_previous(bars.drop("trade_date"), "ts_open")
    return dated.select(bars.columns).lazy()


def with_bars_at(bars: pl.DataFrame, opens: Iterable[int], sessions: SessionTable) -> pl.LazyFrame:
    """`bars` and a minute's bar opening at each of `opens`, its values the first bar's, dated
    again as an import dates them."""
    first = bars.head(1)
    added = [
        first.with_columns(ts_open=pl.lit(opened), ts_close=pl.lit(opened + MINUTE))
        for opened in opens
    ]
    return dated_again(pl.concat([bars, *added]), sessions)


def generated(opens: Iterable[int], width: int, sessions: SessionTable) -> pl.LazyFrame:
    """Bars `width` long opening at `opens`, dated as an import dates them: what the calendar
    check reads of a file."""
    frame = pl.DataFrame({"ts_open": sorted(opens)}, schema={"ts_open": pl.Int64})
    dated = sessions.assign_trade_dates_or_previous(
        frame.with_columns(ts_close=pl.col("ts_open") + width), "ts_open"
    )
    return dated.drop("in_session").lazy()


def offsets(dataset: Dataset, bars: pl.LazyFrame, sessions: SessionTable) -> Offsets:
    """The offsets the calendar check finds, each as its size, cause, and trade dates."""
    return [
        (offset.nanoseconds, offset.cause, offset.first_trade_date, offset.last_trade_date)
        for offset in check_records(dataset, bars, sessions).offsets
    ]


def test_bars_through_a_daily_break_show_no_offset(sessions: SessionTable) -> None:
    # Done means 1: a bar in every minute of the break after 03-05, the last closing at the
    # open of 03-06, read today as a file stamped a bar early.
    after = sessions.session(MARCH_5)
    bars = with_bars_at(
        fixture_bars(), range(after.close, sessions.following(MARCH_5).open, MINUTE), sessions
    )

    assert offsets(ES_MINUTES, bars, sessions) == []


def test_a_bar_in_the_minute_before_an_open_shows_no_offset(sessions: SessionTable) -> None:
    # Done means 1: one bar closing at the open of 03-06, read today as a bar early.
    bars = with_bars_at(fixture_bars(), [sessions.session(MARCH_6).open - MINUTE], sessions)

    assert offsets(ES_MINUTES, bars, sessions) == []


def test_bars_before_the_open_of_a_session_the_file_ends_inside_show_no_offset(
    sessions: SessionTable,
) -> None:
    # Done means 1, the shape of your MNQ 03-24: an hour of bars before the open of 03-09,
    # after the clock change of 03-08, and the first 300 minutes of that session, where the
    # file ends; the part after the change read today as an hour early.
    opened = sessions.session(MARCH_9).open
    ending = fixture_bars().filter(pl.col("ts_open") < opened + 300 * MINUTE)
    bars = with_bars_at(ending, range(opened - HOUR, opened, MINUTE), sessions)

    assert offsets(ES_MINUTES, bars, sessions) == []


def test_bars_before_an_open_beside_sessions_missing_their_last_minutes_show_no_offset(
    sessions: SessionTable,
) -> None:
    # Done means 7, the shape of your ES 12-20's 2020-09-10 and 09-11: nine bars before the
    # open of 03-09, while 03-06 and 03-09 miss their last eight minutes, so the session after
    # them misses the bucket before its last as well, as a session a bar early never does.
    missing = pl.any_horizontal(
        pl.col("ts_open").is_between(session.close - 8 * MINUTE, session.close, closed="left")
        for session in (sessions.session(MARCH_6), sessions.session(MARCH_9))
    )
    opened = sessions.session(MARCH_9).open
    bars = with_bars_at(
        fixture_bars().filter(~missing), range(opened - 9 * MINUTE, opened, MINUTE), sessions
    )

    assert offsets(ES_MINUTES, bars, sessions) == []


def test_two_exports_joined_the_second_a_bar_early_show_that_offset(
    sessions: SessionTable,
) -> None:
    # Done means 7: from 03-06 on the bars run a bar early, as an export stamped at the bars'
    # opens joined to one stamped at their closes gives, so 03-09 holds no bar in its last
    # bucket and one in the bucket before.
    shift = pl.when(pl.col("trade_date") >= MARCH_6).then(-MINUTE).otherwise(0)
    joined = fixture_bars().with_columns(pl.col("ts_open") + shift, pl.col("ts_close") + shift)

    assert offsets(ES_MINUTES, dated_again(joined, sessions), sessions) == [
        (-MINUTE, OffsetCause.BAR_STAMPING, MARCH_5, MARCH_9)
    ]


def test_a_bar_before_most_opens_shows_an_offset_of_one_bar(sessions: SessionTable) -> None:
    # Two of the three sessions open after a bar closing at their open: half of them or more
    # read as a file stamped a bar early, whatever their last buckets hold.
    opens = [sessions.session(day).open - MINUTE for day in (MARCH_6, MARCH_9)]
    bars = with_bars_at(fixture_bars(), opens, sessions)

    assert [found[:2] for found in offsets(ES_MINUTES, bars, sessions)] == [
        (-MINUTE, OffsetCause.BAR_STAMPING)
    ]


def test_hourly_bars_an_hour_late_after_a_clock_change_show_that_offset(
    sessions: SessionTable,
) -> None:
    # Times kept in Central daylight time all year, read as Chicago's, run an hour late once
    # standard time starts on 2026-11-01. The part after the change spans whole sessions, which
    # its bars, each opening an hour before the next, never reach the close of alone, so the
    # part's span, not each session's bars, decides that its hours count (ADR-0022).
    days = sessions.between(date(2026, 10, 12), date(2026, 11, 17))
    late = date(2026, 11, 2)
    opens = [
        opened + (HOUR if trade_date >= late else 0)
        for trade_date, start, end in days.select("trade_date", "open", "close").rows()
        for opened in range(start, end, HOUR)
    ]

    assert offsets(ES_HOURS, generated(opens, HOUR, sessions), sessions) == [
        (30 * MINUTE, OffsetCause.TIME_ZONE, late, date(2026, 11, 17))
    ]


def test_thin_sessions_an_hour_early_before_a_clock_change_show_that_offset(
    sessions: SessionTable,
) -> None:
    # Ten thin sessions, an evening bar every five minutes and the day's regular hours, times
    # kept in Central standard time all year and read as Chicago's, so an hour early until
    # standard time starts; then whole sessions. None of the ten holds its session's last half
    # hour, and their hours count since the part spans the sessions between its first and its
    # last, as a few hours after a clock change never do (ADR-0022).
    thin = sessions.between(date(2026, 10, 19), date(2026, 10, 30)).get_column("open")
    evening_and_day = [
        *range(5 * MINUTE, HOUR, 5 * MINUTE),
        *range(930 * MINUTE, 1320 * MINUTE, MINUTE),
    ]
    whole = sessions.between(date(2026, 11, 2), date(2026, 11, 27)).select("open", "close")
    opens = [opened - HOUR + after for opened in thin.to_list() for after in evening_and_day]
    opens += [opened for start, end in whole.rows() for opened in range(start, end, MINUTE)]

    assert offsets(ES_MINUTES, generated(opens, MINUTE, sessions), sessions) == [
        (-HOUR, OffsetCause.TIME_ZONE, date(2026, 10, 19), date(2026, 10, 30))
    ]
