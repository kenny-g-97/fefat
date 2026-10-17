"""Writing one DBN file's records to the store: each frame placed
(`fefat.market.importers.canonical`), the file's clock checked to never decrease
(`02-engine-and-data.md` §1.1), the rows held until their partitions are complete
(`fefat.market.importers.partition_buffers`), and what happened added up into the file's
report.
"""

from collections.abc import Iterable
from dataclasses import replace

import polars as pl

from fefat.market.importers.canonical import (
    CONTRACT_COUNTS,
    DAY_COUNTS,
    EARLY_COUNTS,
    SPREAD_COUNTS,
    PlacedRecords,
    RecordPlacement,
)
from fefat.market.importers.partition_buffers import PartitionBuffers
from fefat.market.importers.report import (
    ClockDecrease,
    ContractRecords,
    DayRecords,
    EarlySymbol,
    FileImport,
    SymbolRecords,
)
from fefat.market.layout import DatasetMetadata
from fefat.market.store import Store


class FileClock:
    """One file's clock, checked to never decrease: the records seen, the decreases (a record
    earlier than the record before it) with the first of them, and the earliest and latest
    instants."""

    def __init__(self, column: str) -> None:
        self.column = column
        self.records = 0
        self.decreases = 0
        self.first_decrease: ClockDecrease | None = None
        self.earliest: int | None = None
        self.latest: int | None = None
        self._last: int | None = None

    def observe(self, records: pl.DataFrame) -> None:
        instants = records.get_column(self.column)
        before = instants.shift(1)
        if self._last is not None:
            before = before.fill_null(self._last)
        decreased = instants < before
        if self.first_decrease is None and decreased.any():
            index = int(decreased.arg_true()[0])
            self.first_decrease = ClockDecrease(
                record=self.records + index, instant=instants[index], before=before[index]
            )
        self.decreases += int(decreased.sum())
        self.records += records.height
        self._last = instants[-1]
        instant = pl.col(self.column)
        bounds = records.select(earliest=instant.min(), latest=instant.max())
        earliest, latest = bounds.row(0)
        self.earliest = earliest if self.earliest is None else min(self.earliest, earliest)
        self.latest = latest if self.latest is None else max(self.latest, latest)


def write_records(
    records: Iterable[pl.DataFrame],
    placement: RecordPlacement,
    store: Store,
    raw_path: str,
    metadata: DatasetMetadata,
) -> FileImport:
    """Place and write a file's record frames, in file order, each dataset they reach described
    by `metadata`, and report what was written and what was set aside; `raw_path` names the
    file in the report."""
    clock = FileClock(placement.clock_column())
    buffers = PartitionBuffers(store, placement.order_column(), metadata)
    placed: list[PlacedRecords] = []
    for frame in records:
        clock.observe(frame)
        chunk = placement.placed(frame)
        buffers.add(chunk.partitions)
        if clock.latest is not None:
            buffers.write_complete(clock.latest)
        placed.append(replace(chunk, partitions={}))
    buffers.write_all()
    return FileImport(
        path=raw_path,
        schema_name=placement.schema_name,
        dbn_version=placement.metadata.version,
        records=clock.records,
        first_instant=clock.earliest,
        last_instant=clock.latest,
        contracts=_contracts(placed),
        partitions_written=buffers.written,
        partitions_kept=buffers.kept,
        spreads=_spreads(placed),
        before_first_trade_date=_early(placed),
        outside_sessions=_days([chunk.outside_sessions for chunk in placed]),
        unreliable_ts_recv=_days([chunk.unreliable_ts_recv for chunk in placed]),
        clock_decreases=clock.decreases,
        first_clock_decrease=clock.first_decrease,
    )


def _contracts(placed: list[PlacedRecords]) -> tuple[ContractRecords, ...]:
    totals = (
        _concatenated([chunk.contracts for chunk in placed], CONTRACT_COUNTS)
        .group_by("root", "contract", "expiry")
        .agg(pl.col("records").sum(), pl.col("first_instant").min(), pl.col("last_instant").max())
        .sort("root", "expiry", "contract")
    )
    return tuple(ContractRecords.model_validate(row) for row in totals.iter_rows(named=True))


def _spreads(placed: list[PlacedRecords]) -> tuple[SymbolRecords, ...]:
    totals = (
        _concatenated([chunk.spreads for chunk in placed], SPREAD_COUNTS)
        .group_by("raw_symbol")
        .agg(pl.col("records").sum())
        .sort("raw_symbol")
    )
    return tuple(SymbolRecords.model_validate(row) for row in totals.iter_rows(named=True))


def _early(placed: list[PlacedRecords]) -> tuple[EarlySymbol, ...]:
    totals = (
        _concatenated([chunk.early for chunk in placed], EARLY_COUNTS)
        .group_by("raw_symbol")
        .agg(
            pl.col("records").sum(),
            pl.col("first_trade_date").min(),
            pl.col("last_trade_date").max(),
        )
        .sort("raw_symbol")
    )
    return tuple(EarlySymbol.model_validate(row) for row in totals.iter_rows(named=True))


def _days(counts: list[pl.DataFrame]) -> tuple[DayRecords, ...]:
    totals = (
        _concatenated(counts, DAY_COUNTS)
        .group_by("trade_date")
        .agg(pl.col("records").sum())
        .sort("trade_date")
    )
    return tuple(DayRecords.model_validate(row) for row in totals.iter_rows(named=True))


def _concatenated(frames: list[pl.DataFrame], schema: pl.Schema) -> pl.DataFrame:
    """The frames one below the other, in the columns and types of `schema`."""
    return pl.concat([pl.DataFrame(schema=schema), *(frame.cast(schema) for frame in frames)])
