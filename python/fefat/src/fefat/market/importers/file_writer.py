"""One DBN file's records read against the store, then written (step 5.14): each frame placed
(`fefat.market.importers.canonical`), the file's clock checked to never decrease
(`02-engine-and-data.md` §1.1), and the rows held until their partitions are complete and read
against what the store holds of them (`fefat.market.importers.partition_buffers`).
`checked_records` goes over the file without writing and adds up what happened, and what the
file adds to each dataset, into the file's report; `write_records` goes over it again and writes
the partitions that change, so that a file refused part way has written nothing.
"""

from collections.abc import Iterable, Iterator
from dataclasses import replace

import polars as pl

from fefat.market.importers.canonical import (
    CONTRACT_COUNTS,
    EARLY_COUNTS,
    SPREAD_COUNTS,
    PlacedRecords,
    RecordPlacement,
)
from fefat.market.importers.partition_buffers import (
    MergeTally,
    PartitionBuffers,
    day_records,
    write_merges,
)
from fefat.market.importers.partition_merge import (
    DifferingRecords,
    PartitionMerge,
    RecordIdentity,
)
from fefat.market.importers.report import (
    ClockDecrease,
    ContractRecords,
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


class _FilePass:
    """One pass over a file's record frames, in file order: its clock, what each frame set
    aside, and the merge of each partition with what the store holds of it, as it completes."""

    def __init__(self, placement: RecordPlacement, store: Store, metadata: DatasetMetadata) -> None:
        self.clock = FileClock(placement.clock_column())
        self.placed: list[PlacedRecords] = []
        self._placement = placement
        identity = RecordIdentity(clock=placement.order_column())
        self._buffers = PartitionBuffers(store, identity, metadata)

    def merges(self, records: Iterable[pl.DataFrame]) -> Iterator[PartitionMerge]:
        for frame in records:
            self.clock.observe(frame)
            chunk = self._placement.placed(frame)
            self._buffers.add(chunk.partitions)
            self.placed.append(replace(chunk, partitions={}))
            if self.clock.latest is not None:
                yield from self._buffers.complete(self.clock.latest)
        yield from self._buffers.rest()


def checked_records(
    records: Iterable[pl.DataFrame],
    placement: RecordPlacement,
    store: Store,
    raw_path: str,
    metadata: DatasetMetadata,
    on_differing: DifferingRecords,
) -> FileImport:
    """Place a file's record frames and read each of its partitions against the store, writing
    nothing, each dataset they reach described as `metadata` describes it, and report what the
    file adds to each dataset under `on_differing` and what was set aside; `raw_path` names the
    file in the report. A file the store cannot take is refused here, before `write_records`
    writes a partition."""
    passed = _FilePass(placement, store, metadata)
    tally = MergeTally(on_differing)
    for merge in passed.merges(records):
        tally.add(merge)
    clock, placed = passed.clock, passed.placed
    return FileImport(
        path=raw_path,
        schema_name=placement.schema_name,
        dbn_version=placement.metadata.version,
        records=clock.records,
        first_instant=clock.earliest,
        last_instant=clock.latest,
        contracts=_contracts(placed),
        merges=tally.datasets(),
        spreads=_spreads(placed),
        before_first_trade_date=_early(placed),
        outside_sessions=day_records(chunk.outside_sessions for chunk in placed),
        unreliable_ts_recv=day_records(chunk.unreliable_ts_recv for chunk in placed),
        clock_decreases=clock.decreases,
        first_clock_decrease=clock.first_decrease,
    )


def write_records(
    records: Iterable[pl.DataFrame],
    placement: RecordPlacement,
    store: Store,
    metadata: DatasetMetadata,
    differing: DifferingRecords,
) -> None:
    """Go over a file `checked_records` passed again and write each partition its records
    change, the file's standing at the instants the two dispute where `differing` says so, and
    each new dataset's `dataset.json` from `metadata`."""
    write_merges(store, _FilePass(placement, store, metadata).merges(records), metadata, differing)


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


def _concatenated(frames: list[pl.DataFrame], schema: pl.Schema) -> pl.DataFrame:
    """The frames one below the other, in the columns and types of `schema`."""
    return pl.concat([pl.DataFrame(schema=schema), *(frame.cast(schema) for frame in frames)])
