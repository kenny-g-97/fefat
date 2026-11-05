"""The feature cache's partitions and what keys them (step 3.3, `fefat.features.cache`, D-56,
D-71). A partition is one of the store's: the trade dates of a month whose bars are built from
bars the store keeps by month or by contract, named `2026-03`, the dates inside it that data kept
by trade date builds left out, and each of those dates, named `2026-03-05`. A partition's key is
the SHA-256 of what its frame is computed from (`PartitionKeys`), and the SDK's code that shapes
bars and values is part of every key (`runtime_key`).
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import polars as pl

from fefat.features.cache_index import partition_dates
from fefat.features.runtime import FeatureGraph
from fefat.market.api import SeriesSource
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import signal_bar_levels, source_dataset
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, Partitioning, PartitionRequest, YearMonth, partitioning
from fefat.market.schema import Timeframe

Levels = Mapping[date, TickFidelity | Timeframe]
"""Each trade date the store holds, with the level its signal bars are built from."""


@dataclass(frozen=True)
class CachePartition:
    """A partition of the feature cache (module docstring): its name, its first and last day,
    and the trade dates between them that partitions of their own hold."""

    name: str
    first: date
    last: date
    left_out: tuple[date, ...] = ()

    def holds(self) -> pl.Expr:
        """Whether a row's trade date is one of the partition's."""
        days = pl.col("trade_date")
        within = days.is_between(self.first, self.last)
        return within & ~days.is_in(list(self.left_out)) if self.left_out else within

    def holds_day(self, day: date) -> bool:
        """Whether `day` is one of the partition's trade dates."""
        return self.first <= day <= self.last and day not in self.left_out


def held_levels(source: SeriesSource, timeframe: Timeframe, window: tuple[date, date]) -> Levels:
    """Each trade date of the months `window` touches that the source's data holds, with the
    level its bars of `timeframe` are built from, as `load` chooses it (`signal_bar_levels`)."""
    first, last = window
    months = (partition_dates(_month_name(first))[0], partition_dates(_month_name(last))[1])
    counted = source.counted(months)
    return signal_bar_levels(source.store, source.datasets, timeframe, months, counted)


def cache_partitions(
    source: SeriesSource, timeframe: Timeframe, window: tuple[date, date], levels: Levels
) -> tuple[CachePartition, ...]:
    """The partitions that hold the trade dates of `window` from the first to the last date
    the source's data holds (`levels`), in order: none where it holds none of them."""
    if not levels:
        return ()
    held = list(levels)
    first, last = max(window[0], held[0]), min(window[1], held[-1])
    days = source.sessions.between(first, last).get_column("trade_date").to_list()
    by_date = _kept_by_trade_date(source, timeframe, levels)
    found: dict[str, CachePartition] = {}
    for day in days:
        partition = _partition_of(day, by_date)
        found.setdefault(partition.name, partition)
    return tuple(sorted(found.values(), key=lambda partition: (partition.first, partition.name)))


def _kept_by_trade_date(source: SeriesSource, timeframe: Timeframe, levels: Levels) -> set[date]:
    """The trade dates whose bars are built from data the store keeps by trade date."""
    root = source.instrument.root
    by_date: dict[str, bool] = {}
    for level in levels.values():
        if str(level) not in by_date:
            dataset = source_dataset(source.datasets, level, timeframe, root)
            by_date[str(level)] = partitioning(dataset.schema_name) is Partitioning.TRADE_DATE
    return {day for day, level in levels.items() if by_date[str(level)]}


def _partition_of(day: date, by_date: set[date]) -> CachePartition:
    if day in by_date:
        return CachePartition(name=str(day), first=day, last=day)
    name = _month_name(day)
    first, last = partition_dates(name)
    left_out = tuple(sorted(other for other in by_date if first <= other <= last))
    return CachePartition(name=name, first=first, last=last, left_out=left_out)


def _month_name(day: date) -> str:
    return str(YearMonth(year=day.year, month=day.month))


@cache
def runtime_key() -> str:
    """The SHA-256 of the Polars version and the source of the SDK, `fefat`, whose code shapes
    the bars and the values the cache keeps, its market data, features, and the indicators
    features call, so that a changed rule, or a new Polars, computes them again."""
    # shortcut: the key reads the SDK's source, which a build shipping only bytecode lacks;
    # replace it with a version constant when the app is packaged (Phase 14).
    digest = hashlib.sha256(pl.__version__.encode())
    sdk = Path(__file__).parent.parent
    for path in sorted(sdk.rglob("*.py")):
        digest.update(path.relative_to(sdk).as_posix().encode() + b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PartitionKeys:
    """The key of each partition's frames in one computation, each instrument's pins over a
    range of dates taken once (`fefat.features.cache`, module docstring)."""

    def __init__(self, sources: Mapping[str, SeriesSource]) -> None:
        self._sources = sources
        self._ends: dict[Dataset, int] = {}
        self._pins: dict[tuple[str, date, date], tuple[str, ...]] = {}

    def of_bars(self, root: str, timeframe: Timeframe, partition: CachePartition) -> str:
        """The key of the partition's signal bars of `root`, over the trade dates `load` reads
        for them (`SeriesSource.dates_read`)."""
        reads = {root: self._sources[root].dates_read((partition.first, partition.last))}
        return self._key(f"bars {timeframe}", partition, reads)

    def of_values(self, graph: FeatureGraph, identity: str, partition: CachePartition) -> str:
        """The key of the values on the partition of the feature of `graph`, a slot's graph
        (`FeatureGraph.of_slot`), whose features with their parameters `identity` names."""
        reads = self.reads(graph, (partition.first, partition.last))
        return self._key(identity, partition, reads)

    def pins(self, graph: FeatureGraph, dates: tuple[date, date]) -> tuple[str, ...]:
        """What the bars of each instrument the graph reads are read from, to evaluate it on the
        trade dates `dates` spans from its warm-up (`reads`), each instrument's pins as the keys
        of its partitions name them, which a run's request keys (`fefat.backtest.requests`)."""
        reads = self.reads(graph, dates)
        return tuple(line for root in sorted(reads) for line in self._pins_of(root, *reads[root]))

    def reads(self, graph: FeatureGraph, dates: tuple[date, date]) -> dict[str, tuple[date, date]]:
        """The trade dates each instrument's bars are read for, to evaluate the graph on the
        trade dates `dates` spans from its warm-up, as `load` reads them
        (`SeriesSource.dates_read`)."""
        start = graph.lead_in(self._sources[graph.root].sessions, dates[0])
        reads: dict[str, tuple[date, date]] = {}
        for grid in graph.grids():
            source = self._sources[grid.root]
            window = graph.grid_dates(grid, (start, dates[1]), source.sessions)
            first, last = source.dates_read(window)
            known = reads.get(grid.root, (first, last))
            reads[grid.root] = (min(known[0], first), max(known[1], last))
        return reads

    def _key(
        self, identity: str, partition: CachePartition, reads: Mapping[str, tuple[date, date]]
    ) -> str:
        left_out = ",".join(str(day) for day in partition.left_out)
        lines = [runtime_key(), identity, f"partition {partition.name} without {left_out}"]
        for root in sorted(reads):
            first, last = reads[root]
            lines += self._pins_of(root, first, last)
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()

    def _pins_of(self, root: str, first: date, last: date) -> tuple[str, ...]:
        """What `root`'s bars of the trade dates from `first` to `last` are read from: its
        provider, symbol, session table, roll calendar through `last`, and each dataset's
        snapshot with where its data ends."""
        place = (root, first, last)
        if place not in self._pins:
            source = self._sources[root]
            rolls = "none" if source.calendar is None else source.calendar.key_through(last)
            opened = source.sessions.session(first).open
            closed = source.sessions.preceding(last + timedelta(days=1)).close
            folders = sorted(source.datasets.values(), key=_folder)
            self._pins[place] = (
                f"{source.provider} {source.symbol} sessions {source.sessions.key} rolls {rolls}",
                *(self._pin(source, each, (first, last), (opened, closed)) for each in folders),
            )
        return self._pins[place]

    def _pin(
        self,
        source: SeriesSource,
        dataset: Dataset,
        dates: tuple[date, date],
        read: tuple[int, int],
    ) -> str:
        """The dataset's snapshot over `dates`, none where it holds no partition of them, and
        the instant by which its data is in hand, after which a bucket is held back (D-43): every
        dataset's, since a load's grid runs to the end of the data of every dataset that builds
        its bars (`gridded_bars`), taken between `read`, the open of the first session read and
        the close of the last, beyond which an end moves no bucket read, so that a month whose
        data is whole keeps its key as later data comes."""
        opened, closed = read
        end = min(max(self._end_of(source, dataset), opened), closed)
        listing = source.store.list_partitions(dataset)
        request = PartitionRequest(dataset=dataset, start=dates[0], end=dates[1])
        if not any(request.selects(file.partition) for file in listing):
            return f"{_folder(dataset)} none until {end}"
        return f"{source.store.snapshot(request).sha256} until {end}"

    def _end_of(self, source: SeriesSource, dataset: Dataset) -> int:
        """Where the dataset's data ends, 0 without partitions, as `gridded_bars` takes it."""
        if dataset not in self._ends:
            coverage = dataset_coverage(source.store, dataset)
            self._ends[dataset] = 0 if coverage is None else coverage.received_until
        return self._ends[dataset]


def _folder(dataset: Dataset) -> str:
    return dataset.relative_folder().as_posix()
