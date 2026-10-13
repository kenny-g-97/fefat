from datetime import date, time

import pytest

from fefat.market.builtin_calendars import BUILT_IN, cme_holidays, easter_sunday
from fefat.market.calendar import CalendarId

EQUITY_INDEX = CalendarId.CME_EQUITY_INDEX
ENERGY = CalendarId.CME_ENERGY
METALS = CalendarId.CME_METALS
FULL_CLOSE = {"kind": "full-close"}
HALT = {"kind": "halt"}


def early_close(hour: int, minute: int) -> dict[str, object]:
    return {"kind": "early-close", "closes_at": time(hour, minute)}


def holidays_of(calendar_id: CalendarId, first_year: int, last_year: int) -> dict[date, dict]:
    return {
        holiday.day: holiday.model_dump(exclude={"day", "source"})
        for holiday in cme_holidays(calendar_id, first_year, last_year)
    }


# CME's holiday calendar for 2026 (https://www.cmegroup.com/trading-hours.html), with the
# times of the brokers' copies of its schedules that `fefat.market.builtin_calendars` cites.
ENERGY_AND_METALS_OF_2026 = {
    date(2026, 1, 1): FULL_CLOSE,
    date(2026, 1, 19): HALT,
    date(2026, 2, 16): HALT,
    date(2026, 4, 3): FULL_CLOSE,
    date(2026, 5, 25): HALT,
    date(2026, 6, 19): HALT,
    date(2026, 7, 3): HALT,
    date(2026, 9, 7): HALT,
    date(2026, 11, 26): HALT,
    date(2026, 11, 27): early_close(13, 45),
    date(2026, 12, 24): early_close(12, 45),
    date(2026, 12, 25): FULL_CLOSE,
}
EQUITY_INDEX_OF_2026 = {
    **ENERGY_AND_METALS_OF_2026,
    date(2026, 4, 3): early_close(8, 15),
    date(2026, 7, 2): early_close(12, 15),
    date(2026, 11, 27): early_close(12, 15),
    date(2026, 12, 24): early_close(12, 15),
}


@pytest.mark.parametrize(
    ("calendar_id", "expected"),
    [
        (EQUITY_INDEX, EQUITY_INDEX_OF_2026),
        (ENERGY, ENERGY_AND_METALS_OF_2026),
        (METALS, ENERGY_AND_METALS_OF_2026),
    ],
)
def test_the_holidays_of_2026_are_the_ones_cme_published(
    calendar_id: CalendarId, expected: dict[date, dict]
) -> None:
    assert holidays_of(calendar_id, 2026, 2026) == dict(sorted(expected.items()))


@pytest.mark.parametrize(
    ("year", "good_friday"),
    [
        (2010, date(2010, 4, 2)),
        (2019, date(2019, 4, 19)),
        (2021, date(2021, 4, 2)),
        (2024, date(2024, 3, 29)),
        (2025, date(2025, 4, 18)),
        (2027, date(2027, 3, 26)),
        (2030, date(2030, 4, 19)),
    ],
)
def test_good_friday_falls_two_days_before_easter(year: int, good_friday: date) -> None:
    assert (easter_sunday(year) - good_friday).days == 2
    assert holidays_of(ENERGY, year, year)[good_friday] == FULL_CLOSE


def test_new_years_day_on_a_saturday_is_not_observed_and_on_a_sunday_moves_to_monday() -> None:
    around_2022 = holidays_of(METALS, 2021, 2023)

    assert date(2021, 12, 31) not in around_2022
    assert date(2022, 1, 3) not in around_2022
    assert around_2022[date(2023, 1, 2)] == FULL_CLOSE


def test_christmas_and_independence_day_on_a_weekend_move_to_the_nearest_weekday() -> None:
    equity_index = holidays_of(EQUITY_INDEX, 2020, 2022)

    # Christmas 2021 is a Saturday, observed on Friday 12-24, with no early close before it.
    assert equity_index[date(2021, 12, 24)] == FULL_CLOSE
    assert date(2021, 12, 23) not in equity_index
    # Christmas 2022 is a Sunday, observed on Monday 12-26.
    assert equity_index[date(2022, 12, 26)] == FULL_CLOSE
    # Independence Day 2020 is a Saturday, observed on Friday 07-03, so equity index closes
    # early on Thursday 07-02; in 2021 it is a Sunday, observed on Monday 07-05, after a
    # regular Friday.
    assert equity_index[date(2020, 7, 3)] == HALT
    assert equity_index[date(2020, 7, 2)] == early_close(12, 15)
    assert equity_index[date(2021, 7, 5)] == HALT
    assert date(2021, 7, 2) not in equity_index


def test_juneteenth_is_observed_from_2022() -> None:
    energy = holidays_of(ENERGY, 2021, 2027)

    assert [day for day in energy if day.month == 6] == [
        date(2022, 6, 20),
        date(2023, 6, 19),
        date(2024, 6, 19),
        date(2025, 6, 19),
        date(2026, 6, 19),
        date(2027, 6, 18),
    ]


def test_overrides_replace_the_rules_for_their_group_only() -> None:
    # The national day of mourning of 2025-01-09 shortened equity index trading to 08:30, while
    # energy and metals traded their regular hours.
    assert holidays_of(EQUITY_INDEX, 2025, 2025)[date(2025, 1, 9)] == early_close(8, 30)
    assert date(2025, 1, 9) not in holidays_of(METALS, 2025, 2025)
    # In 2021 energy and metals closed at 12:45 the day after Thanksgiving, equity at 12:15.
    assert holidays_of(METALS, 2021, 2021)[date(2021, 11, 26)] == early_close(12, 45)
    assert holidays_of(EQUITY_INDEX, 2021, 2021)[date(2021, 11, 26)] == early_close(12, 15)


def test_every_built_in_calendar_is_keyed_by_its_own_name() -> None:
    assert {calendar_id: calendar.name for calendar_id, calendar in BUILT_IN.items()} == {
        calendar_id: calendar_id.value for calendar_id in CalendarId
    }
    assert BUILT_IN[CalendarId.CRYPTO_24X7].holidays == ()
