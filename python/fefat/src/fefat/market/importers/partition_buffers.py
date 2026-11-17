"""Rows that wait until their partition is complete, then are read against what the store holds
of it (ADR-0019, ADR-0021): a file streams in chunks, while a partition is merged and written
whole.

A partition is complete once the file's clock has passed its last trade date by more than
`COMPLETE_AFTER`, so in a file in clock order no later record can belong to it; a row for a
partition already complete means the file is out of order across partitions, and is refused.
`PartitionBuffers` gives each complete partition as a `PartitionMerge`
(`fefat.market.importers.partition_merge`), the file's rows read against the stored ones, and
writes nothing. An import goes over its file twice: first to check and count every partition
(`MergeTally`, `require_none_differing`), then, once nothing refuses the file, to write the
partitions that change (`write_merges`), so that a refused file leaves the store as it was
(step 5.14). A dataset's `dataset.json` is written by its first import and kept by the later
ones, since snapshots pin it (D-11); an import that counts sizes in another unit than the
dataset's, or holds another series kind (step 1.10), is refused, whether or not it adds a
record.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl

from fefat.market.importers.canonical import DAY_COUNTS
from fefat.market.importers.partition_merge import (
    DifferingRecords,
    PartitionMerge,
    RecordIdentity,
    merged_partition,
)
from fefat.market.importers.report import DIFFERING_ADVICE, DatasetMerge, DayRecords
from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit, YearMonth
from fefat.market.store import Store

CONTRACT_SIZE = SizeUnit(lot=Decimal(1), asset="contract")
"""A futures dataset's sizes and volumes count contracts."""

COMPLETE_AFTER = timedelta(days=7)
"""How far a file's clock must pass a partition's last trade date for the partition to be
complete. A record lies within a few days of its trade date: a session opens the evening
before it, and a weekend or holiday folded into it, or a record dated by the session before
it, adds at most four days."""

DIFFERING_TAKEN_RECORDED = ", the file's records taken where they differ"
"""How the raw manifest records, after an import's other details, that the import was told that
the file's records stand (`DifferingRecords.TAKE_THE_FILE`): the rule it ran under, whatever it
then found to differ, so that an import cut short and run again records the same."""

_NANOSECONDS_PER_SECOND = 1_000_000_000


class PartitionBuffers:
    """One file's rows by partition until each is complete, then read, sorted by the clock and
    keeping the order of equal instants (D-36), against the rows the store holds of the
    partition; each dataset they reach must count its sizes and hold its series as `metadata`
    does."""

    def __init__(self, store: Store, identity: RecordIdentity, metadata: DatasetMetadata) -> None:
        self._store = store
        self._identity = identity
        self._metadata = metadata
        self._waiting: dict[Partition, list[pl.DataFrame]] = {}
        self._done: set[Partition] = set()
        self._agreeing: set[Dataset] = set()

    def add(self, rows: Mapping[Partition, pl.DataFrame]) -> None:
        """Hold the rows of each partition; rows of a partition already complete are refused."""
        for partition, frame in rows.items():
            if partition in self._done:
                raise ValueError(
                    f"Expected the records of {partition.relative_path()} together in clock "
                    "order, got more after it was complete: the file is out of order across "
                    "partitions."
                )
            self._waiting.setdefault(partition, []).append(frame)

    def complete(self, latest: int) -> Iterator[PartitionMerge]:
        """The merge of every partition whose last trade date lies more than `COMPLETE_AFTER`
        before `latest`, the latest instant of the file so far, one in memory at a time."""
        today = datetime.fromtimestamp(latest // _NANOSECONDS_PER_SECOND, UTC).date()
        complete = [
            partition
            for partition in self._waiting
            if (last := _last_trade_date(partition)) is not None and today - last > COMPLETE_AFTER
        ]
        for partition in complete:
            yield self._merged(partition)

    def rest(self) -> Iterator[PartitionMerge]:
        """The merge of every partition still waiting, at the end of the file."""
        for partition in list(self._waiting):
            yield self._merged(partition)

    def _merged(self, partition: Partition) -> PartitionMerge:
        clock = self._identity.clock
        rows = pl.concat(self._waiting.pop(partition)).sort(clock, maintain_order=True)
        self._done.add(partition)
        self._require_the_datasets_terms(partition.dataset)
        stored = None
        if self._store.has_partition(partition):
            stored = self._store.scan_partition(partition).collect()
        return merged_partition(partition, stored, rows, self._identity)

    def _require_the_datasets_terms(self, dataset: Dataset) -> None:
        """Refuse, once for each dataset the store describes, an import whose sizes count
        another unit than its `dataset.json`, or whose series is of another kind."""
        if dataset in self._agreeing or not self._store.has_dataset_metadata(dataset):
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
        self._agreeing.add(dataset)


@dataclass(frozen=True)
class _PartitionCounts:
    """What a tally keeps of a partition's merge: its counts and trade dates, not its rows."""

    changes: bool
    added: int
    held: int
    differing: int
    stored_disputed: int
    new_days: pl.DataFrame
    extended_days: pl.DataFrame
    differing_days: pl.DataFrame


class MergeTally:
    """A file's merges added up for each dataset, as an import that settles differing records
    by `on_differing` reports them (`DatasetMerge`)."""

    def __init__(self, on_differing: DifferingRecords) -> None:
        self._on_differing = on_differing
        self._counted: dict[Dataset, list[_PartitionCounts]] = {}

    def add(self, merge: PartitionMerge) -> None:
        """Count a partition's merge, keeping none of its rows: a trade date that gains records
        is new where the stored partition held none of it, so a session is new, or gains
        records, for its contract."""
        gaining = merge.added_days()
        on_a_held_day = pl.col("trade_date").is_in(merge.held_days().implode())
        counts = _PartitionCounts(
            changes=merge.changes(self._on_differing),
            added=merge.added.height,
            held=merge.held,
            differing=merge.differing.height,
            stored_disputed=merge.stored_records_disputed(),
            new_days=gaining.filter(~on_a_held_day),
            extended_days=gaining.filter(on_a_held_day),
            differing_days=merge.differing_days(),
        )
        self._counted.setdefault(merge.partition.dataset, []).append(counts)

    def datasets(self) -> tuple[DatasetMerge, ...]:
        """What the file adds to each dataset it reaches, sorted by the dataset's folder."""
        by_folder = sorted(self._counted, key=lambda dataset: dataset.relative_folder().as_posix())
        return tuple(self._dataset_merge(dataset) for dataset in by_folder)

    def _dataset_merge(self, dataset: Dataset) -> DatasetMerge:
        counted = self._counted[dataset]
        return DatasetMerge(
            dataset=dataset,
            on_differing=self._on_differing,
            records_added=sum(each.added for each in counted),
            records_held=sum(each.held for each in counted),
            records_differing=sum(each.differing for each in counted),
            stored_records_disputed=sum(each.stored_disputed for each in counted),
            new_sessions=day_records(each.new_days for each in counted),
            extended_sessions=day_records(each.extended_days for each in counted),
            differing_sessions=day_records(each.differing_days for each in counted),
            partitions_changed=sum(each.changes for each in counted),
            partitions_unchanged=sum(not each.changes for each in counted),
        )


def day_records(counts: Iterable[pl.DataFrame]) -> tuple[DayRecords, ...]:
    """The records per trade date of `counts`, frames with the columns of `DAY_COUNTS`, added up
    and sorted by trade date."""
    frames = [pl.DataFrame(schema=DAY_COUNTS), *(frame.cast(DAY_COUNTS) for frame in counts)]
    totals = pl.concat(frames).group_by("trade_date").agg(pl.col("records").sum())
    return tuple(
        DayRecords.model_validate(row) for row in totals.sort("trade_date").iter_rows(named=True)
    )


def require_none_differing(merges: Iterable[DatasetMerge], source: Path) -> None:
    """Refuse, before anything is written, a file some of whose records differ from the store's
    while its import does not let the file's stand (`DatasetMerge.refuses`)."""
    refusing = [merge for merge in merges if merge.refuses()]
    if not refusing:
        return
    raise ValueError(
        f"Expected the records {source} shares with the store to be the ones the store holds, "
        f"got {'; '.join(merge.disagreement() for merge in refusing)}: nothing was written. "
        f"{DIFFERING_ADVICE}"
    )


def require_one_price_basis(merge: DatasetMerge) -> None:
    """Refuse, whatever the import is told, a file of a back-adjusted series the store holds
    that holds none of the store's bars: a platform adjusts such a series again at each roll,
    so a later export moves every price before that roll, and a file that shares no bar with
    the store cannot be told from one adjusted since, whether its bars differ from the stored
    ones or only carry the series on. A file that holds a stored bar was exported on the
    store's price basis, and is left to the import's rule for differing records, as one that
    completes the store's last bar is."""
    if merge.records_held:
        return
    raise ValueError(
        "Expected the file to hold at least one bar that the store holds of the back-adjusted "
        f"series {merge.dataset.relative_folder()}, got none, with {merge.records_differing:,} "
        f"of its records at other values than the stored ones and {merge.records_added:,} that "
        "the store lacks: a platform adjusts such a series again at each roll, so a later "
        "export moves every price before that roll, and without a bar the two share the file "
        "cannot be told from one adjusted since. The file is refused whatever the import is "
        "told, and nothing was written. Export it again from a bar the store holds. Where its "
        "bars then differ from the stored ones, the series was adjusted since: import the "
        "later export whole under a provider of its own, through a copy of its profile."
    )


def write_merges(
    store: Store,
    merges: Iterable[PartitionMerge],
    metadata: DatasetMetadata,
    differing: DifferingRecords,
) -> None:
    """Write each merge that changes its partition under `differing`, a dataset's `dataset.json`
    first where the store has none. An operating system's error part way, as Windows gives for a
    file another program holds open, is told with what was written before it: the import run
    again finishes it, since the records it wrote read as held. A merge with records that
    differ, where the import was not told that the file's stand, so that its check refuses them
    and found none, stops the write: the store or the file changed between the two passes. The
    importers call it under the store's import lock (`Store.held_for_an_import`, step 5.12), and
    its merges read the stored partitions again, so that two imports at once lose no record."""
    written = 0
    for merge in merges:
        if differing is not DifferingRecords.TAKE_THE_FILE and not merge.differing.is_empty():
            raise ValueError(
                f"Expected {merge.partition.relative_path()} as the import's check read it, got "
                f"{merge.differing.height:,} of the file's records with other values than the "
                f"stored ones, after {written} of the file's partitions were written: the store "
                "or the file changed while the import ran. Preview the file before importing it "
                "again."
            )
        if not merge.changes(differing):
            continue
        try:
            _write(store, merge, metadata, differing)
        except OSError as error:
            raise ValueError(
                f"Expected to write {merge.partition.relative_path()}, got {error}, after "
                f"{written} of the file's partitions were written. Nothing is lost: run the "
                "import again with the same options, and it finishes what this one left."
            ) from error
        written += 1


def _write(
    store: Store, merge: PartitionMerge, metadata: DatasetMetadata, differing: DifferingRecords
) -> None:
    dataset = merge.partition.dataset
    if not store.has_dataset_metadata(dataset):
        store.write_dataset_metadata(dataset, metadata)
    store.write_partition(merge.partition, merge.rows(differing))


def _last_trade_date(partition: Partition) -> date | None:
    key = partition.key
    if isinstance(key, YearMonth):
        return key.days()[1]
    return key
