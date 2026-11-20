"""The stored partitions beside each of a file's partitions (step 5.16, ADR-0024): of its
contract, the nearest below and the nearest above it by key, as the store listed the contract's
dataset when one pass over the file first reached it, so that a partition new to the store is
never a neighbour, and one the write pass rewrites before reading it beside the next has only
gained the file's own records, which leave the rules' verdict as the check pass gave it. Each is
read once a pass, for its instrument ids and the first and last instant of its clock, and lazily
for its records, which the offset rule compares (`fefat.market.importers.stored_offset`).

Two refusals, whatever the import is told. A partition new to the store under another
`instrument_id` than its contract's stored partitions beside it and the file's earlier
partitions of that contract carry, or under two where there are none, since one contract under
two ids loads as two series. And a partition whose records do not lie between those beside it in
time: under one session calendar a contract's trade dates follow its clock, so such records were
dated under another one, and a merge would keep one stretch under two trade dates. Nothing here
writes a file.
"""

import bisect

import polars as pl

from fefat.market.calendar import utc_text
from fefat.market.importers.partition_merge import (
    StoredNeighbour,
    listed_ids,
    refused_for_another_dating,
    two_series,
)
from fefat.market.layout import Dataset, Partition
from fefat.market.store import Store

type Beside = tuple[StoredNeighbour | None, StoredNeighbour | None]
"""A partition's stored neighbours below and above it, None where the store holds none."""


class StoredNeighbours:
    """The stored partitions beside each of one pass's partitions, and the rules they hold the
    file's records to (module docstring)."""

    def __init__(self, store: Store, clock: str) -> None:
        self._store = store
        self._clock = clock
        self._listed: dict[Dataset, dict[str, list[Partition]]] = {}
        self._read: dict[Partition, StoredNeighbour | None] = {}
        self._file_ids: dict[tuple[Dataset, str], frozenset[int]] = {}

    def beside(
        self, partition: Partition, rows: pl.DataFrame, stored: bool
    ) -> tuple[StoredNeighbour, ...]:
        """The stored partitions of `partition`'s contract beside it, once `rows`, the file's of
        it in clock order, carry the contract's instrument ids, where the store does not hold
        `partition`, whose own ids the merge compares with the file's (`stored`), and lie
        between those partitions in time."""
        nearest = self._nearest(partition)
        ids = frozenset(rows.get_column("instrument_id").unique().to_list())
        if not stored:
            self._require_the_contracts_ids(partition, ids, nearest)
        self._require_between(partition, rows, nearest)
        contract = (partition.dataset, partition.contract)
        self._file_ids[contract] = self._file_ids.get(contract, frozenset()) | ids
        return tuple(neighbour for neighbour in nearest if neighbour is not None)

    def _nearest(self, partition: Partition) -> Beside:
        listed = self._listed_of(partition.dataset).get(partition.contract)
        if partition.key is None or listed is None:
            return None, None
        key = str(partition.key)
        lower = bisect.bisect_left(listed, key, key=_key_text)
        upper = bisect.bisect_right(listed, key, key=_key_text)
        below = self._neighbour(listed[lower - 1]) if lower > 0 else None
        above = self._neighbour(listed[upper]) if upper < len(listed) else None
        return below, above

    def _listed_of(self, dataset: Dataset) -> dict[str, list[Partition]]:
        """The dataset's stored partitions with a key by contract, listed once a pass: the
        store's listing is sorted by path, so a contract's partitions come in the order of their
        keys."""
        if dataset not in self._listed:
            by_contract: dict[str, list[Partition]] = {}
            for file in self._store.list_partitions(dataset):
                if file.partition.key is not None:
                    by_contract.setdefault(file.partition.contract, []).append(file.partition)
            self._listed[dataset] = by_contract
        return self._listed[dataset]

    def _neighbour(self, partition: Partition) -> StoredNeighbour | None:
        """The stored partition read once for its instrument ids and the span of its clock, and
        lazily for its records; none for a file without a record."""
        if partition not in self._read:
            rows = self._store.scan_partition(partition)
            instant = pl.col(self._clock)
            ids, first, last = (
                rows.select(
                    ids=pl.col("instrument_id").unique().implode(),
                    first=instant.min(),
                    last=instant.max(),
                )
                .collect()
                .row(0)
            )
            self._read[partition] = (
                None
                if first is None
                else StoredNeighbour(
                    partition=partition,
                    rows=rows,
                    instrument_ids=frozenset(ids),
                    first=first,
                    last=last,
                )
            )
        return self._read[partition]

    def _require_the_contracts_ids(
        self, partition: Partition, ids: frozenset[int], nearest: Beside
    ) -> None:
        """Refuse a partition new to the store whose records carry another id than its
        contract's stored partitions beside it and the file's earlier partitions of it, or two
        where there are none."""
        held = (neighbour.instrument_ids for neighbour in nearest if neighbour is not None)
        stored = frozenset[int]().union(*held)
        earlier = self._file_ids.get((partition.dataset, partition.contract), frozenset())
        others = ids - stored - earlier
        path = partition.relative_path()
        if stored and others:
            raise ValueError(
                f"Expected the records of {path} under the instrument_id that "
                f"{partition.contract} carries beside them, {listed_ids(stored | earlier)}, got "
                f"{listed_ids(others)} from this file: {two_series(partition.dataset)}"
            )
        if earlier and others:
            raise ValueError(
                f"Expected the records of {path} under the instrument_id this file gives "
                f"{partition.contract} before them, {listed_ids(earlier)}, got "
                f"{listed_ids(others)}: {_named_twice(partition.contract)}"
            )
        if not stored and not earlier and len(ids) > 1:
            raise ValueError(
                f"Expected the records of {path} under one instrument_id, got {listed_ids(ids)}: "
                f"{_named_twice(partition.contract)}"
            )

    def _require_between(self, partition: Partition, rows: pl.DataFrame, nearest: Beside) -> None:
        """Refuse records of the file's partition that do not lie after the last instant of the
        stored partition below it and before the first of the one above."""
        below, above = nearest
        first, last = rows.item(0, self._clock), rows.item(-1, self._clock)
        if below is not None and first <= below.last:
            raise ValueError(
                f"Expected the records of {partition.relative_path()} after those the store "
                f"holds of {partition.contract} under {below.partition.key}, which end at "
                f"{utc_text(below.last)}, got records from {utc_text(first)}: "
                f"{_dated_twice(partition, below)}"
            )
        if above is not None and last >= above.first:
            raise ValueError(
                f"Expected the records of {partition.relative_path()} before those the store "
                f"holds of {partition.contract} under {above.partition.key}, which start at "
                f"{utc_text(above.first)}, got records to {utc_text(last)}: "
                f"{_dated_twice(partition, above)}"
            )


def _key_text(partition: Partition) -> str:
    """A partition's key as text, which sorts as the keys do: a trade date or a month written in
    ISO 8601."""
    return str(partition.key)


def _named_twice(contract: str) -> str:
    return (
        "one contract under two ids loads as two series, so the file is refused whatever the "
        f"import is told, and nothing was written. The download names two instruments "
        f"{contract}, as a symbol listed again a decade later can: leave the other instrument's "
        "records out of it."
    )


def _dated_twice(partition: Partition, neighbour: StoredNeighbour) -> str:
    return (
        f"the file dates under {partition.key} what the store dates under "
        f"{neighbour.partition.key}, as a change of the session calendar between the two imports "
        "gives, and a merge would keep that stretch under two trade dates. "
        f"{refused_for_another_dating(partition.dataset)}"
    )
