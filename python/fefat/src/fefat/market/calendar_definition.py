"""What a session calendar is (`02-engine-and-data.md` §1.3, D-41): regular hours in an IANA time
zone, the holidays that change them (full closes, halts whose trading belongs to the next trade
date, and early closes), and the regular closes of earlier eras. `fefat.market.calendar` builds
a calendar's session table from it; the built-in calendars are
`fefat.market.builtin_calendars.BUILT_IN`.
"""

import itertools
from datetime import date, time
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self

import polars as pl
from polars.exceptions import ComputeError
from pydantic import AfterValidator, Field, StringConstraints, model_validator

from fefat.market.layout import FolderName
from fefat.market.schema import FrozenModel


class CalendarId(StrEnum):
    """A built-in session calendar: CME Globex's equity index, energy, and metals groups, and
    crypto's 24x7 UTC days (`fefat.market.builtin_calendars`)."""

    CME_EQUITY_INDEX = "cme-equity-index"
    CME_ENERGY = "cme-energy"
    CME_METALS = "cme-metals"
    CRYPTO_24X7 = "crypto-24x7"


class Weekday(IntEnum):
    """A day of the week, numbered as ISO 8601, `date.isoweekday`, and Polars number them."""

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


def _known_time_zone(name: str) -> str:
    try:
        pl.Series([0], dtype=pl.Datetime("ns")).dt.replace_time_zone(name)
    except ComputeError as error:
        raise ValueError(
            f"Expected an IANA time zone such as America/Chicago, got {name!r}."
        ) from error
    return name


TimeZoneName = Annotated[str, AfterValidator(_known_time_zone)]
"""An IANA time-zone name that Polars knows, such as `America/Chicago` or `UTC`."""

SourceLink = Annotated[str, StringConstraints(pattern=r"^https://\S+$")]
"""Where a holiday's date or time is published."""


class SessionHours(FrozenModel):
    """Regular sessions in local time of `time_zone`: each opens at `opens_at`, on the day before
    its trade date when `opens_on_previous_day`, and closes at `closes_at` on its trade date, or
    on the day after when it opens on its trade date and `closes_at` is not after `opens_at` (a
    crypto UTC day runs 00:00 to 00:00). `weekdays` are the days of the week that are trade
    dates."""

    time_zone: TimeZoneName
    opens_at: time
    closes_at: time
    opens_on_previous_day: bool
    weekdays: frozenset[Weekday] = Field(min_length=1)

    @model_validator(mode="after")
    def _sessions_end_before_the_next_opens(self) -> Self:
        if self.opens_on_previous_day and self.closes_at > self.opens_at:
            raise ValueError(
                "Expected the close at or before the open time when sessions open the day "
                f"before their trade date, got an open at {self.opens_at} and a close at "
                f"{self.closes_at}."
            )
        return self


class FullClose(FrozenModel):
    """A day without trading: no session ends on it, and the next session opens at the regular
    open after it."""

    kind: Literal["full-close"] = "full-close"
    day: date
    source: SourceLink


class Halt(FrozenModel):
    """A holiday that trades until a midday halt but has no trade date of its own: its trading
    belongs to the next trade date, whose session opens at the regular open before it."""

    kind: Literal["halt"] = "halt"
    day: date
    source: SourceLink


class EarlyClose(FrozenModel):
    """A trade date whose session closes early, at `closes_at` local time."""

    kind: Literal["early-close"] = "early-close"
    day: date
    closes_at: time
    source: SourceLink


Holiday = Annotated[FullClose | Halt | EarlyClose, Field(discriminator="kind")]
"""A holiday as a model field: a full close, a halt, or an early close, told apart by `kind`."""


class FormerClose(FrozenModel):
    """A regular close that held for the trade dates before `until`, at `closes_at` local time,
    such as 16:15 Chicago on CME Globex until the daily maintenance began 15 minutes earlier
    for trade date 2015-09-21."""

    until: date
    closes_at: time
    source: SourceLink


class Calendar(FrozenModel):
    """A session calendar: regular hours, the holidays that change them, at most one a day,
    each on one of the calendar's weekdays, and the regular closes of earlier eras. The
    built-in calendars are `fefat.market.builtin_calendars.BUILT_IN`; a product a trader
    imports on hours of its own gets a calendar built the same way, with its own name."""

    name: FolderName
    hours: SessionHours
    holidays: tuple[Holiday, ...]
    former_closes: tuple[FormerClose, ...] = ()

    @model_validator(mode="after")
    def _one_holiday_a_day_on_a_trading_weekday(self) -> Self:
        days = sorted(holiday.day for holiday in self.holidays)
        repeated = sorted({day for day, after in itertools.pairwise(days) if day == after})
        if repeated:
            raise ValueError(
                f"Expected at most one holiday a day in {self.name}, got several on "
                f"{', '.join(str(day) for day in repeated)}."
            )
        off_days = [day for day in days if day.isoweekday() not in self.hours.weekdays]
        if off_days:
            raise ValueError(
                f"Expected {self.name}'s holidays on its weekdays, got {off_days[0]}, a "
                f"{off_days[0]:%A}."
            )
        return self

    @model_validator(mode="after")
    def _former_closes_end_their_sessions(self) -> Self:
        ends = sorted(former.until for former in self.former_closes)
        if len(ends) != len(set(ends)):
            raise ValueError(
                f"Expected one former close ending on each day in {self.name}, got the ends "
                f"{', '.join(str(end) for end in ends)}."
            )
        hours = self.hours
        for former in self.former_closes:
            if hours.opens_on_previous_day and former.closes_at > hours.opens_at:
                raise ValueError(
                    f"Expected the former close of {self.name} at or before the open time "
                    f"{hours.opens_at}, got {former.closes_at} until {former.until}."
                )
        return self

    def no_session_reason(self, day: date) -> str:
        """Why `day`, a date without a session, is not a trade date: its holiday or weekday."""
        holiday = next((holiday for holiday in self.holidays if holiday.day == day), None)
        if holiday is None:
            return f"a {day:%A}, not one of its weekdays"
        return f"a {holiday.kind} holiday ({holiday.source})"
