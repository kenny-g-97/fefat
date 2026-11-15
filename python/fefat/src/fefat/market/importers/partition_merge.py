"""Merging a file's rows into the partition the store holds (step 5.14, ADR-0021).

A record's place in a partition is its instant on the store's clock, `ts_open` for bars and
`ts_recv` for everything else, and its position among the records of that instant, in stored or
file order: a bar has its instant to itself, and prints stamped to one second share theirs.
`merged_partition` reads a file's rows of a partition against the stored ones place by place:

- a record at a place the store lacks is added, so a file that carries on an instant the store
  holds the start of adds the rest;
- a record the store holds at its place with the same values in every column is already held;
- an instant with a place the store holds with other values is disputed, and all the file's
  records at it differ. An import refuses them, or, told that the file's stand
  (`DifferingRecords.TAKE_THE_FILE`), takes each disputed instant whole from the file.

Two files it refuses whatever the import is told, since a merge cannot be taken back: one whose
records carry an `instrument_id` the stored partition does not hold, which would make one
contract load as two series, and one that overlaps the stored records in time without sharing a
record with them, as the same prints read under another time zone or stamping rule do, which
would store them twice.

Where a file gives its prints no sequence (`RecordIdentity.numbered_by_place`), the comparison
leaves `sequence` out, a print's sequence is its place in its instant, and a print added to an
instant the store holds is numbered on from the stored prints' last, which keep theirs: the
order within an instant is all the number says (F-CLK-03). Such a file starts on a whole instant
and may stop inside one. Nothing here reads or writes a file.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from fefat.market.calendar import utc_text
from fefat.market.importers.canonical import DAY_COUNTS
from fefat.market.layout import Partition

PLACE = "_place"
"""The column of a record's position among the records of its instant, counted from 0."""


class DifferingRecords(StrEnum):
    """What an import does with the instants a file and the store dispute (ADR-0021): refuse
    the file, or take each such instant whole from the file."""

    REFUSE = "refuse"
    TAKE_THE_FILE = "take-file"


@dataclass(frozen=True)
class RecordIdentity:
    """What tells the records of a partition apart: the clock column they are sorted by, and
    whether the import numbers the prints by their place, since their file gives them no
    sequence."""

    clock: str
    numbered_by_place: bool = False

    def compared_columns(self, columns: list[str]) -> list[str]:
        """The columns two records at one place must agree in to be the same record."""
        if not self.numbered_by_place:
            return columns
        return [name for name in columns if name != "sequence"]


@dataclass(frozen=True)
class PartitionMerge:
    """A file's rows of one partition read against the rows the store holds of it: the stored
    rows, the file's rows the store lacks, how many of the file's it already holds, and the
    file's rows at the instants the two dispute, each frame with its records' `PLACE`."""

    partition: Partition
    clock: str
    kept: pl.DataFrame
    added: pl.DataFrame
    held: int
    differing: pl.DataFrame

    def changes(self, differing: DifferingRecords) -> bool:
        """Whether an import under `differing` writes the partition: it adds records, or takes
        the file's at the disputed instants."""
        takes = differing is DifferingRecords.TAKE_THE_FILE and not self.differing.is_empty()
        return takes or not self.added.is_empty()

    def rows(self, differing: DifferingRecords) -> pl.DataFrame:
        """The partition as an import under `differing` leaves it, in clock order and one chunk,
        so that its bytes follow from its rows however the files arrived: the stored rows and
        the added ones, the stored rows of the disputed instants giving way to the file's where
        the file's stand."""
        kept, taken = self.kept, self.added
        if differing is DifferingRecords.TAKE_THE_FILE:
            kept = kept.filter(~self._in_dispute())
            taken = pl.concat([self.differing, self.added])
        return pl.concat([kept, taken]).sort(self.clock, PLACE).drop(PLACE).rechunk()

    def stored_records_disputed(self) -> int:
        """How many stored records lie at the disputed instants, which give way where the
        file's stand."""
        return self.kept.filter(self._in_dispute()).height

    def added_days(self) -> pl.DataFrame:
        """The records added per trade date, with the columns of `DAY_COUNTS`."""
        return _per_trade_date(self.added, self.partition)

    def differing_days(self) -> pl.DataFrame:
        """The file's records at disputed instants per trade date, as `added_days`."""
        return _per_trade_date(self.differing, self.partition)

    def held_days(self) -> list[date]:
        """The trade dates the stored partition holds records of."""
        return _per_trade_date(self.kept, self.partition).get_column("trade_date").to_list()

    def _in_dispute(self) -> pl.Expr:
        instants = self.differing.get_column(self.clock).unique()
        return pl.col(self.clock).is_in(instants.implode())


def merged_partition(
    partition: Partition,
    stored: pl.DataFrame | None,
    incoming: pl.DataFrame,
    identity: RecordIdentity,
) -> PartitionMerge:
    """The rows `incoming`, a file's of `partition` in clock order, read against `stored`, the
    rows the store holds of it, none where it holds no such partition (module docstring)."""
    clock = identity.clock
    new = _placed(incoming, clock)
    if identity.numbered_by_place:
        new = new.with_columns(sequence=pl.col(PLACE).cast(pl.UInt32))
    if stored is None or stored.is_empty():
        return PartitionMerge(partition, clock, new.clear(), new, 0, new.clear())
    kept = _placed(stored, clock)
    _require_the_instruments_held(partition, kept, new)
    places = [clock, PLACE]
    shared = new.join(kept.select(places), on=places, how="semi", maintain_order="left")
    if shared.is_empty():
        _require_no_overlap(partition, kept, new, clock)
    same = [PLACE, *identity.compared_columns(incoming.columns)]
    unequal = shared.join(kept, on=same, how="anti", nulls_equal=True, maintain_order="left")
    in_dispute = pl.col(clock).is_in(unequal.get_column(clock).unique().implode())
    added = new.join(kept.select(places), on=places, how="anti", maintain_order="left")
    added = added.filter(~in_dispute)
    if identity.numbered_by_place:
        added = _numbered_on(added, kept, clock)
    held = shared.filter(~in_dispute).height
    return PartitionMerge(partition, clock, kept, added, held, new.filter(in_dispute))


def _placed(rows: pl.DataFrame, clock: str) -> pl.DataFrame:
    return rows.with_columns(pl.int_range(pl.len()).over(clock).alias(PLACE))


def _numbered_on(added: pl.DataFrame, kept: pl.DataFrame, clock: str) -> pl.DataFrame:
    """The added prints, those of an instant the store holds numbered on from the stored
    prints' last number, where their place alone would count from the stored prints' count."""
    last = pl.col("sequence").cast(pl.Int64).max()
    carried = kept.group_by(clock).agg(_carried=last + 1 - pl.len())
    numbered = added.join(carried, on=clock, how="left", maintain_order="left")
    sequence = pl.col(PLACE) + pl.col("_carried").fill_null(0)
    return numbered.with_columns(sequence=sequence.cast(pl.UInt32)).drop("_carried")


def _require_the_instruments_held(
    partition: Partition, kept: pl.DataFrame, new: pl.DataFrame
) -> None:
    held = set(kept.get_column("instrument_id").unique().to_list())
    others = sorted(set(new.get_column("instrument_id").unique().to_list()) - held)
    if others:
        raise ValueError(
            f"Expected the records of {partition.relative_path()} under the instrument_id it "
            f"holds, {', '.join(str(each) for each in sorted(held))}, got "
            f"{', '.join(str(each) for each in others)} from this file: one contract under two "
            "ids loads as two series, so the file is refused, and nothing was written. Name its "
            "instruments as the files before it did."
        )


def _require_no_overlap(
    partition: Partition, kept: pl.DataFrame, new: pl.DataFrame, clock: str
) -> None:
    """Refuse a file that shares no record with the stored partition though both hold records
    in the stretch of time the two have in common."""
    instant = pl.col(clock)
    stored_first, stored_last = kept.select(first=instant.min(), last=instant.max()).row(0)
    file_first, file_last = new.select(first=instant.min(), last=instant.max()).row(0)
    first, last = max(stored_first, file_first), min(stored_last, file_last)
    both_reach = instant.is_between(first, last)
    if first > last or kept.filter(both_reach).is_empty() or new.filter(both_reach).is_empty():
        return
    raise ValueError(
        f"Expected the file to share records with {partition.relative_path()} where the two "
        f"overlap in time, from {utc_text(first)} to {utc_text(last)}, got none in common: the "
        "file reads its times under another time zone or stamping rule than the files before "
        "it, or holds another source's records, and merging it would store them twice. Nothing "
        "was written."
    )


def _per_trade_date(rows: pl.DataFrame, partition: Partition) -> pl.DataFrame:
    """The records of `rows` per trade date, with the columns of `DAY_COUNTS`: by a bar's own
    trade date, by the partition's key for records kept by trade date, and none for records
    that carry no trade date, as definitions do."""
    if "trade_date" in rows.columns:
        return rows.group_by("trade_date").agg(records=pl.len()).cast(DAY_COUNTS)
    if isinstance(partition.key, date) and not rows.is_empty():
        counted = {"trade_date": [partition.key], "records": [rows.height]}
        return pl.DataFrame(counted, schema=DAY_COUNTS)
    return pl.DataFrame(schema=DAY_COUNTS)
