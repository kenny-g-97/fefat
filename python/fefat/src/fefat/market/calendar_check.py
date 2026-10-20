"""The calendar check: a store's prints against the session table of each root's calendar,
trade date by trade date (`02-engine-and-data.md` §1.3, step 1.3).

For each dataset of bars or ticks, the check takes each trade date's first and last print, the
first bar's `ts_open` and the last bar's `ts_close`, or the first and last `ts_recv` of trades
and TBBO (keyed by their partition's trade date), across all of the root's contracts, and
compares them with that trade date's session in the root's calendar
(`fefat.market.saved_instruments`, `fefat.market.builtin_calendars`). It reports a print before the
open or after the close (for bars, a bar wholly outside the session, since a bar's prints lie
somewhere inside it), a first print more than `tolerance` after the open, a last print more
than `tolerance` before the close, a trade date the calendar has no session for, and a session
between a dataset's first and last trade date without a single print, which is a day the
vendor missed or a session the calendar should not have, such as a full close it lacks.
Definitions, statistics, and funding hold no session prints and are not checked. A half-day
the holiday rules lack shows as an early last print: add it to
`fefat.market.builtin_calendars.OVERRIDES` with its source.

It also finds a dataset's offset (step 1.10), the time by which its records run late or early
against the calendar, as an import read in the wrong time zone or with the wrong bar stamping
gives (`02-engine-and-data.md` §1.8): whole or half hours when moving the records, or those on
one side of a change of the calendar's offset from UTC, by them puts inside the sessions most
of those outside, and one bar when any session's break holds a bar closing at the next open,
or most sessions a bar opening at the close (`fefat.market.calendar_offset`).
`check_records` runs the same check on records an import has not stored yet.

    paths = resolve_paths(os.environ)
    print(validate_calendar(Store(paths.data_dir), paths.cache_dir).summary())
"""

import itertools
from collections.abc import Iterator
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import Field

from fefat.market.calendar import Session, SessionTable, sessions_of, utc_text
from fefat.market.calendar_offset import CalendarOffset, records_offset
from fefat.market.layout import Dataset, Partition
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import FrozenModel, SchemaKind
from fefat.market.store import Store

DEFAULT_TOLERANCE = timedelta(minutes=5)
_CHECKED_KINDS = frozenset({SchemaKind.TRADES, SchemaKind.TBBO, SchemaKind.OHLCV})


class MismatchKind(StrEnum):
    """How a trade date's prints disagree with its session."""

    PRINT_BEFORE_OPEN = "print-before-open"
    PRINT_AFTER_CLOSE = "print-after-close"
    LATE_FIRST_PRINT = "late-first-print"
    EARLY_LAST_PRINT = "early-last-print"
    NO_SESSION = "no-session"
    NO_PRINTS = "no-prints"


class SessionMismatch(FrozenModel):
    """A trade date of a dataset whose first or last print, in nanoseconds since the Unix epoch,
    UTC, lies outside its session or too far inside it."""

    kind: Literal[
        MismatchKind.PRINT_BEFORE_OPEN,
        MismatchKind.PRINT_AFTER_CLOSE,
        MismatchKind.LATE_FIRST_PRINT,
        MismatchKind.EARLY_LAST_PRINT,
    ]
    dataset: Dataset
    trade_date: date
    first_print: int
    last_print: int
    session: Session

    def describe(self) -> str:
        """One line: the dataset, the trade date, the kind, and the observed and expected times."""
        session = f"session {utc_text(self.session.open)} to {utc_text(self.session.close)}"
        return f"{_observed(self)}, {session}"


class MissingSession(FrozenModel):
    """A trade date of a dataset, with its first and last print, that the calendar has no
    session for."""

    kind: Literal[MismatchKind.NO_SESSION] = MismatchKind.NO_SESSION
    dataset: Dataset
    trade_date: date
    first_print: int
    last_print: int

    def describe(self) -> str:
        """One line: the dataset, the trade date, and the observed times."""
        return f"{_observed(self)}, on a day without a session"


class SessionWithoutPrints(FrozenModel):
    """A session between a dataset's first and last trade date without a single print."""

    kind: Literal[MismatchKind.NO_PRINTS] = MismatchKind.NO_PRINTS
    dataset: Dataset
    trade_date: date
    session: Session

    def describe(self) -> str:
        """One line: the dataset, the trade date, and the session that has no prints."""
        session = f"{utc_text(self.session.open)} to {utc_text(self.session.close)}"
        heading = f"{self.dataset.relative_folder()} {self.trade_date} {self.kind}"
        return f"{heading}: no prints in the session {session}"


Mismatch = SessionMismatch | MissingSession | SessionWithoutPrints
CalendarMismatch = Annotated[Mismatch, Field(discriminator="kind")]
"""A mismatch of a dataset's trade date with the calendar, told apart by `kind`."""


def _observed(mismatch: SessionMismatch | MissingSession) -> str:
    prints = f"prints {utc_text(mismatch.first_print)} to {utc_text(mismatch.last_print)}"
    folder = mismatch.dataset.relative_folder()
    return f"{folder} {mismatch.trade_date} {mismatch.kind}: {prints}"


class CalendarReport(FrozenModel):
    """What `validate_calendar` or `check_records` found: how many dataset trade dates were
    checked, the mismatches, sorted by dataset, trade date, and kind, and each dataset's
    offset, where its records run late or early as a whole."""

    days_checked: int = Field(ge=0)
    mismatches: tuple[CalendarMismatch, ...]
    offsets: tuple[CalendarOffset, ...] = ()

    def summary(self) -> str:
        """A line per offset and per mismatch, or one line saying there are none."""
        if not self.mismatches and not self.offsets:
            return f"Trade dates checked: {self.days_checked}. Mismatches: none."
        heading = f"Trade dates checked: {self.days_checked}. Mismatches: {len(self.mismatches)}."
        return "\n".join(
            [
                heading,
                *(offset.describe() for offset in self.offsets),
                *(mismatch.describe() for mismatch in self.mismatches),
            ]
        )


def validate_calendar(
    store: Store, cache_folder: Path, tolerance: timedelta = DEFAULT_TOLERANCE
) -> CalendarReport:
    """Compare each bar and tick dataset of `store` with its root's session calendar, whose
    table `fefat.market.calendar.sessions_of` keeps in `cache_folder`. A root missing from
    the instrument table is refused, since its calendar is unknown."""
    instruments = instrument_table(store.folder)
    reports: list[CalendarReport] = []
    for dataset, partitions in _checked_datasets(store):
        # shortcut: the calendar of the root's newest instrument version; split the check by
        # version when a root's calendar changes over time.
        calendar = instruments.get(dataset.root).session_calendar()
        rows = pl.concat([_dated_rows(store, partition) for partition in partitions])
        reports.append(check_records(dataset, rows, sessions_of(calendar, cache_folder), tolerance))
    return CalendarReport(
        days_checked=sum(report.days_checked for report in reports),
        mismatches=tuple(mismatch for report in reports for mismatch in report.mismatches),
        offsets=tuple(offset for report in reports for offset in report.offsets),
    )


def check_records(
    dataset: Dataset,
    records: pl.LazyFrame,
    sessions: SessionTable,
    tolerance: timedelta = DEFAULT_TOLERANCE,
) -> CalendarReport:
    """The calendar check of one dataset's `records`, stored or not, which carry the columns
    of the dataset's schema and each record's `trade_date`, against `sessions`."""
    prints = _prints_by_trade_date(_record_prints(records, dataset.schema_name.kind))
    if prints.is_empty():
        return CalendarReport(days_checked=0, mismatches=())
    joined = _beside_their_sessions(prints, sessions)
    offset = records_offset(dataset, records, sessions)
    return CalendarReport(
        days_checked=joined.height,
        mismatches=tuple(_mismatches(dataset, joined, tolerance)),
        offsets=() if offset is None else (offset,),
    )


def _checked_datasets(store: Store) -> Iterator[tuple[Dataset, list[Partition]]]:
    """The store's bar and tick datasets with their partitions; the listing is sorted by path,
    so each dataset's partitions come together."""
    checked = (
        file.partition
        for file in store.list_partitions()
        if file.partition.dataset.schema_name.kind in _CHECKED_KINDS
    )
    for dataset, partitions in itertools.groupby(checked, key=lambda partition: partition.dataset):
        yield dataset, list(partitions)


def _prints_by_trade_date(prints: pl.LazyFrame) -> pl.DataFrame:
    """Per trade date: the first and last print, the end of the first print, and the start of
    the last (a bar's `ts_close` and `ts_open`, a tick's own time). An empty file adds no trade
    date."""
    return (
        prints.group_by("trade_date")
        .agg(
            pl.col("first_print").min(),
            pl.col("first_end").min(),
            pl.col("last_start").max(),
            pl.col("last_print").max(),
        )
        .drop_nulls("first_print")
        .sort("trade_date")
        .collect()
    )


def _beside_their_sessions(prints: pl.DataFrame, table: SessionTable) -> pl.DataFrame:
    """The prints of each trade date beside the sessions from the dataset's first trade date to
    its last: a row per date that has either, the other side null where it is missing."""
    dates = pl.col("trade_date")
    first, last = prints.select(first=dates.min(), last=dates.max()).row(0)
    sessions = table.between(first, last).rename({"open": "session_open", "close": "session_close"})
    return prints.join(sessions, on="trade_date", how="full", coalesce=True).sort("trade_date")


def _dated_rows(store: Store, partition: Partition) -> pl.LazyFrame:
    """A partition's rows with their trade date: a bar's own, a tick's its partition's."""
    rows = store.scan_partition(partition)
    if partition.dataset.schema_name.kind is SchemaKind.OHLCV:
        return rows
    return rows.with_columns(trade_date=pl.lit(partition.key, dtype=pl.Date))


def _record_prints(rows: pl.LazyFrame, kind: SchemaKind) -> pl.LazyFrame:
    """Each record's print as the check reads it: a bar from its `ts_open` to its `ts_close`,
    a tick at its `ts_recv`, beside its trade date."""
    if kind is SchemaKind.OHLCV:
        return rows.select(
            "trade_date",
            first_print=pl.col("ts_open"),
            first_end=pl.col("ts_close"),
            last_start=pl.col("ts_open"),
            last_print=pl.col("ts_close"),
        )
    received = pl.col("ts_recv")
    return rows.select(
        "trade_date",
        first_print=received,
        first_end=received + 1,
        last_start=received,
        last_print=received,
    )


def _mismatches(dataset: Dataset, joined: pl.DataFrame, tolerance: timedelta) -> list[Mismatch]:
    margin = tolerance // timedelta(microseconds=1) * 1_000
    checks = {
        MismatchKind.NO_SESSION: pl.col("session_open").is_null(),
        MismatchKind.NO_PRINTS: pl.col("first_print").is_null(),
        MismatchKind.PRINT_BEFORE_OPEN: pl.col("first_end") <= pl.col("session_open"),
        MismatchKind.PRINT_AFTER_CLOSE: pl.col("last_start") >= pl.col("session_close"),
        MismatchKind.LATE_FIRST_PRINT: pl.col("first_print") > pl.col("session_open") + margin,
        MismatchKind.EARLY_LAST_PRINT: pl.col("last_print") < pl.col("session_close") - margin,
    }
    found = pl.concat(
        [
            joined.filter(condition).with_columns(kind=pl.lit(str(kind)))
            for kind, condition in checks.items()
        ]
    ).sort("trade_date", "kind")
    return [_mismatch(dataset, row) for row in found.iter_rows(named=True)]


def _session(row: dict[str, Any]) -> Session:
    return Session(
        trade_date=row["trade_date"],
        open=row["session_open"],
        close=row["session_close"],
        halts=row["halts"],
    )


def _mismatch(dataset: Dataset, row: dict[str, Any]) -> Mismatch:
    if row["first_print"] is None:
        return SessionWithoutPrints(
            dataset=dataset, trade_date=row["trade_date"], session=_session(row)
        )
    observed = {
        "dataset": dataset,
        "trade_date": row["trade_date"],
        "first_print": row["first_print"],
        "last_print": row["last_print"],
    }
    if row["session_open"] is None:
        return MissingSession.model_validate(observed)
    return SessionMismatch.model_validate(
        {**observed, "kind": row["kind"], "session": _session(row)}
    )
