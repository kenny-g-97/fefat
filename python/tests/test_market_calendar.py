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
    Calendar,
    CalendarId,
    EarlyClose,
    FullClose,
    Session,
    SessionHours,
    SessionTable,
    Weekday,
    build_sessions,
    sessions_of,
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
]


@pytest.fixture(scope="module")
def tables(tmp_path_factory: pytest.TempPathFactory) -> dict[CalendarId, SessionTable]:
    cache_folder = tmp_path_factory.mktemp("cache")
    return {
        identity: sessions_of(calendar, cache_folder) for identity, calendar in BUILT_IN.items()
    }


@pytest.mark.parametrize(("calendar_id", "trade_date", "opens", "closes"), GOLDEN_SESSIONS)
def test_golden_sessions(
    tables: dict[CalendarId, SessionTable],
    calendar_id: CalendarId,
    trade_date: date,
    opens: int,
    closes: int,
) -> None:
    session = tables[calendar_id].session(trade_date)

    assert session == Session(trade_date=trade_date, open=opens, close=closes)


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
        (date(2026, 3, 4), utc(2026, 3, 4), utc(2026, 3, 4, 12)),
        (date(2026, 3, 5), utc(2026, 3, 5), utc(2026, 3, 6)),
    ]


def test_a_session_that_closes_before_it_opens_is_refused() -> None:
    with pytest.raises(ValueError, match="to close after it opens"):
        Session(trade_date=date(2026, 3, 9), open=utc(2026, 3, 9, 21), close=utc(2026, 3, 8, 22))


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
        (date(2026, 7, 2), utc(2026, 7, 2, 13, 30), utc(2026, 7, 2, 20)),
        (date(2026, 7, 6), utc(2026, 7, 6, 13, 30), utc(2026, 7, 6, 20)),
    ]
    assert autumn.rows() == [(date(2026, 11, 27), utc(2026, 11, 27, 14, 30), utc(2026, 11, 27, 18))]


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
