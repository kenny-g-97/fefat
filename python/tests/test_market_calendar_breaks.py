"""Bars in a break against an offset (step 5.15, ADR-0022): a file that holds bars through a
break, a bar in the minute before an open, or bars before the open of a session it ends inside
shows no offset but bars in a break, with the sessions beside them, while a file stamped a bar
early, wholly or in a part of whole sessions, or a part of it read hours off, still does. The
fixtures' ESH2026 1-minute bars hold three whole sessions, 2026-03-05, 03-06, and 03-09, across
the clock change of 2026-03-08; the bars and trades of longer spans are generated on the
calendar."""

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
ES_TRADES = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
ESH2026_MINUTES = Partition(
    dataset=ES_MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=3)
)
MINUTE = 60_000_000_000
HOUR = 60 * MINUTE
MARCH_5, MARCH_6, MARCH_9 = date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)

type Offsets = list[tuple[int, OffsetCause, date, date]]
type Breaks = list[tuple[list[tuple[date, int]], list[date]]]


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


def breaks_found(bars: pl.LazyFrame, sessions: SessionTable) -> Breaks:
    """What the calendar check finds of the bars' breaks: each break that holds a bar closing at
    the next open, as the trade date it follows and its bars, and the trade dates beside them;
    none where it finds an offset or no such break."""
    report = check_records(ES_MINUTES, bars, sessions)
    assert report.offsets == ()
    return [
        (
            [(each.after, each.bars) for each in found.breaks],
            found.trade_dates_beside(),
        )
        for found in report.breaks_with_bars
    ]


def test_bars_through_a_daily_break_are_bars_in_a_break(sessions: SessionTable) -> None:
    # Done means 1: a bar in every minute of the break after 03-05, the last closing at the
    # open of 03-06, read today as a file stamped a bar early. The sessions on both sides go
    # with them, and 03-09 too, since the fixtures' straggler after the close of 03-06 joins
    # it by a break that holds a bar.
    after = sessions.session(MARCH_5)
    bars = with_bars_at(
        fixture_bars(), range(after.close, sessions.following(MARCH_5).open, MINUTE), sessions
    )

    assert breaks_found(bars, sessions) == [([(MARCH_5, 60)], [MARCH_5, MARCH_6, MARCH_9])]


def test_a_bar_in_the_minute_before_an_open_is_a_bar_in_a_break(sessions: SessionTable) -> None:
    # Done means 1: one bar closing at the open of 03-06, read today as a bar early.
    bars = with_bars_at(fixture_bars(), [sessions.session(MARCH_6).open - MINUTE], sessions)

    assert breaks_found(bars, sessions) == [([(MARCH_5, 1)], [MARCH_5, MARCH_6, MARCH_9])]


def test_bars_before_the_open_of_a_session_the_file_ends_inside_are_bars_in_a_break(
    sessions: SessionTable,
) -> None:
    # Done means 1, the shape of your MNQ 03-24: an hour of bars before the open of 03-09,
    # after the clock change of 03-08, and the first 300 minutes of that session, where the
    # file ends; the part after the change read today as an hour early. The weekend break
    # holds the straggler after the close of 03-06 as well.
    opened = sessions.session(MARCH_9).open
    ending = fixture_bars().filter(pl.col("ts_open") < opened + 300 * MINUTE)
    bars = with_bars_at(ending, range(opened - HOUR, opened, MINUTE), sessions)

    assert breaks_found(bars, sessions) == [([(MARCH_6, 61)], [MARCH_6, MARCH_9])]


def test_bars_before_an_open_beside_sessions_missing_their_last_minutes_are_bars_in_a_break(
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

    assert breaks_found(bars, sessions) == [([(MARCH_6, 10)], [MARCH_6, MARCH_9])]


def test_bars_in_a_break_that_reach_no_open_are_kept_and_not_found(
    sessions: SessionTable,
) -> None:
    # The fixtures' straggler after the close of 03-06, and bars in the middle of the break
    # after 03-05, reach no open: they stay, as before (D-43), and refuse nothing.
    after = sessions.session(MARCH_5)
    bars = with_bars_at(
        fixture_bars(), [after.close + 10 * MINUTE, after.close + 20 * MINUTE], sessions
    )

    assert breaks_found(bars, sessions) == []


def test_the_sessions_beside_grow_across_breaks_that_hold_a_bar(sessions: SessionTable) -> None:
    # Generated whole sessions from 2026-02-02 to 02-13: a bar closing at the open of 02-10,
    # after the break of 02-09, and a stray in the break after 02-05, the Thursday before, and
    # in the weekend after 02-06: the sessions joined to 02-09 by breaks with bars go too,
    # back to 02-05, while 02-04, whose break after it holds none, stays.
    days = sessions.between(date(2026, 2, 2), date(2026, 2, 13))
    opens = [
        opened
        for start, end in days.select("open", "close").rows()
        for opened in range(start, end, MINUTE)
    ]
    strays = [sessions.session(date(2026, 2, day)).close + 5 * MINUTE for day in (5, 6)]
    reaching = [sessions.session(date(2026, 2, 10)).open - MINUTE]

    assert breaks_found(generated([*opens, *strays, *reaching], MINUTE, sessions), sessions) == [
        (
            [(date(2026, 2, 9), 1)],
            [date(2026, 2, day) for day in (5, 6, 9, 10)],
        )
    ]


def test_bars_in_a_break_are_described_in_counts_and_trade_dates(sessions: SessionTable) -> None:
    # What the calendar check says of them, here and of stored data alike, in counts and dates
    # alone, never a price (D-21): the fixtures' 1,381 bars of 03-06, the hour before the open
    # of 03-09 and the straggler after 03-06's close among them, and 300 of 03-09.
    opened = sessions.session(MARCH_9).open
    ending = fixture_bars().filter(pl.col("ts_open") < opened + 300 * MINUTE)
    bars = with_bars_at(ending, range(opened - HOUR, opened, MINUTE), sessions)
    (found,) = check_records(ES_MINUTES, bars, sessions).breaks_with_bars

    assert found.describe() == (
        "synthetic/ohlcv-1m/root=ES bars in a break: the break after the trade date 2026-03-06 "
        "holds 61 bars, one closing at the next session's open, as a stretch a platform stamped "
        "early holds; the sessions beside, 1,741 records of the trade dates 2026-03-06, "
        "2026-03-09"
    )


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
    # part's span, not each session's bars, decides that its hours count (ADR-0022). The check
    # words the hour as 30 minutes, the smallest move that puts every hourly bar inside its
    # session, as before step 5.15 (BACKLOG).
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


def an_hour_early_after_the_spring_change(sessions: SessionTable) -> list[int]:
    """The minutes of whole sessions from 2026-03-02 to 03-06, then of the first 300 minutes of
    03-09 an hour early, as times kept in standard time across the clock change of 03-08 give
    of a file that ends inside that session."""
    days = sessions.between(date(2026, 3, 2), MARCH_6).select("open", "close")
    opened = sessions.session(MARCH_9).open
    whole = [minute for start, end in days.rows() for minute in range(start, end, MINUTE)]
    return [*whole, *range(opened - HOUR, opened + 240 * MINUTE, MINUTE)]


def test_a_part_an_hour_early_whose_bars_reach_no_open_shows_that_offset(
    sessions: SessionTable,
) -> None:
    # Gap 1 of the step's review (D-104): the part after the change spans no whole session,
    # and the 60th minute of 03-09 had no trade, so no bar of the part closes at the open. No
    # break explains its hours, which count, as before step 5.15; the part of your MNQ 03-24,
    # whose bars reach the open, reads as bars in a break.
    reaching = sessions.session(MARCH_9).open - MINUTE
    opens = [each for each in an_hour_early_after_the_spring_change(sessions) if each != reaching]

    assert offsets(ES_MINUTES, generated(opens, MINUTE, sessions), sessions) == [
        (-HOUR, OffsetCause.TIME_ZONE, MARCH_9, MARCH_9)
    ]


def test_trades_a_part_an_hour_early_show_that_offset(sessions: SessionTable) -> None:
    # Gap 1: no trade is a bar in a break, so the hours of a part of a file of trades count
    # however few sessions it spans, as before step 5.15.
    prints = pl.DataFrame(
        {"ts_recv": an_hour_early_after_the_spring_change(sessions)}, schema={"ts_recv": pl.Int64}
    )
    trades = sessions.assign_trade_dates_or_previous(prints, "ts_recv").drop("in_session")

    assert offsets(ES_TRADES, trades.lazy(), sessions) == [
        (-HOUR, OffsetCause.TIME_ZONE, MARCH_9, MARCH_9)
    ]


def test_a_session_a_bar_early_before_a_bar_at_the_next_open_shows_that_offset(
    sessions: SessionTable,
) -> None:
    # Engine review, finding 2 (D-104): from 02-03 on the bars run a bar early, as two exports
    # joined give, but the first minutes of 02-03 and 02-04 had no trade, so only 02-05 opens
    # after a bar closing at its open, and the file ends inside it. 02-04, the session before
    # that bar, holds no bar in its last bucket and one in the bucket before, as a session a
    # bar early does. Read as bars in a break, the correction would leave out 02-04 and 02-05
    # and store 02-03 a bar early.
    monday, tuesday, wednesday, thursday = (
        sessions.session(date(2026, 2, day)) for day in (2, 3, 4, 5)
    )
    unheaded = [
        minute
        for session in (tuesday, wednesday)
        for minute in range(session.open + MINUTE, session.close, MINUTE)
    ]
    ending = range(thursday.open, thursday.open + 300 * MINUTE, MINUTE)
    early = [minute - MINUTE for minute in [*unheaded, *ending]]
    opens = [*range(monday.open, monday.close, MINUTE), *early]

    assert offsets(ES_MINUTES, generated(opens, MINUTE, sessions), sessions) == [
        (-MINUTE, OffsetCause.BAR_STAMPING, date(2026, 2, 2), date(2026, 2, 5))
    ]
