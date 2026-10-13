"""Session calendars: the trade dates of a product group, each with its session's open and
close as UTC instants (`02-engine-and-data.md` §1.3, D-41).

A calendar (`fefat.market.calendar_definition`) is regular hours in a time zone and its
holidays: full closes, halts whose trading belongs to the next trade date (as CME dates holiday
trading), and early closes, with the regular closes of earlier eras. Trade dates
come from session membership, never from clock arithmetic: `SessionTable.assign_trade_dates`
gives each instant the trade date of the session it falls in. Local times become UTC instants
day by day through the IANA time-zone database that Polars carries, so a daylight-saving
change moves the UTC open and close, and a local time that does not exist that day, or exists
twice, is refused. `sessions_of` builds a calendar's table once and keeps it in the cache
folder. The built-in calendars are `fefat.market.builtin_calendars`:

    table = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], resolve_paths(os.environ).cache_dir)
    table.session(date(2026, 3, 9))  # open 2026-03-08 22:00 UTC (17:00 CDT), close 21:00 UTC
"""

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Self

import polars as pl
from polars.exceptions import ComputeError
from pydantic import model_validator

from fefat.market.calendar_definition import Calendar, SessionHours
from fefat.market.schema import FrozenModel, require_columns
from fefat.market.store import write_atomically

# shortcut: sessions from 2010, where the data on this PC starts; widen the span, and check
# the holiday rules of the earlier years, before importing older data.
FIRST_SESSION_DATE = date(2010, 1, 1)
LAST_SESSION_DATE = date(2030, 12, 31)
SESSION_TABLE_FOLDER_NAME = "calendar"
"""The folder of the cached session tables, inside the cache folder."""
SESSION_COLUMNS = pl.Schema({"trade_date": pl.Date, "open": pl.Int64, "close": pl.Int64})
"""A session table's columns: the trade date, and its session's open and close in nanoseconds
since the Unix epoch, UTC."""

_LEAD_IN = timedelta(days=14)
_NANOSECONDS_PER_SECOND = 1_000_000_000
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Session(FrozenModel):
    """One trade date's session, from `open` to just before `close`, in nanoseconds since the
    Unix epoch, UTC (the store's clock)."""

    trade_date: date
    open: int
    close: int

    @model_validator(mode="after")
    def _closes_after_it_opens(self) -> Self:
        if self.close <= self.open:
            raise ValueError(
                f"Expected the session of {self.trade_date} to close after it opens at "
                f"{utc_text(self.open)}, got a close at {utc_text(self.close)}."
            )
        return self


def utc_text(instant: int) -> str:
    """An instant in nanoseconds since the Unix epoch as ISO 8601 UTC text, such as
    `2026-03-08T22:00:00Z`, with the nanoseconds when there are any."""
    seconds, nanoseconds = divmod(instant, _NANOSECONDS_PER_SECOND)
    text = (_UNIX_EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")
    if nanoseconds:
        return f"{text}.{nanoseconds:09d}Z"
    return f"{text}Z"


class SessionTable:
    """One calendar's sessions: a row per trade date with the columns of `SESSION_COLUMNS`,
    sorted by trade date."""

    def __init__(self, calendar: Calendar, sessions: pl.DataFrame) -> None:
        require_columns(SESSION_COLUMNS, sessions.schema, f"the session table of {calendar.name}")
        self._calendar = calendar
        self._sessions = sessions

    def __repr__(self) -> str:
        first, last = self._span()
        return f"SessionTable({self._calendar.name!r}, {self._sessions.height} sessions, {first} to {last})"

    def session(self, trade_date: date) -> Session:
        """The session of `trade_date`; a date without one is refused with the reason."""
        found = self._sessions.filter(pl.col("trade_date") == trade_date)
        if not found.is_empty():
            return Session.model_validate(found.row(0, named=True))
        self._require_within_the_span(pl.Series([trade_date], dtype=pl.Date))
        raise ValueError(
            f"Expected a trade date of {self._calendar.name}, got {trade_date}, "
            f"{self._calendar.no_session_reason(trade_date)}."
        )

    def between(self, first: date, last: date) -> pl.DataFrame:
        """The sessions of the trade dates from `first` to `last`, with the columns of
        `SESSION_COLUMNS`; dates outside the table's span are refused."""
        self._require_within_the_span(pl.Series([first, last], dtype=pl.Date))
        return self._sessions.filter(pl.col("trade_date").is_between(first, last))

    def assign_trade_dates(self, frame: pl.DataFrame, column: str) -> pl.DataFrame:
        """`frame` sorted by `column`, an Int64 instant in nanoseconds since the Unix epoch, UTC,
        keeping the order of equal instants (D-36), with the `trade_date` of the session each
        instant falls in. An instant outside every session (a weekend, the daily break, a full
        close) is refused, with the first of them. The hours a halt day leaves closed, and the
        weekend after a Friday halt, lie inside the next trade date's session, since the table
        holds no halt windows (`BACKLOG.md`)."""
        assigned = self._beside_their_sessions(frame, column)
        outside = assigned.filter(
            pl.col("trade_date").is_null() | (pl.col(column) >= pl.col("session_close"))
        )
        if not outside.is_empty():
            raise ValueError(
                f"Expected every {column} inside a session of {self._calendar.name}, got "
                f"{outside.height} outside, the first at {utc_text(outside.item(0, column))}."
            )
        return assigned.drop("session_open", "session_close")

    def assign_trade_dates_or_previous(self, frame: pl.DataFrame, column: str) -> pl.DataFrame:
        """`frame` sorted by `column` as `assign_trade_dates` sorts it, with the `trade_date` of
        the latest session that opened at or before each instant and `in_session`, whether the
        instant falls inside that session. An instant in the daily break, on a weekend, or on a
        holiday the rules miss takes the trade date before it rather than being refused, as an
        importer of a vendor's history needs (step 1.6), and a print received just after a close
        keeps its session. An instant before the table's first open or from its last close on
        is refused."""
        assigned = self._beside_their_sessions(frame, column)
        first_open = self._sessions.item(0, "open")
        last_close = self._sessions.item(-1, "close")
        instant = pl.col(column)
        beyond = assigned.filter((instant < first_open) | (instant >= last_close))
        if not beyond.is_empty():
            raise ValueError(
                f"Expected every {column} within the session table of {self._calendar.name}, "
                f"from its first open {utc_text(first_open)} to its last close "
                f"{utc_text(last_close)}, got {beyond.height} outside, the first at "
                f"{utc_text(beyond.item(0, column))}."
            )
        in_session = instant < pl.col("session_close")
        return assigned.with_columns(in_session=in_session).drop("session_open", "session_close")

    def _beside_their_sessions(self, frame: pl.DataFrame, column: str) -> pl.DataFrame:
        """`frame` sorted by `column`, keeping the order of equal instants (D-36), beside the
        session that opened last at or before each instant: its trade date, open, and close."""
        if frame.schema.get(column) != pl.Int64:
            raise ValueError(
                f"Expected an Int64 column {column!r} of nanoseconds since the Unix epoch, UTC, "
                f"got {frame.schema.get(column)}."
            )
        if "trade_date" in frame.columns:
            raise ValueError("Expected a frame without a trade_date column, got one.")
        return frame.sort(column, maintain_order=True).join_asof(
            self._renamed(), left_on=column, right_on="session_open", strategy="backward"
        )

    def _renamed(self) -> pl.DataFrame:
        return self._sessions.rename({"open": "session_open", "close": "session_close"})

    def _span(self) -> tuple[date, date]:
        return self._sessions.item(0, "trade_date"), self._sessions.item(-1, "trade_date")

    def _require_within_the_span(self, trade_dates: pl.Series) -> None:
        first, last = self._span()
        outside = trade_dates.filter(~trade_dates.is_between(first, last))
        if not outside.is_empty():
            raise ValueError(
                f"Expected trade dates from {first} to {last}, the span of the session table "
                f"of {self._calendar.name}, got {outside.min()}."
            )


def build_sessions(calendar: Calendar, first: date, last: date) -> pl.DataFrame:
    """The sessions of `calendar` whose trade dates fall from `first` to `last`, sorted, with
    the columns of `SESSION_COLUMNS`. A day trades when it is one of the weekdays and not a
    full close, and it is a trade date when it trades and is not a halt. A trade date's session
    opens at the regular open of the first day that trades after the previous trade date (the
    evening before on CME), so a weekend or a halt folds into the next trade date, and closes at
    the regular or early close of its trade date. An early close must fall after its session's
    open and by its regular close."""
    if last < first:
        raise ValueError(
            f"Expected the first trade date {first} on or before the last, got {last}."
        )
    sessions = _trade_dates_with_their_first_trading_day(_days(calendar, first - _LEAD_IN, last))
    _require_an_earlier_trade_date(calendar, sessions, first)
    hours = calendar.hours
    open_day = pl.col("first_trading_day") - timedelta(days=int(hours.opens_on_previous_day))
    regular_close_time = _regular_close_time(calendar)
    close_time = pl.col("early_close").fill_null(regular_close_time)
    try:
        built = sessions.filter(pl.col("trade_date") >= first).select(
            "trade_date",
            open=_utc_nanoseconds(open_day, pl.lit(hours.opens_at), hours.time_zone),
            close=_utc_nanoseconds(_close_day(close_time, hours), close_time, hours.time_zone),
            regular_close=_utc_nanoseconds(
                _close_day(regular_close_time, hours), regular_close_time, hours.time_zone
            ),
        )
    except ComputeError as error:
        raise ValueError(
            f"Expected open and close times that exist once in {hours.time_zone} on every "
            f"session of {calendar.name}, got: {str(error).splitlines()[0]}"
        ) from error
    _require_early_closes_inside_their_sessions(calendar, built)
    return built.drop("regular_close")


def _regular_close_time(calendar: Calendar) -> pl.Expr:
    """Each trade date's regular close: the close of the former era it falls in, if any, else
    the hours' close."""
    close_time = pl.lit(calendar.hours.closes_at)
    for former in sorted(calendar.former_closes, key=lambda former: former.until, reverse=True):
        before = pl.col("trade_date") < former.until
        close_time = pl.when(before).then(pl.lit(former.closes_at)).otherwise(close_time)
    return close_time


def _close_day(close_time: pl.Expr, hours: SessionHours) -> pl.Expr:
    """The day a session closes: its trade date, or the day after for a session that opens on
    its trade date and closes at or before its open time, such as a crypto UTC day, whose early
    close at 12:00 still falls on the trade date."""
    if hours.opens_on_previous_day:
        return pl.col("trade_date")
    next_day = pl.col("trade_date") + timedelta(days=1)
    return pl.when(close_time <= hours.opens_at).then(next_day).otherwise(pl.col("trade_date"))


def _require_early_closes_inside_their_sessions(calendar: Calendar, sessions: pl.DataFrame) -> None:
    misplaced = sessions.filter(
        (pl.col("close") <= pl.col("open")) | (pl.col("close") > pl.col("regular_close"))
    )
    if misplaced.is_empty():
        return
    trade_date, opens, closes, regular_close = misplaced.row(0)
    raise ValueError(
        f"Expected the early close of {calendar.name} on {trade_date} after its session's open "
        f"{utc_text(opens)} and by its regular close {utc_text(regular_close)}, got "
        f"{utc_text(closes)}."
    )


def _days(calendar: Calendar, start: date, end: date) -> pl.DataFrame:
    """Every day from `start` to `end`, in order, with whether it trades, whether it is a trade
    date, and its early close (null on other days)."""
    holidays = pl.from_dicts(
        [holiday.model_dump() for holiday in calendar.holidays],
        schema={"day": pl.Date, "kind": pl.String, "closes_at": pl.Time},
    )
    weekdays = sorted(int(weekday) for weekday in calendar.hours.weekdays)
    trades = pl.col("day").dt.weekday().is_in(weekdays) & pl.col("kind").ne_missing("full-close")
    return (
        pl.DataFrame({"day": pl.date_range(start, end, eager=True)})
        .join(holidays, on="day", how="left", maintain_order="left")
        .with_columns(trades=trades)
        .with_columns(is_trade_date=pl.col("trades") & pl.col("kind").ne_missing("halt"))
    )


def _trade_dates_with_their_first_trading_day(days: pl.DataFrame) -> pl.DataFrame:
    """A row per trade date, sorted: the first day that trades after the previous trade date
    (the trade date itself after a regular day) and the trade date's early close, if any."""
    trade_dates_before = pl.col("is_trade_date").cast(pl.UInt32).cum_sum().shift(1, fill_value=0)
    return (
        days.with_columns(trade_dates_before=trade_dates_before)
        .group_by("trade_dates_before")
        .agg(
            trade_date=pl.col("day").filter(pl.col("is_trade_date")).max(),
            first_trading_day=pl.col("day").filter(pl.col("trades")).min(),
            early_close=pl.col("closes_at").filter(pl.col("is_trade_date")).max(),
        )
        .drop_nulls("trade_date")
        .sort("trade_date")
    )


def _require_an_earlier_trade_date(calendar: Calendar, sessions: pl.DataFrame, first: date) -> None:
    """The first trade date scanned anchors the next session's open, so it must lie before
    `first`: an open is only known once the previous trade date is."""
    if sessions.is_empty() or sessions.item(0, "trade_date") < first:
        return
    raise ValueError(
        f"Expected a trade date of {calendar.name} in the {_LEAD_IN.days} days before {first}, "
        "which anchors the open of the first session, got none."
    )


def _utc_nanoseconds(day: pl.Expr, local_time: pl.Expr, time_zone: str) -> pl.Expr:
    return (
        day.dt.combine(local_time, time_unit="ns")
        .dt.replace_time_zone(time_zone, ambiguous="raise", non_existent="raise")
        .dt.epoch("ns")
    )


def sessions_of(calendar: Calendar, cache_folder: Path) -> SessionTable:
    """The calendar's sessions from `FIRST_SESSION_DATE` to `LAST_SESSION_DATE`, read from
    `<cache_folder>/calendar/` when built before, else built and written there. The file's
    name carries a key over the calendar, its holidays included, this module's source, and the
    Polars version, whose time-zone database converts the local times, so a changed holiday, a
    changed rule, or new time-zone rules build a new table; older files stay until the cache
    folder, which holds nothing that cannot be rebuilt, is cleared."""
    folder = cache_folder / SESSION_TABLE_FOLDER_NAME
    path = folder / f"{calendar.name}-{_cache_key(calendar)}.parquet"
    if path.is_file():
        return SessionTable(calendar, pl.read_parquet(path))
    sessions = build_sessions(calendar, FIRST_SESSION_DATE, LAST_SESSION_DATE)
    write_atomically(path, sessions.write_parquet)
    return SessionTable(calendar, sessions)


def _cache_key(calendar: Calendar) -> str:
    digest = hashlib.sha256(calendar.model_dump_json().encode())
    # shortcut: the key reads this module's source, which a build shipping only bytecode lacks;
    # replace it with a version constant when the app is packaged (Phase 14).
    digest.update(Path(__file__).read_bytes())
    digest.update(pl.__version__.encode())
    return digest.hexdigest()[:12]
