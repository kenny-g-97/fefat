import shutil
from datetime import UTC, date, datetime, time
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market import calendar as calendar_module
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import (
    FIRST_SESSION_DATE,
    LAST_SESSION_DATE,
    HaltWindow,
    Session,
    SessionTable,
    build_sessions,
    sessions_of,
)
from fefat.market.calendar_definition import (
    Calendar,
    CalendarId,
    EarlyClose,
    FormerClose,
    FormerDailyHalt,
    FullClose,
    Halt,
    SessionHours,
    Weekday,
)

EQUITY_INDEX = CalendarId.CME_EQUITY_INDEX
ENERGY = CalendarId.CME_ENERGY
METALS = CalendarId.CME_METALS
CRYPTO = CalendarId.CRYPTO_24X7
A_SOURCE = "https://www.example.com/holiday-notice"


def utc(*fields: int) -> int:
    """The instant of a UTC date and time, in nanoseconds since the Unix epoch."""
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def halt(start: int, end: int) -> HaltWindow:
    return HaltWindow(start=start, end=end)


NO_HALTS: tuple[HaltWindow, ...] = ()


# Golden sessions, computed by hand. CME Globex trades from 17:00 Chicago on the evening before
# a trade date to 16:00 Chicago on it. Chicago keeps CST (UTC-6) in winter and CDT (UTC-5) from
# the second Sunday of March at 02:00 to the first Sunday of November at 02:00: 2025-03-09 to
# 2025-11-02 and 2026-03-08 to 2026-11-01. So 17:00 is 23:00 UTC in CST and 22:00 UTC in CDT,
# and 16:00 is 22:00 UTC in CST and 21:00 UTC in CDT.
GOLDEN_SESSIONS = [
    # The spring-forward week of 2026. Friday 03-06 is still CST: it opens on Thursday at 17:00
    # CST, 23:00 UTC, and closes at 16:00 CST, 22:00 UTC.
    (EQUITY_INDEX, date(2026, 3, 6), utc(2026, 3, 5, 23), utc(2026, 3, 6, 22)),
    # Monday 03-09 opens on Sunday 03-08 at 17:00, after the clocks moved at 02:00 that
    # morning: 17:00 CDT is 22:00 UTC, an hour earlier in UTC than the Friday before. It closes
    # at 16:00 CDT, 21:00 UTC.
    (EQUITY_INDEX, date(2026, 3, 9), utc(2026, 3, 8, 22), utc(2026, 3, 9, 21)),
    # Tuesday 03-10 opens on Monday at 17:00 CDT, 22:00 UTC, and closes at 21:00 UTC.
    (EQUITY_INDEX, date(2026, 3, 10), utc(2026, 3, 9, 22), utc(2026, 3, 10, 21)),
    # A Sunday open in standard time: Monday 2026-02-02 opens on Sunday at 17:00 CST, 23:00 UTC,
    # and closes at 16:00 CST, 22:00 UTC.
    (EQUITY_INDEX, date(2026, 2, 2), utc(2026, 2, 1, 23), utc(2026, 2, 2, 22)),
    # Thanksgiving week of 2025, all CST. Wednesday 11-26 is a regular day: Tuesday 17:00, 23:00
    # UTC, to 16:00, 22:00 UTC.
    (EQUITY_INDEX, date(2025, 11, 26), utc(2025, 11, 25, 23), utc(2025, 11, 26, 22)),
    # Thanksgiving Thursday 11-27 trades until a midday halt but has no trade date of its own:
    # its trading belongs to Friday 11-28, whose session opens on Wednesday at 17:00 CST, 23:00
    # UTC, and closes early on Friday at 12:15 CST for equity index, 18:15 UTC, ...
    (EQUITY_INDEX, date(2025, 11, 28), utc(2025, 11, 26, 23), utc(2025, 11, 28, 18, 15)),
    # ... and at 13:45 CST for energy and metals, 19:45 UTC.
    (ENERGY, date(2025, 11, 28), utc(2025, 11, 26, 23), utc(2025, 11, 28, 19, 45)),
    (METALS, date(2025, 11, 28), utc(2025, 11, 26, 23), utc(2025, 11, 28, 19, 45)),
    # Monday 12-01 opens on Sunday 11-30 at 17:00 CST, 23:00 UTC.
    (EQUITY_INDEX, date(2025, 12, 1), utc(2025, 11, 30, 23), utc(2025, 12, 1, 22)),
    # Juneteenth 2026, all CDT. Thursday 06-18, the day the June equity index contracts expired
    # because Friday was the holiday, is a regular day: Wednesday 17:00 CDT, 22:00 UTC, to 16:00
    # CDT, 21:00 UTC.
    (EQUITY_INDEX, date(2026, 6, 18), utc(2026, 6, 17, 22), utc(2026, 6, 18, 21)),
    # Friday 06-19 trades until a midday halt, and since that day CME gives a Friday holiday's
    # trades the next trade date: Monday 06-22, whose session opens on Thursday 06-18 at 17:00
    # CDT, 22:00 UTC, and closes on Monday at 16:00 CDT, 21:00 UTC.
    (EQUITY_INDEX, date(2026, 6, 22), utc(2026, 6, 18, 22), utc(2026, 6, 22, 21)),
    (ENERGY, date(2026, 6, 22), utc(2026, 6, 18, 22), utc(2026, 6, 22, 21)),
    (METALS, date(2026, 6, 22), utc(2026, 6, 18, 22), utc(2026, 6, 22, 21)),
    # Christmas 2025, all CST. Christmas Eve, Wednesday 12-24, closes early: at 12:15 CST for
    # equity index, 18:15 UTC, and 12:45 CST for energy, 18:45 UTC. Christmas Day is a full
    # close, so no session opens on the evening of the 24th: Friday 12-26 opens on Thursday
    # 12-25 at 17:00 CST, 23:00 UTC.
    (EQUITY_INDEX, date(2025, 12, 24), utc(2025, 12, 23, 23), utc(2025, 12, 24, 18, 15)),
    (ENERGY, date(2025, 12, 24), utc(2025, 12, 23, 23), utc(2025, 12, 24, 18, 45)),
    (ENERGY, date(2025, 12, 26), utc(2025, 12, 25, 23), utc(2025, 12, 26, 22)),
    # Good Friday 2026, CDT, with the March jobs report out that morning. Equity index trades a
    # short session with its own trade date, from Thursday 17:00 CDT, 22:00 UTC, to 08:15 CDT,
    # 13:15 UTC; energy is closed, so its Monday 04-06 session opens on Sunday at 17:00 CDT.
    (EQUITY_INDEX, date(2026, 4, 3), utc(2026, 4, 2, 22), utc(2026, 4, 3, 13, 15)),
    (ENERGY, date(2026, 4, 6), utc(2026, 4, 5, 22), utc(2026, 4, 6, 21)),
    # A crypto UTC day, Saturday 2026-03-07, from 00:00 UTC to 00:00 UTC on Sunday.
    (CRYPTO, date(2026, 3, 7), utc(2026, 3, 7), utc(2026, 3, 8)),
    # Until CME moved the daily maintenance 15 minutes earlier for trade date Monday 2015-09-21,
    # equity index, energy, and metals closed at 16:15 Chicago. Friday 2015-09-18, CDT, opens on
    # Thursday at 17:00 CDT, 22:00 UTC, and closes at 16:15 CDT, 21:15 UTC; Monday 09-21 opens
    # on Sunday at 22:00 UTC and closes at 16:00 CDT, 21:00 UTC.
    (METALS, date(2015, 9, 18), utc(2015, 9, 17, 22), utc(2015, 9, 18, 21, 15)),
    (METALS, date(2015, 9, 21), utc(2015, 9, 20, 22), utc(2015, 9, 21, 21)),
    (EQUITY_INDEX, date(2015, 9, 18), utc(2015, 9, 17, 22), utc(2015, 9, 18, 21, 15)),
    (ENERGY, date(2015, 9, 21), utc(2015, 9, 20, 22), utc(2015, 9, 21, 21)),
    # Independence Day 2026 is a Saturday, observed on Friday 07-03 with a halt. Thursday 07-02,
    # CDT, trades in full, from Wednesday 17:00, 22:00 UTC, to 16:00, 21:00 UTC: MES and MNQ
    # printed until 16:00 that day. In 2025, Thursday 07-03 closed early, at 12:15 CDT, 17:15 UTC.
    (EQUITY_INDEX, date(2026, 7, 2), utc(2026, 7, 1, 22), utc(2026, 7, 2, 21)),
    (EQUITY_INDEX, date(2025, 7, 3), utc(2025, 7, 2, 22), utc(2025, 7, 3, 17, 15)),
    # The day after Thanksgiving 2023, Friday 11-24, CST: energy and metals closed at 12:45 CST,
    # 18:45 UTC, an hour before the 13:45 close of 2024 on.
    (ENERGY, date(2023, 11, 24), utc(2023, 11, 22, 23), utc(2023, 11, 24, 18, 45)),
]


# Golden halts, computed by hand in the same way. A halt day's hours from its halt to the next
# open lie inside the next trade date's session, and equity index halted from 15:15 to 15:30
# Chicago inside every session until trade date 2021-06-28.
GOLDEN_HALTS = [
    # Thanksgiving 2025, CST: equity index halts at 12:00, 18:00 UTC, and reopens at 17:00, 23:00
    # UTC, for Friday 11-28; energy and metals halt at 13:30, 19:30 UTC, as they do since 2022.
    (EQUITY_INDEX, date(2025, 11, 28), (halt(utc(2025, 11, 27, 18), utc(2025, 11, 27, 23)),)),
    (ENERGY, date(2025, 11, 28), (halt(utc(2025, 11, 27, 19, 30), utc(2025, 11, 27, 23)),)),
    (METALS, date(2025, 11, 28), (halt(utc(2025, 11, 27, 19, 30), utc(2025, 11, 27, 23)),)),
    # Juneteenth 2026, a Friday, CDT: every group halts at 12:00, 17:00 UTC, and reopens on Sunday
    # 06-21 at 17:00, 22:00 UTC, for Monday 06-22.
    (EQUITY_INDEX, date(2026, 6, 22), (halt(utc(2026, 6, 19, 17), utc(2026, 6, 21, 22)),)),
    (ENERGY, date(2026, 6, 22), (halt(utc(2026, 6, 19, 17), utc(2026, 6, 21, 22)),)),
    (METALS, date(2026, 6, 22), (halt(utc(2026, 6, 19, 17), utc(2026, 6, 21, 22)),)),
    # Thanksgiving 2023, CST: energy halts at 13:30, 19:30 UTC.
    (ENERGY, date(2023, 11, 24), (halt(utc(2023, 11, 23, 19, 30), utc(2023, 11, 23, 23)),)),
    # Martin Luther King Jr. Day 2021, CST: metals halted at 12:00, 18:00 UTC, before 2022.
    (METALS, date(2021, 1, 19), (halt(utc(2021, 1, 18, 18), utc(2021, 1, 18, 23)),)),
    # Labor Day 2011, CDT: metals halted at 12:15, 17:15 UTC, and reopened at 17:00, 22:00 UTC.
    (METALS, date(2011, 9, 6), (halt(utc(2011, 9, 5, 17, 15), utc(2011, 9, 5, 22)),)),
    # Friday 2021-06-25, CDT: equity index's last daily halt, 15:15 to 15:30, 20:15 to 20:30 UTC;
    # none from Monday 06-28, and never in energy and metals.
    (EQUITY_INDEX, date(2021, 6, 25), (halt(utc(2021, 6, 25, 20, 15), utc(2021, 6, 25, 20, 30)),)),
    (EQUITY_INDEX, date(2021, 6, 28), NO_HALTS),
    (METALS, date(2021, 6, 25), NO_HALTS),
    # Friday 2015-09-18, CDT, closing at 16:15: the daily halt lies inside the session.
    (EQUITY_INDEX, date(2015, 9, 18), (halt(utc(2015, 9, 18, 20, 15), utc(2015, 9, 18, 20, 30)),)),
    # Friday 2020-11-27, CST, closes at 12:15, before the daily halt; Thanksgiving's halt from
    # 12:00 to 17:00, 18:00 to 23:00 UTC, lies inside its session.
    (EQUITY_INDEX, date(2020, 11, 27), (halt(utc(2020, 11, 26, 18), utc(2020, 11, 26, 23)),)),
    # A regular day of 2026, and a crypto UTC day.
    (EQUITY_INDEX, date(2026, 3, 9), NO_HALTS),
    (CRYPTO, date(2026, 3, 7), NO_HALTS),
]


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> dict[CalendarId, SessionTable]:
    cache_folder = tmp_path_factory.mktemp("cache")
    return {
        identity: sessions_of(calendar, cache_folder) for identity, calendar in BUILT_IN.items()
    }


HALTS_OF_GOLDEN_SESSIONS = {
    (calendar_id, trade_date): halts for calendar_id, trade_date, halts in GOLDEN_HALTS
}
"""The golden halts by session; every other golden session has none."""


@pytest.mark.parametrize(("calendar_id", "trade_date", "opens", "closes"), GOLDEN_SESSIONS)
def test_golden_sessions(
    tables: dict[CalendarId, SessionTable],
    calendar_id: CalendarId,
    trade_date: date,
    opens: int,
    closes: int,
) -> None:
    session = tables[calendar_id].session(trade_date)

    halts = HALTS_OF_GOLDEN_SESSIONS.get((calendar_id, trade_date), NO_HALTS)
    assert session == Session(trade_date=trade_date, open=opens, close=closes, halts=halts)


@pytest.mark.parametrize(("calendar_id", "trade_date", "halts"), GOLDEN_HALTS)
def test_golden_halts(
    tables: dict[CalendarId, SessionTable],
    calendar_id: CalendarId,
    trade_date: date,
    halts: tuple[HaltWindow, ...],
) -> None:
    assert tables[calendar_id].session(trade_date).halts == halts


@pytest.mark.parametrize(
    ("calendar_id", "holiday", "kind"),
    [
        (EQUITY_INDEX, date(2025, 11, 27), "halt"),
        (ENERGY, date(2025, 11, 27), "halt"),
        (EQUITY_INDEX, date(2026, 6, 19), "halt"),
        (METALS, date(2026, 6, 19), "halt"),
        (EQUITY_INDEX, date(2025, 12, 25), "full-close"),
        (ENERGY, date(2026, 1, 1), "full-close"),
    ],
)
def test_a_holiday_without_a_trade_date_of_its_own_has_no_session(
    tables: dict[CalendarId, SessionTable], calendar_id: CalendarId, holiday: date, kind: str
) -> None:
    with pytest.raises(ValueError, match=f"got {holiday}, a {kind} holiday"):
        tables[calendar_id].session(holiday)


def test_the_session_following_a_trade_date_is_the_next_trade_dates(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Friday 2026-03-06 is followed by Monday 03-09, which opens on Sunday at 17:00 CDT, 22:00
    # UTC, and Wednesday 2025-11-26 by Friday 11-28, Thanksgiving having no trade date.
    equity_index = tables[EQUITY_INDEX]

    assert equity_index.following(date(2026, 3, 6)).trade_date == date(2026, 3, 9)
    assert equity_index.following(date(2026, 3, 6)).open == utc(2026, 3, 8, 22)
    assert equity_index.following(date(2025, 11, 26)).trade_date == date(2025, 11, 28)
    with pytest.raises(ValueError, match="after 2030-12-31, got none in its session table"):
        equity_index.following(LAST_SESSION_DATE)


def test_the_session_preceding_a_trade_date_is_the_previous_trade_dates(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Monday 2026-03-09 is preceded by Friday 03-06, which opens on Thursday at 17:00 CST, 23:00
    # UTC, and New Year's Day 2026, a full close, by Wednesday 2025-12-31.
    equity_index = tables[EQUITY_INDEX]

    assert equity_index.preceding(date(2026, 3, 9)).trade_date == date(2026, 3, 6)
    assert equity_index.preceding(date(2026, 3, 9)).open == utc(2026, 3, 5, 23)
    assert equity_index.preceding(date(2026, 1, 1)).trade_date == date(2025, 12, 31)
    with pytest.raises(ValueError, match="before 2010-01-04, got none in its session table"):
        equity_index.preceding(date(2010, 1, 4))


def test_each_sessions_break_ends_at_the_next_sessions_open(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # Thursday 2026-03-05's break ends when Friday 03-06 opens, at 23:00 UTC, and Friday's when
    # Monday 03-09 opens on Sunday at 22:00 UTC, after the last trade date asked.
    sessions = tables[EQUITY_INDEX].between_with_next_opens(date(2026, 3, 5), date(2026, 3, 6))

    assert sessions.select("trade_date", "next_open").rows() == [
        (date(2026, 3, 5), utc(2026, 3, 5, 23)),
        (date(2026, 3, 6), utc(2026, 3, 8, 22)),
    ]


def test_a_weekend_day_and_a_day_outside_the_table_have_no_session(
    tables: dict[CalendarId, SessionTable],
) -> None:
    with pytest.raises(ValueError, match="got 2026-03-07, a Saturday"):
        tables[EQUITY_INDEX].session(date(2026, 3, 7))
    with pytest.raises(ValueError, match="the span of the session table"):
        tables[EQUITY_INDEX].session(date(2031, 1, 6))


def test_instants_get_the_trade_date_of_the_session_they_fall_in(
    tables: dict[CalendarId, SessionTable],
) -> None:
    received = pl.DataFrame(
        {
            # 2026-03-08 22:00 UTC is the first instant of Monday 03-09's session (17:00 CDT on
            # Sunday); 2025-11-27 16:00 UTC is 10:00 CST on Thanksgiving, whose trading belongs
            # to Friday 11-28; 2026-06-22 20:59 UTC is 15:59 CDT, inside Monday 06-22's session.
            "ts_recv": [utc(2026, 6, 22, 20, 59), utc(2026, 3, 8, 22), utc(2025, 11, 27, 16)],
            "size": [3, 1, 2],
        }
    )

    assigned = tables[EQUITY_INDEX].assign_trade_dates(received, "ts_recv")

    expected = pl.DataFrame(
        {
            "ts_recv": [utc(2025, 11, 27, 16), utc(2026, 3, 8, 22), utc(2026, 6, 22, 20, 59)],
            "size": [2, 1, 3],
            "trade_date": [date(2025, 11, 28), date(2026, 3, 9), date(2026, 6, 22)],
        }
    )
    assert_frame_equal(assigned, expected)


def test_instants_received_at_the_same_time_keep_their_order(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # The prints of one event share their ts_recv, and bars take their open and close from the
    # first and last print, so equal instants keep the order they came in (D-36). Several
    # hundred rows in falling order, four to an instant, since a sort of twenty rows or fewer
    # keeps ties in order whatever it is asked.
    same = utc(2026, 3, 9, 15)
    offsets = [(399 - row) // 4 for row in range(400)]
    received = pl.DataFrame(
        {"ts_recv": [same + offset for offset in offsets], "sequence": range(400)}
    )

    assigned = tables[EQUITY_INDEX].assign_trade_dates(received, "ts_recv")

    in_order = sorted(range(400), key=lambda row: offsets[row])
    assert assigned.get_column("sequence").to_list() == in_order


@pytest.mark.parametrize(
    ("instant", "text"),
    [
        # 16:30 CDT on Tuesday 2026-03-10, in the daily break between 16:00 and 17:00.
        (utc(2026, 3, 10, 21, 30), "2026-03-10T21:30:00Z"),
        # Saturday noon, between Friday's close and Sunday's open.
        (utc(2026, 3, 7, 12), "2026-03-07T12:00:00Z"),
    ],
)
def test_an_instant_outside_every_session_is_refused(
    tables: dict[CalendarId, SessionTable], instant: int, text: str
) -> None:
    received = pl.DataFrame({"ts_recv": [utc(2026, 3, 9, 15), instant]})

    with pytest.raises(ValueError, match=f"got 1 outside, the first at {text}"):
        tables[EQUITY_INDEX].assign_trade_dates(received, "ts_recv")


def test_assigning_trade_dates_needs_int64_instants_and_no_trade_date_yet(
    tables: dict[CalendarId, SessionTable],
) -> None:
    unsigned = pl.DataFrame({"ts_recv": [utc(2026, 3, 9, 15)]}, schema={"ts_recv": pl.UInt64})
    dated = pl.DataFrame({"ts_recv": [utc(2026, 3, 9, 15)], "trade_date": [date(2026, 3, 9)]})

    with pytest.raises(ValueError, match="Expected an Int64 column 'ts_recv'"):
        tables[EQUITY_INDEX].assign_trade_dates(unsigned, "ts_recv")
    with pytest.raises(ValueError, match="without a trade_date column"):
        tables[EQUITY_INDEX].assign_trade_dates(dated, "ts_recv")


def every_day() -> frozenset[Weekday]:
    return frozenset(Weekday)


def test_an_unknown_time_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected an IANA time zone"):
        SessionHours(
            time_zone="America/Chicag",
            opens_at=time(17),
            closes_at=time(16),
            opens_on_previous_day=True,
            weekdays=every_day(),
        )


def test_hours_whose_sessions_would_overlap_the_next_are_refused() -> None:
    with pytest.raises(ValueError, match="Expected the close at or before the open"):
        SessionHours(
            time_zone="America/Chicago",
            opens_at=time(17),
            closes_at=time(17, 30),
            opens_on_previous_day=True,
            weekdays=every_day(),
        )


def test_a_local_open_that_the_clock_change_skips_is_refused() -> None:
    # On 2026-03-08 Chicago's clocks jump from 02:00 CST to 03:00 CDT, so 02:30 never happens.
    early_birds = Calendar(
        name="early-birds",
        hours=SessionHours(
            time_zone="America/Chicago",
            opens_at=time(2, 30),
            closes_at=time(16),
            opens_on_previous_day=False,
            weekdays=every_day(),
        ),
        holidays=(),
    )

    with pytest.raises(ValueError, match="2026-03-08 02:30:00' is non-existent"):
        build_sessions(early_birds, date(2026, 3, 8), date(2026, 3, 8))


def test_holidays_must_be_one_a_day_on_the_calendars_weekdays() -> None:
    hours = BUILT_IN[EQUITY_INDEX].hours
    twice = (
        FullClose(day=date(2026, 12, 25), source=A_SOURCE),
        EarlyClose(day=date(2026, 12, 25), closes_at=time(12), source=A_SOURCE),
    )

    with pytest.raises(
        ValueError, match="at most one holiday a day in twice, got several on 2026-12-25"
    ):
        Calendar(name="twice", hours=hours, holidays=twice)
    with pytest.raises(ValueError, match="got 2026-07-04, a Saturday"):
        Calendar(
            name="weekend",
            hours=hours,
            holidays=(FullClose(day=date(2026, 7, 4), source=A_SOURCE),),
        )


def test_an_early_close_after_the_regular_close_is_refused() -> None:
    # 18:00 CST on Wednesday 2026-03-04 is two hours after the regular 16:00 close, and after
    # the next session opens at 17:00.
    late = Calendar(
        name="late-close",
        hours=BUILT_IN[EQUITY_INDEX].hours,
        holidays=(EarlyClose(day=date(2026, 3, 4), closes_at=time(18), source=A_SOURCE),),
    )

    with pytest.raises(ValueError, match="Expected the early close of late-close on 2026-03-04"):
        build_sessions(late, date(2026, 3, 2), date(2026, 3, 6))


def test_an_early_close_of_a_utc_day_falls_on_its_trade_date() -> None:
    # A UTC day runs from 00:00 to 00:00 the next day, so an early close at 12:00 ends the
    # session at noon of the trade date itself, not of the day after.
    half_day = Calendar(
        name="half-day",
        hours=BUILT_IN[CRYPTO].hours,
        holidays=(EarlyClose(day=date(2026, 3, 4), closes_at=time(12), source=A_SOURCE),),
    )

    sessions = build_sessions(half_day, date(2026, 3, 4), date(2026, 3, 5))

    assert sessions.rows() == [
        (date(2026, 3, 4), utc(2026, 3, 4), utc(2026, 3, 4, 12), []),
        (date(2026, 3, 5), utc(2026, 3, 5), utc(2026, 3, 6), []),
    ]


def test_a_session_that_closes_before_it_opens_is_refused() -> None:
    with pytest.raises(ValueError, match="to close after it opens"):
        Session(trade_date=date(2026, 3, 9), open=utc(2026, 3, 9, 21), close=utc(2026, 3, 8, 22))


def test_a_former_close_holds_for_the_trade_dates_before_its_end() -> None:
    # A calendar that closed at 16:15 until 2015-09-21 and at 16:00 since, with an early close at
    # 12:15 on Friday 2015-09-18 that keeps its own time.
    moved = Calendar(
        name="moved-close",
        hours=BUILT_IN[EQUITY_INDEX].hours,
        holidays=(EarlyClose(day=date(2015, 9, 18), closes_at=time(12, 15), source=A_SOURCE),),
        former_closes=(
            FormerClose(until=date(2015, 9, 21), closes_at=time(16, 15), source=A_SOURCE),
        ),
    )

    sessions = build_sessions(moved, date(2015, 9, 17), date(2015, 9, 21))

    assert sessions.get_column("close").to_list() == [
        utc(2015, 9, 17, 21, 15),
        utc(2015, 9, 18, 17, 15),
        utc(2015, 9, 21, 21),
    ]


def test_a_former_close_after_the_next_open_or_two_on_one_day_are_refused() -> None:
    hours = BUILT_IN[EQUITY_INDEX].hours
    late = FormerClose(until=date(2015, 9, 21), closes_at=time(17, 30), source=A_SOURCE)
    twice = FormerClose(until=date(2015, 9, 21), closes_at=time(16, 15), source=A_SOURCE)

    with pytest.raises(ValueError, match="Expected the former close of late at or before"):
        Calendar(name="late", hours=hours, holidays=(), former_closes=(late,))
    with pytest.raises(ValueError, match="Expected one former close ending on each day"):
        Calendar(name="twice", hours=hours, holidays=(), former_closes=(twice, twice))


def test_a_generic_calendar_of_a_traders_product_gives_its_sessions() -> None:
    # A product traded 09:30 to 16:00 New York time, Monday to Friday, closed on Friday
    # 2026-07-03 and closing at 13:00 on Friday 2026-11-27. New York keeps EDT (UTC-4) from
    # 2026-03-08 to 2026-11-01 and EST (UTC-5) after: 09:30 EDT is 13:30 UTC and 16:00 EDT 20:00
    # UTC; 09:30 EST is 14:30 UTC and 13:00 EST 18:00 UTC.
    weekdays = frozenset(
        {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
    )
    new_york_cash = Calendar(
        name="new-york-cash",
        hours=SessionHours(
            time_zone="America/New_York",
            opens_at=time(9, 30),
            closes_at=time(16),
            opens_on_previous_day=False,
            weekdays=weekdays,
        ),
        holidays=(
            FullClose(day=date(2026, 7, 3), source=A_SOURCE),
            EarlyClose(day=date(2026, 11, 27), closes_at=time(13), source=A_SOURCE),
        ),
    )

    summer = build_sessions(new_york_cash, date(2026, 7, 2), date(2026, 7, 6))
    autumn = build_sessions(new_york_cash, date(2026, 11, 27), date(2026, 11, 27))

    assert summer.rows() == [
        (date(2026, 7, 2), utc(2026, 7, 2, 13, 30), utc(2026, 7, 2, 20), []),
        (date(2026, 7, 6), utc(2026, 7, 6, 13, 30), utc(2026, 7, 6, 20), []),
    ]
    assert autumn.rows() == [
        (date(2026, 11, 27), utc(2026, 11, 27, 14, 30), utc(2026, 11, 27, 18), [])
    ]


def new_york_cash_hours() -> SessionHours:
    weekdays = frozenset(
        {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
    )
    return SessionHours(
        time_zone="America/New_York",
        opens_at=time(9, 30),
        closes_at=time(16),
        opens_on_previous_day=False,
        weekdays=weekdays,
    )


def test_the_halt_of_a_session_opening_on_its_trade_date_lasts_until_the_next_open() -> None:
    # Hours of 09:30 to 16:00 New York time, in EST (UTC-5) after 2026-11-01, with a halt at
    # 13:00 on Thursday 11-26: Friday 11-27's session opens on Thursday at 09:30, 14:30 UTC, and
    # holds the halt from 13:00, 18:00 UTC, to Friday's open at 09:30, 14:30 UTC.
    halting = Calendar(
        name="halting",
        hours=new_york_cash_hours(),
        holidays=(Halt(day=date(2026, 11, 26), closes_at=time(13), source=A_SOURCE),),
    )

    sessions = build_sessions(halting, date(2026, 11, 25), date(2026, 11, 27))

    assert sessions.rows() == [
        (date(2026, 11, 25), utc(2026, 11, 25, 14, 30), utc(2026, 11, 25, 21), []),
        (
            date(2026, 11, 27),
            utc(2026, 11, 26, 14, 30),
            utc(2026, 11, 27, 21),
            [{"start": utc(2026, 11, 26, 18), "end": utc(2026, 11, 27, 14, 30)}],
        ),
    ]


def test_a_halt_outside_its_session_is_refused() -> None:
    # A halt at 09:00 on Thursday 2026-11-26, before that day's 09:30 open.
    early = Calendar(
        name="early-halt",
        hours=new_york_cash_hours(),
        holidays=(Halt(day=date(2026, 11, 26), closes_at=time(9), source=A_SOURCE),),
    )

    with pytest.raises(ValueError, match="Expected the halts of early-halt inside their sessions"):
        build_sessions(early, date(2026, 11, 25), date(2026, 11, 27))


def test_halts_that_overlap_are_refused() -> None:
    # Two daily halts, 12:00 to 13:00 and 12:30 to 13:30 New York time: the grid reads each
    # session's halts one after another, so they must be apart.
    overlapping = Calendar(
        name="overlapping",
        hours=new_york_cash_hours(),
        holidays=(),
        former_daily_halts=tuple(
            FormerDailyHalt(until=date(2027, 1, 4), halts_at=start, resumes_at=end, source=A_SOURCE)
            for start, end in ((time(12), time(13)), (time(12, 30), time(13, 30)))
        ),
    )

    with pytest.raises(ValueError, match="and apart from each other, got one from"):
        build_sessions(overlapping, date(2026, 11, 25), date(2026, 11, 25))


def test_a_daily_halt_that_resumes_before_it_halts_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected a daily halt to resume after it halts"):
        FormerDailyHalt(
            until=date(2021, 6, 28),
            halts_at=time(15, 30),
            resumes_at=time(15, 15),
            source=A_SOURCE,
        )


@pytest.mark.parametrize("calendar_id", list(CalendarId))
def test_every_built_in_table_holds_ordered_sessions_on_trade_dates_only(
    calendar_id: CalendarId,
) -> None:
    calendar = BUILT_IN[calendar_id]
    sessions = build_sessions(calendar, FIRST_SESSION_DATE, LAST_SESSION_DATE)
    trade_dates = sessions.get_column("trade_date")
    opens, closes = sessions.get_column("open"), sessions.get_column("close")
    without_a_session = {
        holiday.day for holiday in calendar.holidays if holiday.kind in ("full-close", "halt")
    }

    assert trade_dates.is_sorted() and trade_dates.is_unique().all()
    assert (opens < closes).all()
    assert (closes.slice(0, len(closes) - 1) <= opens.slice(1)).all()
    assert set(trade_dates.dt.weekday().unique().to_list()) <= set(calendar.hours.weekdays)
    assert without_a_session.isdisjoint(trade_dates.to_list())


def cached_tables(cache_folder: Path) -> list[Path]:
    return sorted((cache_folder / "calendar").glob("*.parquet"))


def test_a_session_table_is_built_once_and_then_read_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = BUILT_IN[EQUITY_INDEX]
    sessions_of(calendar, tmp_path)
    written = cached_tables(tmp_path)

    def no_rebuild(*_: object) -> pl.DataFrame:
        raise AssertionError("Expected the cached session table, got a rebuild.")

    monkeypatch.setattr(calendar_module, "build_sessions", no_rebuild)
    cached = sessions_of(calendar, tmp_path)

    assert [path.name[: len("cme-equity-index-")] for path in written] == ["cme-equity-index-"]
    assert cached_tables(tmp_path) == written
    assert_frame_equal(
        pl.read_parquet(written[0]),
        build_sessions(calendar, FIRST_SESSION_DATE, LAST_SESSION_DATE),
    )
    assert cached.session(date(2026, 3, 9)).open == utc(2026, 3, 8, 22)


def test_a_changed_holiday_builds_a_new_session_table(tmp_path: Path) -> None:
    calendar = BUILT_IN[EQUITY_INDEX]
    sessions_of(calendar, tmp_path)
    # An early close at 12:00 CST, 18:00 UTC, on Friday 2026-03-06.
    changed = Calendar(
        name=calendar.name,
        hours=calendar.hours,
        holidays=(
            *calendar.holidays,
            EarlyClose(day=date(2026, 3, 6), closes_at=time(12), source=A_SOURCE),
        ),
    )

    table = sessions_of(changed, tmp_path)

    assert len(cached_tables(tmp_path)) == 2
    assert table.session(date(2026, 3, 6)).close == utc(2026, 3, 6, 18)
    assert sessions_of(calendar, tmp_path).session(date(2026, 3, 6)).close == utc(2026, 3, 6, 22)


def test_a_changed_session_rule_builds_a_new_session_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = BUILT_IN[CRYPTO]
    sessions_of(calendar, tmp_path / "cache")
    changed_rules = tmp_path / "calendar.py"
    shutil.copyfile(calendar_module.__file__, changed_rules)
    with changed_rules.open("a", encoding="utf-8") as module:
        module.write("\n# A changed rule.\n")
    monkeypatch.setattr(calendar_module, "__file__", str(changed_rules))

    sessions_of(calendar, tmp_path / "cache")

    assert len(cached_tables(tmp_path / "cache")) == 2


def test_a_new_polars_version_builds_a_new_session_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Polars carries the time-zone database that turns local times into UTC instants.
    calendar = BUILT_IN[CRYPTO]
    sessions_of(calendar, tmp_path)
    monkeypatch.setattr(pl, "__version__", "0.0.0")

    sessions_of(calendar, tmp_path)

    assert len(cached_tables(tmp_path)) == 2


def test_an_instant_outside_every_session_takes_the_latest_session_opened_before_it(
    tables: dict[CalendarId, SessionTable],
) -> None:
    # The importer of step 1.6 dates a vendor's bars while the holiday rules of the years
    # before 2024 are unchecked, so an instant outside every session is dated, not refused.
    # Saturday noon, 2026-03-07, falls after Friday 03-06's session; 15:00 CDT on Monday 03-09,
    # 20:00 UTC, falls inside Monday's session; 5 ms after Monday's close at 16:00 CDT, 21:00
    # UTC, a print matched before the close but received after it keeps Monday; 16:30 CDT on
    # Tuesday 03-10, 21:30 UTC, falls in the daily break after Tuesday's session.
    after_the_close = utc(2026, 3, 9, 21) + 5_000_000
    received = pl.DataFrame(
        {
            "ts_recv": [
                utc(2026, 3, 10, 21, 30),
                after_the_close,
                utc(2026, 3, 7, 12),
                utc(2026, 3, 9, 20),
            ]
        }
    )

    assigned = tables[EQUITY_INDEX].assign_trade_dates_or_previous(received, "ts_recv")

    expected = pl.DataFrame(
        {
            "ts_recv": [
                utc(2026, 3, 7, 12),
                utc(2026, 3, 9, 20),
                after_the_close,
                utc(2026, 3, 10, 21, 30),
            ],
            "trade_date": [date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 9), date(2026, 3, 10)],
            "in_session": [False, True, False, False],
        }
    )
    assert_frame_equal(assigned, expected)


@pytest.mark.parametrize(
    "instant",
    [
        # Saturday 2010-01-02, before the table's first session, which opens on Sunday
        # 2010-01-03 at 17:00 CST for Monday 01-04 (01-01 is a full close).
        utc(2010, 1, 2, 12),
        # 2031-01-02, after the table's last session closes on 2030-12-31.
        utc(2031, 1, 2, 12),
    ],
)
def test_dating_by_the_latest_session_refuses_instants_beyond_the_table(
    tables: dict[CalendarId, SessionTable], instant: int
) -> None:
    received = pl.DataFrame({"ts_recv": [utc(2026, 3, 9, 15), instant]})

    with pytest.raises(
        ValueError,
        match="from its first open 2010-01-03T23:00:00Z to its last close 2030-12-31T22:00:00Z",
    ):
        tables[EQUITY_INDEX].assign_trade_dates_or_previous(received, "ts_recv")
