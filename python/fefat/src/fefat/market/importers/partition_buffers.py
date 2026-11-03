"""Rows that wait until their partition is complete, then go to the store in one write
(ADR-0019): a file streams in chunks, while `Store.write_partition` writes a partition whole.

A partition is complete once the file's clock has passed its last trade date by more than
`COMPLETE_AFTER`, so in a file in clock order no later record can belong to it; a row for a
partition already written means the file is out of order across partitions, and is refused. A
partition the store already holds is left alone when it holds exactly these rows, which is
how an interrupted import runs again, and refused otherwise: a file that overlaps an imported
one is not merged into it. A dataset's `dataset.json` is written by its first import and kept
by the later ones, since snapshots pin it (D-11); an import that counts sizes in another unit
than the dataset's, or holds another series kind (step 1.10), is refused.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import polars as pl

from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit, YearMonth
from fefat.market.store import Store

CONTRACT_SIZE = SizeUnit(lot=Decimal(1), asset="contract")
"""A futures dataset's sizes and volumes count contracts."""

COMPLETE_AFTER = timedelta(days=7)
"""How far a file's clock must pass a partition's last trade date for the partition to be
complete. A record lies within a few days of its trade date: a session opens the evening
before it, and a weekend or holiday folded into it, or a record dated by the session before
it, adds at most four days."""

_NANOSECONDS_PER_SECOND = 1_000_000_000


class PartitionBuffers:
    """One file's rows by partition until each is complete, written sorted by `order_column`,
    keeping the order of equal instants (D-36), each dataset described by `metadata`."""

    def __init__(self, store: Store, order_column: str, metadata: DatasetMetadata) -> None:
        self._store = store
        self._order_column = order_column
        self._metadata = metadata
        self._waiting: dict[Partition, list[pl.DataFrame]] = {}
        self._done: set[Partition] = set()
        self._described: set[Dataset] = set()
        self.written = 0
        self.kept = 0

    def add(self, rows: Mapping[Partition, pl.DataFrame]) -> None:
        """Hold the rows of each partition; rows of a partition already written are refused."""
        for partition, frame in rows.items():
            if partition in self._done:
                raise ValueError(
                    f"Expected the records of {partition.relative_path()} together in clock "
                    "order, got more after it was complete and written: the file is out of "
                    "order across partitions."
                )
            self._waiting.setdefault(partition, []).append(frame)

    def write_complete(self, latest: int) -> None:
        """Write every partition whose last trade date lies more than `COMPLETE_AFTER` before
        `latest`, the latest instant of the file so far."""
        today = datetime.fromtimestamp(latest // _NANOSECONDS_PER_SECOND, UTC).date()
        complete = [
            partition
            for partition in self._waiting
            if (last := _last_trade_date(partition)) is not None and today - last > COMPLETE_AFTER
        ]
        for partition in complete:
            self._write(partition)

    def write_all(self) -> None:
        """Write every partition still waiting, at the end of the file: those the store holds
        are compared first, so one that differs refuses the file before any is written."""
        waiting = list(self._waiting)
        for partition in waiting:
            if self._store.has_partition(partition):
                self._write(partition)
        for partition in waiting:
            if partition in self._waiting:
                self._write(partition)

    def _write(self, partition: Partition) -> None:
        rows = pl.concat(self._waiting.pop(partition)).sort(self._order_column, maintain_order=True)
        self._done.add(partition)
        if self._store.has_partition(partition):
            self._keep_stored(partition, rows)
            return
        if partition.dataset not in self._described:
            self._describe(partition.dataset)
            self._described.add(partition.dataset)
        self._store.write_partition(partition, rows)
        self.written += 1

    def _describe(self, dataset: Dataset) -> None:
        if not self._store.has_dataset_metadata(dataset):
            self._store.write_dataset_metadata(dataset, self._metadata)
            return
        stored = self._store.dataset_metadata(dataset)
        if stored.size_unit != self._metadata.size_unit:
            raise ValueError(
                f"Expected the size unit of {dataset.relative_folder()}, {stored.size_unit}, got "
                f"{self._metadata.size_unit} from this import: a dataset counts its sizes in one "
                "unit."
            )
        if stored.series != self._metadata.series:
            raise ValueError(
                f"Expected a {stored.series} series in {dataset.relative_folder()}, got a "
                f"{self._metadata.series} series from this import: dated contracts and a "
                "continuous series are kept in datasets of their own, under providers of their own."
            )

    def _keep_stored(self, partition: Partition, rows: pl.DataFrame) -> None:
        stored = self._store.scan_partition(partition).collect()
        if not stored.equals(rows):
            raise ValueError(
                f"Expected {partition.relative_path()} to hold the {rows.height} rows this file "
                f"gives it, or not to exist, got {stored.height} other rows: a file that "
                "overlaps an imported one is not merged into it."
            )
        self.kept += 1


def _last_trade_date(partition: Partition) -> date | None:
    key = partition.key
    if isinstance(key, YearMonth):
        return key.days()[1]
    return key
