"""Records a file holds that are the stored ones at another offset (step 5.16, ADR-0024). A file
read under the wrong time zone or bar stamping whose timing the calendar check cannot test, as
records of regular hours only, thin ones, or a calendar without breaks give, lands on the stored
instants and reads as differing, which an import told that the file's records stand takes, or
beside them as new, which a merge adds by default. Either way a merge would keep two timings in
one dataset, whichever side is off, so the file is refused whatever the import is told.

`offset_evidence` takes of each partition's merge the file's records the store does not hold,
those it would add and those that differ, within reach of the stored records of the partition
and of its contract's stored partitions beside it (`PartitionMerge.neighbours`): a sample of at
most `OFFSET_SAMPLE`, every so many, so that a file gives one sample. At each offset a misread
file shows (`misread_offsets`) it counts the records beside which the store holds one at their
instant less the offset and their place in their instant, the comparable ones, and those whose
stored record there has their values in the columns every import fills, the matching ones.
`require_no_offset_from_the_store` refuses a dataset where, over the file's partitions, at one
offset at least `MATCHING_AT_LEAST` records match and they are at least half of those comparable
there. The plan measured the builder's store: months of it moved an hour or a bar match at that
offset in every comparable record, while 988 correct files built from its months, a month
carried on, a session filled, every second or third bar filled, match at most 3.5 % at any of 314
offsets.
"""

from collections.abc import Iterable

import polars as pl

from fefat.market.calendar import counted
from fefat.market.calendar_offset import duration_text
from fefat.market.importers.partition_merge import PLACE, PartitionMerge, deleted_and_imported_again
from fefat.market.layout import Dataset
from fefat.market.schema import BarSchemaName, SchemaKind, holds_daily_bars

OFFSET_SAMPLE = 2_000
"""At most this many of a partition's records the store does not hold are compared."""
MATCHING_AT_LEAST = 10
"""How many records must match at one offset for it to refuse a file: one bar the store took
before it was complete, the routine reason to take a file, is never ten, while a thin month of the
builder's read an hour late held a hundred."""
EVIDENCE = pl.Schema(
    {"offset": pl.Int64, "trade_date": pl.Date, "comparable": pl.Int64, "matching": pl.Int64}
)
"""`offset_evidence`'s columns: per offset and trade date of the file's records, how many of the
sample were comparable and how many matched."""
_HALF_HOUR = 30 * 60 * 1_000_000_000
_ZONES_APART = 52
"""The half hours two time zones lie apart at most, from UTC-12 to UTC+14."""
_BAR_VALUES = ("instrument_id", "open", "high", "low", "close", "volume")
_PRINT_VALUES = ("instrument_id", "price", "size", "side")


def misread_offsets(dataset: Dataset) -> tuple[int, ...]:
    """The offsets, in nanoseconds, at which a misread file's records can be the stored ones:
    every half hour up to 26 hours late or early, the most two time zones lie apart, for prints
    and for bars shorter than a day, and for those bars one bar either way too, alone or on top of
    the half hours, as a profile with the bar stamping wrong, the time zone wrong, or both gives;
    none for daily bars, dated by the date they name, nor for other records, such as funding
    rates, which repeat as a matter of course."""
    schema_name = dataset.schema_name
    if holds_daily_bars(schema_name):
        return ()
    if isinstance(schema_name, BarSchemaName):
        width = schema_name.timeframe.nominal_nanoseconds()
        bars = (-width, 0, width)
    elif schema_name.kind in (SchemaKind.TRADES, SchemaKind.TBBO):
        bars = (0,)
    else:
        return ()
    zones = range(-_ZONES_APART, _ZONES_APART + 1)
    return tuple(sorted({zone * _HALF_HOUR + bar for zone in zones for bar in bars} - {0}))


def offset_evidence(merge: PartitionMerge) -> pl.DataFrame:
    """Of a sample of the merge's records the store does not hold, within reach of the stored
    ones, those comparable and those matching per offset and trade date (module docstring), with
    the columns of `EVIDENCE`; none where the schema has no offsets or nothing is in reach."""
    offsets = misread_offsets(merge.partition.dataset)
    if not offsets:
        return pl.DataFrame(schema=EVIDENCE)
    candidates = _within_reach(merge, max(abs(offset) for offset in offsets))
    if candidates.is_empty():
        return pl.DataFrame(schema=EVIDENCE)
    clock, values = merge.clock, _compared_values(merge.partition.dataset)
    sample = candidates.gather_every(candidates.height // OFFSET_SAMPLE + 1)
    moved = (
        sample.select(clock, PLACE, *values, trade_date=_trade_date(merge))
        .join(pl.DataFrame({"offset": offsets}, schema={"offset": pl.Int64}), how="cross")
        .with_columns(pl.col(clock) - pl.col("offset"))
    )
    stored = _stored_at(merge, moved.get_column(clock).unique(), values)
    places = [clock, PLACE]
    comparable = moved.join(stored.select(places), on=places, how="semi")
    matching = comparable.join(stored, on=[*places, *values], how="semi", nulls_equal=True)
    keys = ["offset", "trade_date"]
    return (
        comparable.group_by(keys)
        .agg(comparable=pl.len())
        .join(matching.group_by(keys).agg(matching=pl.len()), on=keys, how="left")
        .with_columns(pl.col("matching").fill_null(0))
        .select(EVIDENCE.names())
        .cast(EVIDENCE)
    )


def require_no_offset_from_the_store(dataset: Dataset, evidence: Iterable[pl.DataFrame]) -> None:
    """Refuse, whatever the import is told, a file whose records in `dataset` are the stored ones
    at another offset, `evidence` being `offset_evidence` of each of its partitions there: at one
    offset at least `MATCHING_AT_LEAST` match, and they are at least half of those comparable."""
    found = pl.concat([pl.DataFrame(schema=EVIDENCE), *evidence])
    matching = pl.col("matching")
    refusing = (
        found.group_by("offset")
        .agg(pl.col("comparable").sum(), matching.sum())
        .filter((matching >= MATCHING_AT_LEAST) & (matching * 2 >= pl.col("comparable")))
        .sort(matching, pl.col("offset").abs(), "offset", descending=[True, False, False])
    )
    if refusing.is_empty():
        return
    offset, comparable, matched = refusing.select("offset", "comparable", "matching").row(0)
    dates = found.filter((pl.col("offset") == offset) & (matching > 0))
    dated = dates.get_column("trade_date").unique().sort()
    side = "earlier" if offset > 0 else "later"
    raise ValueError(
        f"Expected the file's records in {dataset.relative_folder()} at times of their own, got "
        f"{matched:,} of the {comparable:,} compared equal to the stored records "
        f"{duration_text(abs(offset))} {side}, on {counted(len(dated), 'trade date')} from "
        f"{dated[0]}: the file, or the data stored before it, was read under another time zone "
        "or bar stamping, and a merge would keep both in one dataset. The file is refused "
        "whatever the import is told, and nothing was written. Compare that trade date with the "
        "platform's chart: where the file is off, read it under the right time zone or bar "
        f"stamping; where the stored data is, {deleted_and_imported_again(dataset)}."
    )


def _compared_values(dataset: Dataset) -> tuple[str, ...]:
    """The columns a misread record keeps the stored one's values in: those every import fills,
    so that a trade count one profile maps and a copy of it does not hides nothing."""
    return _BAR_VALUES if isinstance(dataset.schema_name, BarSchemaName) else _PRINT_VALUES


def _within_reach(merge: PartitionMerge, reach: int) -> pl.DataFrame:
    """The merge's records the store does not hold, those it would add and those that differ,
    within `reach` of the stored records of the partition or of a stored partition beside it."""
    instant = pl.col(merge.clock)
    spans = [(neighbour.first, neighbour.last) for neighbour in merge.neighbours]
    if not merge.kept.is_empty():
        spans.append(merge.kept.select(instant.min(), instant.max().alias("last")).row(0))
    unheld = pl.concat([merge.differing, merge.added])
    if not spans:
        return unheld.clear()
    near = [instant.is_between(first - reach, last + reach) for first, last in spans]
    return unheld.filter(pl.any_horizontal(near))


def _trade_date(merge: PartitionMerge) -> pl.Expr:
    """A record's trade date: a bar's own, a print's its partition's."""
    if "trade_date" in merge.added.columns:
        return pl.col("trade_date")
    return pl.lit(merge.partition.key, dtype=pl.Date)


def _stored_at(merge: PartitionMerge, asked: pl.Series, values: tuple[str, ...]) -> pl.DataFrame:
    """The stored records of the merge's partition and of the stored partitions beside it at the
    instants `asked`, each with its place in its instant, in the columns compared; a neighbour's
    records are read at those instants alone, whole, so that their places are their own."""
    clock = merge.clock
    columns = [clock, PLACE, *values]
    at_asked = pl.col(clock).is_in(asked.implode())
    beside = [
        neighbour.rows.filter(at_asked)
        .with_columns(pl.int_range(pl.len()).over(clock).alias(PLACE))
        .select(columns)
        for neighbour in merge.neighbours
    ]
    return pl.concat([merge.kept.lazy().filter(at_asked).select(columns), *beside]).collect()
