"""The bar check: one trade date of a root's bars rebuilt from the finer data the store holds and
compared with the stored ones (`02-engine-and-data.md` §1.4, step 1.5).

For each provider of the root, `verify_bars` rebuilds every stored bar schema of the trade date
from the data below it with `fefat.market.bars`: 1-second and 1-minute bars from trades,
1-minute bars from 1-second bars, and 5-minute and daily bars from 1-minute bars. It lists each
bar on which the two sides differ, by instrument and `ts_open`: a column with both values
(`ts_close`, `trade_date`, the prices, `volume`, and `trade_count` where both sides know it),
or a bar only one side holds. `vwap` is compared nowhere, since vendors' bars carry none
and each resampling rounds it down. A comparison whose stored bars exist without the data to
rebuild them is pending, such as the tick-level one until a trades file is imported, and one
without stored bars is not available. One comparison always runs on the finest data present:
resampled to 5-minute bars and then to daily bars, it must give the daily bars it gives at once,
so a store of a vendor's 1-minute bars alone still checks the resampling on real data. Every
print of a trade date is received before the next session opens, so its bars are complete then.

    paths = resolve_paths(os.environ)
    print(verify_bars(Store(paths.data_dir), "MES", date(2026, 9, 21), paths.cache_dir).summary())
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import polars as pl
from pydantic import Field

from fefat.market.bars import build_bars, resample_bars
from fefat.market.calendar import SessionTable, utc_text
from fefat.market.engine_units import price_text
from fefat.market.layout import FolderName, Partition, PartitionRequest
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import (
    BarSchemaName,
    FrozenModel,
    RecordSchemaName,
    SchemaKind,
    SchemaName,
    Timeframe,
    TimeUnit,
)
from fefat.market.store import Store


def _bars_of(count: int, unit: TimeUnit) -> BarSchemaName:
    return BarSchemaName(timeframe=Timeframe(count=count, unit=unit))


_TRADES = RecordSchemaName(kind=SchemaKind.TRADES)
_SECONDS = _bars_of(1, TimeUnit.SECOND)
_MINUTES = _bars_of(1, TimeUnit.MINUTE)
_FIVE_MINUTES = _bars_of(5, TimeUnit.MINUTE)
_DAYS = _bars_of(1, TimeUnit.DAY)
_FINEST_FIRST: tuple[SchemaName, ...] = (_TRADES, _SECONDS, _MINUTES)
STORED_FROM_FINER: tuple[tuple[SchemaName, BarSchemaName], ...] = (
    (_TRADES, _SECONDS),
    (_TRADES, _MINUTES),
    (_SECONDS, _MINUTES),
    (_MINUTES, _FIVE_MINUTES),
    (_MINUTES, _DAYS),
)
"""Each finer schema beside the stored schema of bars the check rebuilds from it."""
ComparedColumn = Literal[
    "ts_close", "trade_date", "open", "high", "low", "close", "volume", "trade_count"
]
"""A column the check compares; `vwap` is compared nowhere."""
_COMPARED_COLUMNS: tuple[ComparedColumn, ...] = get_args(ComparedColumn)
_PRICE_COLUMNS = frozenset({"open", "high", "low", "close"})


class ComparisonStatus(StrEnum):
    """Whether a comparison of rebuilt bars ran."""

    COMPARED = "compared"
    PENDING = "pending"
    NOT_AVAILABLE = "not-available"


class Side(StrEnum):
    """A side of a comparison: the bars rebuilt, or the reference they are compared with."""

    REBUILT = "rebuilt"
    REFERENCE = "reference"


class ColumnDifference(FrozenModel):
    """A bar both sides hold, found by `instrument_id` and `ts_open`, whose `column` they give
    differently, with both values as the report writes them."""

    kind: Literal["column"] = "column"
    instrument_id: int
    ts_open: int
    column: ComparedColumn
    rebuilt: str
    reference: str

    def describe(self) -> str:
        """One indented line: the bar, the column, and both values."""
        values = f"{self.column} rebuilt {self.rebuilt}, reference {self.reference}"
        return f"  {_bar(self.instrument_id, self.ts_open)}: {values}"


class OneSidedBar(FrozenModel):
    """A bar only one side holds, found by `instrument_id` and `ts_open`."""

    kind: Literal["one-sided"] = "one-sided"
    instrument_id: int
    ts_open: int
    held_by: Side

    def describe(self) -> str:
        """One indented line: the bar and the side that holds it."""
        return f"  {_bar(self.instrument_id, self.ts_open)}: only the {self.held_by} bars hold it"


BarDifference = Annotated[ColumnDifference | OneSidedBar, Field(discriminator="kind")]
"""A bar on which the rebuilt bars and the reference disagree, told apart by `kind`."""


def _bar(instrument_id: int, ts_open: int) -> str:
    return f"instrument_id {instrument_id}, bar opening {utc_text(ts_open)}"


class ComparedBars(FrozenModel):
    """Bars rebuilt along `route`, from its first schema through each next one, compared with
    `reference`: a stored schema, or another route from the same data."""

    status: Literal[ComparisonStatus.COMPARED] = ComparisonStatus.COMPARED
    provider: FolderName
    route: tuple[SchemaName, ...]
    reference: tuple[SchemaName, ...]
    bars_compared: int = Field(ge=0)
    differences: tuple[BarDifference, ...]

    def lines(self) -> list[str]:
        """The comparison's line, then a line per difference."""
        outcome = f"{len(self.differences)} differences" if self.differences else "no differences"
        heading = f"{_heading(self)}: {self.bars_compared:,} compared, {outcome}"
        return [heading, *(difference.describe() for difference in self.differences)]


class UncomparedBars(FrozenModel):
    """A comparison that did not run: pending while its reference is stored without the data to
    rebuild it from, not available while its reference is not stored."""

    status: Literal[ComparisonStatus.PENDING, ComparisonStatus.NOT_AVAILABLE]
    provider: FolderName
    route: tuple[SchemaName, ...]
    reference: tuple[SchemaName, ...]

    def lines(self) -> list[str]:
        """The comparison's line, with what it waits for."""
        if self.status is ComparisonStatus.PENDING:
            return [f"{_heading(self)}: pending, without {self.route[0]} to rebuild from"]
        return [f"{_heading(self)}: no {self.reference[0]} stored to compare with"]


BarsComparison = Annotated[ComparedBars | UncomparedBars, Field(discriminator="status")]
"""A comparison of rebuilt bars, told apart by `status`."""


def _heading(comparison: ComparedBars | UncomparedBars) -> str:
    route = " -> ".join(str(schema) for schema in comparison.route)
    reference = " -> ".join(str(schema) for schema in comparison.reference)
    return f"{comparison.provider}: {route} against {reference}"


class BarsReport(FrozenModel):
    """What `verify_bars` found on a root's trade date: its comparisons, provider by provider."""

    root: str
    trade_date: date
    comparisons: tuple[BarsComparison, ...]

    def comparisons_run(self) -> int:
        """How many comparisons ran: none means nothing was verified."""
        return len(self._compared())

    def difference_count(self) -> int:
        """How many differences the comparisons that ran found."""
        return sum(len(compared.differences) for compared in self._compared())

    def summary(self) -> str:
        """A heading with the comparisons run and the differences found, then a line per
        comparison and per difference."""
        found = self.difference_count()
        differences = str(found) if found else "none"
        heading = (
            f"Bars of {self.root} on {self.trade_date}. Comparisons run: "
            f"{self.comparisons_run()}. Differences: {differences}."
        )
        lines = (line for comparison in self.comparisons for line in comparison.lines())
        return "\n".join([heading, *lines])

    def _compared(self) -> list[ComparedBars]:
        return [
            comparison for comparison in self.comparisons if isinstance(comparison, ComparedBars)
        ]


@dataclass(frozen=True)
class _Rebuild:
    """How the check rebuilds bars: in the root's sessions, with every print of the trade date
    in hand by `received_until`, the next session's open."""

    sessions: SessionTable
    received_until: int

    def along(
        self, rows: pl.DataFrame, source: SchemaName, targets: Sequence[BarSchemaName]
    ) -> pl.DataFrame:
        """`rows` of `source` built into bars of each of `targets` in turn."""
        for step, target in enumerate(targets):
            from_trades = step == 0 and source.kind is SchemaKind.TRADES
            build = build_bars if from_trades else resample_bars
            rows = build(rows, target.timeframe, self.sessions, self.received_until)
        return rows


def verify_bars(store: Store, root: str, trade_date: date, cache_folder: Path) -> BarsReport:
    """Rebuild `root`'s bars of `trade_date` from the finer data `store` holds and compare them
    with the stored ones, provider by provider, in the sessions of the root's calendar, whose
    table is kept in `cache_folder`. A root without trades or bars in the store, a root missing
    from the instrument table, and a date without a session are refused."""
    held = [
        file.partition for file in store.list_partitions() if file.partition.dataset.root == root
    ]
    if not held:
        raise ValueError(f"Expected trades or bars of {root} in the store, got none.")
    sessions = instrument_table(store.folder).sessions_of(root, cache_folder)
    sessions.session(trade_date)
    rebuild = _Rebuild(sessions=sessions, received_until=sessions.following(trade_date).open)
    comparisons: list[ComparedBars | UncomparedBars] = []
    for provider in sorted({partition.dataset.provider for partition in held}):
        of_provider = [partition for partition in held if partition.dataset.provider == provider]
        stored = {
            schema: _stored_rows(store, of_provider, schema, trade_date)
            for schema in (*_FINEST_FIRST, _FIVE_MINUTES, _DAYS)
        }
        comparisons.extend(
            _against_the_stored(provider, stored, source, target, rebuild)
            for source, target in STORED_FROM_FINER
        )
        comparisons.append(_resampling_check(provider, stored, rebuild))
    return BarsReport(root=root, trade_date=trade_date, comparisons=tuple(comparisons))


def _stored_rows(
    store: Store, partitions: Sequence[Partition], schema: SchemaName, trade_date: date
) -> pl.DataFrame | None:
    """The rows of `schema` that `partitions` hold on `trade_date`, or None when they hold none."""
    of_schema = [partition for partition in partitions if partition.dataset.schema_name == schema]
    if not of_schema:
        return None
    request = PartitionRequest(dataset=of_schema[0].dataset, start=trade_date, end=trade_date)
    if not any(request.selects(partition) for partition in of_schema):
        return None
    rows = store.scan(request).collect()
    if rows.is_empty():
        return None
    return rows


def _against_the_stored(
    provider: str,
    stored: Mapping[SchemaName, pl.DataFrame | None],
    source: SchemaName,
    target: BarSchemaName,
    rebuild: _Rebuild,
) -> ComparedBars | UncomparedBars:
    route, reference = (source, target), (target,)
    stored_bars, finer = stored[target], stored[source]
    if stored_bars is None:
        status = ComparisonStatus.NOT_AVAILABLE
        return UncomparedBars(status=status, provider=provider, route=route, reference=reference)
    if finer is None:
        status = ComparisonStatus.PENDING
        return UncomparedBars(status=status, provider=provider, route=route, reference=reference)
    joined = _side_by_side(rebuild.along(finer, source, (target,)), stored_bars)
    return ComparedBars(
        provider=provider,
        route=route,
        reference=reference,
        bars_compared=joined.height,
        differences=_differences(joined),
    )


def _resampling_check(
    provider: str, stored: Mapping[SchemaName, pl.DataFrame | None], rebuild: _Rebuild
) -> ComparedBars | UncomparedBars:
    """The finest data present resampled to 5-minute bars and then to daily bars, against its
    daily bars made at once."""
    present = {schema: rows for schema, rows in stored.items() if rows is not None}
    finest = next((schema for schema in _FINEST_FIRST if schema in present), None)
    if finest is None:
        return UncomparedBars(
            status=ComparisonStatus.NOT_AVAILABLE,
            provider=provider,
            route=(_MINUTES, _FIVE_MINUTES, _DAYS),
            reference=(_MINUTES, _DAYS),
        )
    stepwise = rebuild.along(present[finest], finest, (_FIVE_MINUTES, _DAYS))
    joined = _side_by_side(stepwise, rebuild.along(present[finest], finest, (_DAYS,)))
    return ComparedBars(
        provider=provider,
        route=(finest, _FIVE_MINUTES, _DAYS),
        reference=(finest, _DAYS),
        bars_compared=joined.height,
        differences=_differences(joined),
    )


def _side_by_side(rebuilt: pl.DataFrame, reference: pl.DataFrame) -> pl.DataFrame:
    """A row for every bar either side holds, by instrument and `ts_open`, with the reference's
    columns beside the rebuilt ones, named with `_reference`."""
    return rebuilt.join(
        reference, on=["instrument_id", "ts_open"], how="full", coalesce=True, suffix="_reference"
    )


def _differences(joined: pl.DataFrame) -> tuple[ColumnDifference | OneSidedBar, ...]:
    """The bars of `joined` on which the two sides differ, sorted by instrument and `ts_open`,
    a bar only one side holds before the columns of one both hold; a trade count only one side
    knows is no difference."""
    on_one_side = pl.col("ts_close").is_null() | pl.col("ts_close_reference").is_null()
    differences: list[ColumnDifference | OneSidedBar] = [
        _one_sided(row) for row in joined.filter(on_one_side).iter_rows(named=True)
    ]
    on_both = joined.filter(~on_one_side)
    for column in _COMPARED_COLUMNS:
        ours, theirs = pl.col(column), pl.col(f"{column}_reference")
        differs = ours.ne_missing(theirs)
        if column == "trade_count":
            differs = differs & ours.is_not_null() & theirs.is_not_null()
        rows = on_both.filter(differs).iter_rows(named=True)
        differences.extend(_in_column(row, column) for row in rows)
    return tuple(sorted(differences, key=_order))


def _order(difference: ColumnDifference | OneSidedBar) -> tuple[int, int, int]:
    if isinstance(difference, OneSidedBar):
        return difference.instrument_id, difference.ts_open, -1
    return difference.instrument_id, difference.ts_open, _COMPARED_COLUMNS.index(difference.column)


def _one_sided(row: dict[str, Any]) -> OneSidedBar:
    held_by = Side.REBUILT if row["ts_close_reference"] is None else Side.REFERENCE
    return OneSidedBar(instrument_id=row["instrument_id"], ts_open=row["ts_open"], held_by=held_by)


def _in_column(row: dict[str, Any], column: ComparedColumn) -> ColumnDifference:
    return ColumnDifference(
        instrument_id=row["instrument_id"],
        ts_open=row["ts_open"],
        column=column,
        rebuilt=_written(column, row[column]),
        reference=_written(column, row[f"{column}_reference"]),
    )


def _written(column: str, value: Any) -> str:
    """A value as the report writes it: prices in their currency units, instants in UTC."""
    if value is None:
        return "none"
    if column in _PRICE_COLUMNS:
        return price_text(value)
    if column == "ts_close":
        return utc_text(value)
    return str(value)
