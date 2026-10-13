"""The calendar check: a store's prints against the session table of each root's calendar,
trade date by trade date (`02-engine-and-data.md` §1.3, step 1.3).

For each dataset of bars or ticks, the check takes each trade date's first and last print, the
first bar's `ts_open` and the last bar's `ts_close`, or the first and last `ts_recv` of trades
and TBBO (keyed by their partition's trade date), across all of the root's contracts, and
compares them with that trade date's session in the root's calendar
(`fefat.market.instruments`, `fefat.market.builtin_calendars`). It reports a print before the
open or after the close, a first print more than `tolerance` after the open, a last print more
than `tolerance` before the close, and a trade date the calendar has no session for.
Definitions, statistics, and funding hold no session prints and are not checked. A half-day
the holiday rules lack shows as an early last print: add it to
`fefat.market.builtin_calendars.OVERRIDES` with its source.

    paths = resolve_paths(os.environ)
    print(validate_calendar(Store(paths.data_dir), paths.cache_dir).summary())
"""

import itertools
from collections.abc import Iterator
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import polars as pl
from pydantic import Field, model_validator

from fefat.market import instruments
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import Session, sessions_of, utc_text
from fefat.market.layout import Dataset, Partition
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


class CalendarMismatch(FrozenModel):
    """A trade date of a dataset whose first and last prints, in nanoseconds since the Unix
    epoch, UTC, disagree with its session; `session` is None only for a trade date that has
    none."""

    dataset: Dataset
    trade_date: date
    kind: MismatchKind
    first_print: int
    last_print: int
    session: Session | None

    @model_validator(mode="after")
    def _a_session_unless_the_day_has_none(self) -> Self:
        if (self.session is None) != (self.kind is MismatchKind.NO_SESSION):
            raise ValueError(
                f"Expected a session with every mismatch but {MismatchKind.NO_SESSION}, got "
                f"{self.kind} with the session {self.session}."
            )
        return self

    def describe(self) -> str:
        """One line: the dataset, the trade date, the kind, and the observed and expected times."""
        observed = f"prints {utc_text(self.first_print)} to {utc_text(self.last_print)}"
        heading = f"{self.dataset.relative_folder()} {self.trade_date} {self.kind}: {observed}"
        if self.session is None:
            return f"{heading}, on a day without a session"
        return f"{heading}, session {utc_text(self.session.open)} to {utc_text(self.session.close)}"


class CalendarReport(FrozenModel):
    """What `validate_calendar` found: how many dataset trade dates it checked, and the
    mismatches, sorted by dataset, trade date, and kind."""

    days_checked: int = Field(ge=0)
    mismatches: tuple[CalendarMismatch, ...]

    def summary(self) -> str:
        """A line per mismatch with its trade date and times, or one line saying there are none."""
        if not self.mismatches:
            return f"No mismatches over {self.days_checked} trade dates."
        heading = f"Mismatches over {self.days_checked} trade dates: {len(self.mismatches)}"
        return "\n".join([heading, *(mismatch.describe() for mismatch in self.mismatches)])


def validate_calendar(
    store: Store, cache_folder: Path, tolerance: timedelta = DEFAULT_TOLERANCE
) -> CalendarReport:
    """Compare each bar and tick dataset of `store` with its root's session calendar, whose
    table `fefat.market.calendar.sessions_of` keeps in `cache_folder`. A root missing from
    the instrument table is refused, since its calendar is unknown."""
    days_checked = 0
    mismatches: list[CalendarMismatch] = []
    for dataset, partitions in _checked_datasets(store):
        calendar = BUILT_IN[instruments.get(dataset.root).calendar_id]
        prints = _prints_by_trade_date(store, partitions)
        days_checked += prints.height
        joined = sessions_of(calendar, cache_folder).with_sessions(prints)
        mismatches.extend(_mismatches(dataset, joined, tolerance))
    return CalendarReport(days_checked=days_checked, mismatches=tuple(mismatches))


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


def _prints_by_trade_date(store: Store, partitions: list[Partition]) -> pl.DataFrame:
    """Per trade date: the first print, the last print, and the end of the last print (the last
    bar's `ts_close`, or the nanosecond after the last tick), across the partitions."""
    return (
        pl.concat([_partition_prints(store, partition) for partition in partitions])
        .group_by("trade_date")
        .agg(pl.col("first_print").min(), pl.col("last_print").max(), pl.col("last_end").max())
        .sort("trade_date")
        .collect()
    )


def _partition_prints(store: Store, partition: Partition) -> pl.LazyFrame:
    rows = store.scan_partition(partition)
    if partition.dataset.schema_name.kind is SchemaKind.OHLCV:
        return rows.group_by("trade_date").agg(
            first_print=pl.col("ts_open").min(),
            last_print=pl.col("ts_close").max(),
            last_end=pl.col("ts_close").max(),
        )
    return rows.select(
        trade_date=pl.lit(partition.key, dtype=pl.Date),
        first_print=pl.col("ts_recv").min(),
        last_print=pl.col("ts_recv").max(),
        last_end=pl.col("ts_recv").max() + 1,
    )


def _mismatches(
    dataset: Dataset, joined: pl.DataFrame, tolerance: timedelta
) -> list[CalendarMismatch]:
    margin = tolerance // timedelta(microseconds=1) * 1_000
    checks = {
        MismatchKind.NO_SESSION: pl.col("session_open").is_null(),
        MismatchKind.PRINT_BEFORE_OPEN: pl.col("first_print") < pl.col("session_open"),
        MismatchKind.PRINT_AFTER_CLOSE: pl.col("last_end") > pl.col("session_close"),
        MismatchKind.LATE_FIRST_PRINT: pl.col("first_print") > pl.col("session_open") + margin,
        MismatchKind.EARLY_LAST_PRINT: pl.col("last_end") < pl.col("session_close") - margin,
    }
    found = pl.concat(
        [
            joined.filter(condition).with_columns(kind=pl.lit(str(kind)))
            for kind, condition in checks.items()
        ]
    ).sort("trade_date", "kind")
    return [_mismatch(dataset, row) for row in found.iter_rows(named=True)]


def _mismatch(dataset: Dataset, row: dict[str, Any]) -> CalendarMismatch:
    session = None
    if row["session_open"] is not None:
        session = Session(
            trade_date=row["trade_date"], open=row["session_open"], close=row["session_close"]
        )
    return CalendarMismatch(
        dataset=dataset,
        trade_date=row["trade_date"],
        kind=row["kind"],
        first_print=row["first_print"],
        last_print=row["last_print"],
        session=session,
    )
