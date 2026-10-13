"""The built-in session calendars, keyed by `CalendarId` (`fefat.market.calendar`, D-41).

CME Globex trades the equity index, energy, and metals groups from 17:00 Chicago on the evening
before a trade date to 16:00 Chicago on it, from Sunday evening to Friday afternoon, as the
products' specification pages state (`fefat.market.instruments`). Its holidays follow the US
exchange holidays, and CME dates holiday trading by session: what trades on a halt day belongs
to the next trade date ("Day orders entered after a product's Pre-opening(s) on Sunday,
September 6th are for trade date Tuesday, September 8th", the notes of
https://www.cmegroup.com/tools-information/holiday-calendar.html), and from 2026-06-19 so does
what trades on a Friday holiday
(https://www.cmegroup.com/notices/electronic-trading/2026/06/20260615.html). The calendars date
both the same way in every year, the trade date CME Clearing used before that change too.

- Full closes, every group: New Year's Day (on the Monday when it falls on a Sunday, and not
  observed when it falls on a Saturday), Good Friday, and Christmas (on the nearest weekday).
- Halts, every group: Martin Luther King Jr. Day, Presidents' Day, Memorial Day, Juneteenth
  (from 2022), Independence Day (both on the nearest weekday), Labor Day, and Thanksgiving.
- Early closes: the day after Thanksgiving (equity index 12:15, energy and metals 13:45),
  Christmas Eve from Monday to Thursday (12:15, and 12:45), and for equity index the weekday
  before Independence Day, from Monday to Thursday (12:15).

Each rule names its source: brokers' copies of CME's holiday schedules, since cmegroup.com
refuses scripted reads. `OVERRIDES` holds the days the rules miss, each with its source; where
`fefat.market.calendar_check.validate_calendar` finds a mismatch in real data that a holiday
explains, the fix is a row there. Crypto trades around the clock, and its trade date is the UTC
day, as the venues' daily bars are.
"""

from collections.abc import Callable, Iterator, Mapping
from datetime import date, time, timedelta
from types import MappingProxyType

from fefat.market.calendar import (
    FIRST_SESSION_DATE,
    LAST_SESSION_DATE,
    Calendar,
    CalendarId,
    EarlyClose,
    FullClose,
    Halt,
    Holiday,
    SessionHours,
    Weekday,
)

DayRule = Callable[[int], tuple[date, ...]]
"""The days a holiday falls on in a year, none when it is not observed that year."""

CME_GLOBEX_HOURS = SessionHours(
    time_zone="America/Chicago",
    opens_at=time(17),
    closes_at=time(16),
    opens_on_previous_day=True,
    weekdays=frozenset(
        {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
    ),
)
CRYPTO_HOURS = SessionHours(
    time_zone="UTC",
    opens_at=time(0),
    closes_at=time(0),
    opens_on_previous_day=False,
    weekdays=frozenset(Weekday),
)

_PARAGON = "https://www.paragonglobalmarkets.com/wp-content/uploads"
_DTN = "https://iqhelp.dtn.com"
_NEW_YEARS_DAY = "https://www.ampfutures.com/news/new-year-holiday-trading-schedule-2023-2024"
_GOOD_FRIDAY = f"{_DTN}/good-friday-holiday-hours-2025/"
_CHRISTMAS = "https://www.ampfutures.com/news/christmas-holiday-trading-schedule"
_MARTIN_LUTHER_KING_JR_DAY = f"{_PARAGON}/2025/01/PGM_MLK-Holiday-Schedule_2025.pdf"
_PRESIDENTS_DAY = f"{_PARAGON}/2025/02/PGM_Presidents-Day-Holiday-Schedule_2025.pdf"
_MEMORIAL_DAY = f"{_PARAGON}/2025/05/PGM_Memorial-Day-Holiday-Schedule_2025.pdf"
_JUNETEENTH = f"{_PARAGON}/2026/06/PGM_Juneteenth-Holiday-Schedule_2026.pdf"
_INDEPENDENCE_DAY = f"{_DTN}/fourth-of-july-service-hours-2025/"
_LABOR_DAY = "https://edgeclear.com/exchange-holiday-hours/"
_THANKSGIVING = f"{_PARAGON}/2025/11/PGM_Thanksgiving-Holiday-Schedule_2025.pdf"
_CHRISTMAS_EVE = f"{_DTN}/christmas-new-year-holiday-hours-2025/"
_DAY_BEFORE_INDEPENDENCE_DAY = f"{_PARAGON}/2026/07/PGM_Independence-Day-Holiday-Schedule_2026.pdf"


def _observed(day: date) -> date:
    """A holiday on a Saturday is observed on the Friday before, one on a Sunday on the Monday
    after."""
    if day.isoweekday() == Weekday.SATURDAY:
        return day - timedelta(days=1)
    if day.isoweekday() == Weekday.SUNDAY:
        return day + timedelta(days=1)
    return day


def _monday_to_thursday(day: date) -> tuple[date, ...]:
    if day.isoweekday() <= Weekday.THURSDAY:
        return (day,)
    return ()


def _nth_weekday(year: int, month: int, weekday: Weekday, count: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.isoweekday()) % 7 + 7 * (count - 1))


def _last_weekday(year: int, month: int, weekday: Weekday) -> date:
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.isoweekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    """Easter Sunday of the Gregorian calendar, by the anonymous algorithm of 1876 (Meeus,
    Astronomical Algorithms, chapter 8)."""
    metonic_year = year % 19
    century, year_of_century = divmod(year, 100)
    leap_centuries, century_remainder = divmod(century, 4)
    lunar_shift = (century - (century + 8) // 25 + 1) // 3
    epact = (19 * metonic_year + century - leap_centuries - lunar_shift + 15) % 30
    leap_years, year_remainder = divmod(year_of_century, 4)
    weekday_shift = (32 + 2 * century_remainder + 2 * leap_years - epact - year_remainder) % 7
    correction = (metonic_year + 11 * epact + 22 * weekday_shift) // 451
    month, day = divmod(epact + weekday_shift - 7 * correction + 114, 31)
    return date(year, month, day + 1)


def _new_years_day(year: int) -> tuple[date, ...]:
    day = date(year, 1, 1)
    if day.isoweekday() == Weekday.SATURDAY:
        return ()
    return (_observed(day),)


def _good_friday(year: int) -> tuple[date, ...]:
    return (easter_sunday(year) - timedelta(days=2),)


def _christmas(year: int) -> tuple[date, ...]:
    return (_observed(date(year, 12, 25)),)


def _martin_luther_king_jr_day(year: int) -> tuple[date, ...]:
    return (_nth_weekday(year, 1, Weekday.MONDAY, 3),)


def _presidents_day(year: int) -> tuple[date, ...]:
    return (_nth_weekday(year, 2, Weekday.MONDAY, 3),)


def _memorial_day(year: int) -> tuple[date, ...]:
    return (_last_weekday(year, 5, Weekday.MONDAY),)


def _juneteenth(year: int) -> tuple[date, ...]:
    if year < 2022:
        return ()
    return (_observed(date(year, 6, 19)),)


def _independence_day(year: int) -> tuple[date, ...]:
    return (_observed(date(year, 7, 4)),)


def _labor_day(year: int) -> tuple[date, ...]:
    return (_nth_weekday(year, 9, Weekday.MONDAY, 1),)


def _thanksgiving(year: int) -> tuple[date, ...]:
    return (_nth_weekday(year, 11, Weekday.THURSDAY, 4),)


def _day_after_thanksgiving(year: int) -> tuple[date, ...]:
    return (_nth_weekday(year, 11, Weekday.THURSDAY, 4) + timedelta(days=1),)


def _christmas_eve(year: int) -> tuple[date, ...]:
    return _monday_to_thursday(date(year, 12, 24))


def _day_before_independence_day(year: int) -> tuple[date, ...]:
    return _monday_to_thursday(_observed(date(year, 7, 4)) - timedelta(days=1))


_FULL_CLOSES: tuple[tuple[DayRule, str], ...] = (
    (_new_years_day, _NEW_YEARS_DAY),
    (_good_friday, _GOOD_FRIDAY),
    (_christmas, _CHRISTMAS),
)
_HALTS: tuple[tuple[DayRule, str], ...] = (
    (_martin_luther_king_jr_day, _MARTIN_LUTHER_KING_JR_DAY),
    (_presidents_day, _PRESIDENTS_DAY),
    (_memorial_day, _MEMORIAL_DAY),
    (_juneteenth, _JUNETEENTH),
    (_independence_day, _INDEPENDENCE_DAY),
    (_labor_day, _LABOR_DAY),
    (_thanksgiving, _THANKSGIVING),
)
_ENERGY_AND_METALS_EARLY_CLOSES: tuple[tuple[DayRule, time, str], ...] = (
    (_day_after_thanksgiving, time(13, 45), _THANKSGIVING),
    (_christmas_eve, time(12, 45), _CHRISTMAS_EVE),
)
_EARLY_CLOSES: Mapping[CalendarId, tuple[tuple[DayRule, time, str], ...]] = {
    CalendarId.CME_EQUITY_INDEX: (
        (_day_after_thanksgiving, time(12, 15), _THANKSGIVING),
        (_christmas_eve, time(12, 15), _CHRISTMAS_EVE),
        (_day_before_independence_day, time(12, 15), _DAY_BEFORE_INDEPENDENCE_DAY),
    ),
    CalendarId.CME_ENERGY: _ENERGY_AND_METALS_EARLY_CLOSES,
    CalendarId.CME_METALS: _ENERGY_AND_METALS_EARLY_CLOSES,
}
"""The early closes of each CME group, in Chicago time."""

# shortcut: the rules are CME's 2024 to 2026 schedules; earlier years may differ, and step
# 1.6's check of the real bars from 2010 adds every difference it explains to OVERRIDES.
OVERRIDES: tuple[tuple[CalendarId, Holiday], ...] = (
    # National Day of Mourning for President George H. W. Bush.
    (
        CalendarId.CME_EQUITY_INDEX,
        EarlyClose(
            day=date(2018, 12, 5),
            closes_at=time(8, 30),
            source="https://investor.cmegroup.com/news-releases/news-release-details/"
            "cme-group-us-equity-interest-rate-markets-close-national-day",
        ),
    ),
    # Good Friday with the March jobs report.
    (
        CalendarId.CME_EQUITY_INDEX,
        EarlyClose(
            day=date(2021, 4, 2),
            closes_at=time(8, 15),
            source="https://www.markettradingessentials.com/2021/04/u-s-stock-futures-edge-"
            "higher-ahead-of-march-jobs-report-regular-trading-closed-for-good-friday/",
        ),
    ),
    # The day after Thanksgiving in 2021, before the close moved to 13:45.
    *(
        (
            calendar_id,
            EarlyClose(
                day=date(2021, 11, 26),
                closes_at=time(12, 45),
                source="https://www.ampfutures.com/news/thanksgiving-holiday-trading-schedule-2021",
            ),
        )
        for calendar_id in (CalendarId.CME_ENERGY, CalendarId.CME_METALS)
    ),
    # Good Friday with the March jobs report.
    (
        CalendarId.CME_EQUITY_INDEX,
        EarlyClose(
            day=date(2023, 4, 7),
            closes_at=time(8, 15),
            source="https://www.ironbeam.com/good-friday-holidy-futures-trading-schedule-2023/",
        ),
    ),
    # National Day of Mourning for President Jimmy Carter.
    (
        CalendarId.CME_EQUITY_INDEX,
        EarlyClose(
            day=date(2025, 1, 9),
            closes_at=time(8, 30),
            source="https://investor.cmegroup.com/news-releases/news-release-details/"
            "cme-group-announces-trading-hours-us-national-day-mourning-honor",
        ),
    ),
    # Good Friday with the March jobs report.
    (
        CalendarId.CME_EQUITY_INDEX,
        EarlyClose(
            day=date(2026, 4, 3),
            closes_at=time(8, 15),
            source="https://www.ironbeam.com/good-friday-2026-futures-trading-hours/",
        ),
    ),
)
"""Days where CME did otherwise than the rules, for one group, each with its source; a row
replaces the rules' holiday of its day."""


def cme_holidays(calendar_id: CalendarId, first_year: int, last_year: int) -> tuple[Holiday, ...]:
    """The holidays of a CME Globex group from `first_year` to `last_year`, sorted by day: the
    rules' holidays, with the group's `OVERRIDES` replacing or joining them."""
    years = range(first_year, last_year + 1)
    overrides = {
        holiday.day: holiday
        for overridden, holiday in OVERRIDES
        if overridden is calendar_id and holiday.day.year in years
    }
    rules = [
        holiday for holiday in _rule_holidays(calendar_id, years) if holiday.day not in overrides
    ]
    return tuple(sorted([*rules, *overrides.values()], key=lambda holiday: holiday.day))


def _rule_holidays(calendar_id: CalendarId, years: range) -> Iterator[Holiday]:
    for year in years:
        for rule, source in _FULL_CLOSES:
            yield from (FullClose(day=day, source=source) for day in rule(year))
        for rule, source in _HALTS:
            yield from (Halt(day=day, source=source) for day in rule(year))
        for rule, closes_at, source in _EARLY_CLOSES[calendar_id]:
            yield from (
                EarlyClose(day=day, closes_at=closes_at, source=source) for day in rule(year)
            )


def _cme_calendar(calendar_id: CalendarId) -> Calendar:
    holidays = cme_holidays(calendar_id, FIRST_SESSION_DATE.year, LAST_SESSION_DATE.year)
    return Calendar(name=calendar_id.value, hours=CME_GLOBEX_HOURS, holidays=holidays)


BUILT_IN: Mapping[CalendarId, Calendar] = MappingProxyType(
    {
        CalendarId.CME_EQUITY_INDEX: _cme_calendar(CalendarId.CME_EQUITY_INDEX),
        CalendarId.CME_ENERGY: _cme_calendar(CalendarId.CME_ENERGY),
        CalendarId.CME_METALS: _cme_calendar(CalendarId.CME_METALS),
        CalendarId.CRYPTO_24X7: Calendar(
            name=CalendarId.CRYPTO_24X7.value, hours=CRYPTO_HOURS, holidays=()
        ),
    }
)
"""Every built-in calendar, read-only, with its holidays from `FIRST_SESSION_DATE` to
`LAST_SESSION_DATE`."""
