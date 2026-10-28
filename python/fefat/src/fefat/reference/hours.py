"""When the market is open, for F-SES-02: records received in a break or a halt, and bars
that open there, are not tradeable. `CalendarHours` reads a product's session table
(`fefat.market.calendar`); `AlwaysOpen` serves a product without a calendar, such as a
scenario's inline instrument, which trades around the clock."""

from bisect import bisect_right
from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from fefat.market.calendar import Session, SessionTable
from fefat.reference.units import day_number, instant_text, utc_date

_AROUND = timedelta(days=7)


class TradingHours(Protocol):
    def is_open(self, instant: int) -> bool:
        """Whether the market trades at `instant`, in nanoseconds since the Unix epoch, UTC."""
        ...

    def trade_date_of(self, instant: int) -> int:
        """The trade date `instant` belongs to, in days since 1970-01-01, which prices the fees
        of the fills there (F-FEE-01)."""
        ...


class AlwaysOpen:
    """A product without a calendar, which trades around the clock."""

    def is_open(self, instant: int) -> bool:
        return True

    def trade_date_of(self, instant: int) -> int:
        """The UTC day: a market without sessions has no other."""
        return day_number(utc_date(instant))


class CalendarHours:
    """Open from each session's open to just before its close, but inside its halts."""

    def __init__(self, sessions: Sequence[Session]) -> None:
        self._sessions = sorted(sessions, key=lambda session: session.open)
        self._opens = [session.open for session in self._sessions]

    @classmethod
    def around(cls, table: SessionTable, first: int, last: int) -> "CalendarHours":
        """The sessions of `table` from a week before the instant `first` to a week after the
        instant `last`."""
        rows = table.between(utc_date(first) - _AROUND, utc_date(last) + _AROUND)
        return cls([Session.model_validate(row) for row in rows.iter_rows(named=True)])

    def sessions(self) -> tuple[Session, ...]:
        """The sessions it holds, ordered by their opens."""
        return tuple(self._sessions)

    def is_open(self, instant: int) -> bool:
        index = bisect_right(self._opens, instant) - 1
        if index < 0 or instant >= self._sessions[index].close:
            return False
        return not any(halt.start <= instant < halt.end for halt in self._sessions[index].halts)

    def trade_date_of(self, instant: int) -> int:
        """The trade date of the session `instant` falls in, or of the last one opened before it,
        as `load` dates the store's records (`SessionTable.assign_trade_dates_or_previous`)."""
        index = bisect_right(self._opens, instant) - 1
        if index < 0:
            raise ValueError(
                f"Expected a session opened by {instant_text(instant)}, got the first at "
                f"{instant_text(self._opens[0])}."
            )
        return day_number(self._sessions[index].trade_date)
