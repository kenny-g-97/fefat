"""The feature cache (step 3.3, `02-engine-and-data.md` §6, D-56, D-71): `compute` keeps the
values it computes under `FEFAT_HOME/cache/features/` and reads them back while what they were
computed from is unchanged, so that previews and backtests of a feature are quick and a sweep
computes each parameter's values once.

    frame = ff.features.compute({"rsi": rsi(n=14)}, "MES", "5m", "2025-01-01", "2025-12-31")
    ff.features.cache_status()

The cache is split as the store is (`fefat.features.cache_keys`): a month's trade dates whose bars
are built from bars the store keeps by month or by contract, and each trade date whose bars are
built from data it keeps by trade date, so that a new month computes that month alone. A
partition's signal bars are those `load` gives for its dates alone, and each feature's values on
them are computed from as many sessions before the partition as its own warm-up needs
(`FeatureGraph.lead_in`), so that a partition's values depend on the feature and the data alone,
never on the window asked for or on the features computed beside it: a range computed in chunks
equals the range computed at once.

A partition is read back while its key is the one its inputs give now (D-71): the SDK's code that
shapes bars and values, with the Polars version; the feature's content hash with its parameters
and those of the features it reads, each with its timeframe; and, for each instrument read, the
provider, the symbol, the session table's key, the roll calendar's rows through the last date
read, and each of the provider's datasets by its snapshot over the dates read, which pins each
store partition by the SHA-256 its `part.digest.json` keeps (D-56), with where its data ends,
which holds a bucket back (D-43). The bars' key reads the session before the partition, as
`load` reads it. Each folder's `index.json` keeps its partitions' keys, sizes, and last use
(`fefat.features.cache_index`, `fefat.features.cache_folders`).

Where one computation evaluates partitions that follow each other, each is evaluated one
session past its end, and a feature's values there must agree with those the next partition
gives from its own warm-up: exactly for integers and Booleans, and for floats within 1e-9 of the
output's largest magnitude among them (`fefat.features.cache_evaluation`). A feature that
remembers more than its warm-up is refused, rather than cached with edges that differ from a
computation of the whole range. A partition computed alone is not checked; the leak
detector's start-invariance check (step 3.4) is.

A run reads its features' values through the cache too (`cached_slots`), so that a feature
previewed alone and the same feature in a backtest give the same values.
"""

import dataclasses
import os
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import product
from pathlib import Path

import polars as pl

from fefat.config import resolve_paths
from fefat.features.cache_evaluation import (
    Evaluation,
    disagreement,
    evaluated_features,
    first_difference,
)
from fefat.features.cache_folders import CacheFolder, FeatureFolder, bars_folder, feature_folder
from fefat.features.cache_index import (
    FEATURE_CACHE_FOLDER_NAME,
    KEY_METADATA,
    CachedPartition,
    write_cache_index,
)
from fefat.features.cache_keys import (
    CachePartition,
    Levels,
    PartitionKeys,
    cache_partitions,
    held_levels,
)
from fefat.features.evaluation import FeatureSpec
from fefat.features.runtime import FeatureGraph, slot_columns
from fefat.market.api import SeriesSource, parse_trade_date, series_source
from fefat.market.dataset_choice import dataset_warnings, source_dataset
from fefat.market.schema import Timeframe
from fefat.market.store_files import write_atomically

Place = tuple[Path, str]
"""A folder of the cache and the name of one of its partitions."""
LAST_USE_STEP = timedelta(hours=1)
"""How long a partition's last use may age before a computation that reads it writes its
index again: pruning counts days, and a sweep reading one folder many times an hour writes
it once."""


def compute(
    specs: Mapping[str, FeatureSpec],
    instrument: str,
    timeframe: str,
    start: str | date,
    end: str | date,
    *,
    provider: str | None = None,
) -> pl.LazyFrame:
    """`load`'s signal bars of the root `instrument` of `timeframe` on the trade dates from
    `start` to `end` from `provider`, as `load` names it, each with the columns of the features
    of `specs` by slot (`slot_columns`), each feature's values read from the cache while its
    inputs are unchanged and computed there otherwise (module docstring)."""
    first, last = parse_trade_date(start, "start"), parse_trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    graph = FeatureGraph.of(specs, instrument, Timeframe.parse(timeframe))
    window = cached_window(graph, (first, last), provider)
    for warning in window.warnings:
        warnings.warn(warning, UserWarning, stacklevel=2)
    whole = pl.concat([window.bars, window.slots.drop("ts_close")], how="horizontal")
    within = whole.filter(pl.col("trade_date").is_between(first, last))
    if within.is_empty():
        raise ValueError(
            f"Expected bars of {instrument} from {first} to {last} in the store, got none."
        )
    return within.lazy()


@dataclass(frozen=True)
class CachedSlots:
    """A graph's slots' columns by `ts_close` on the cached partitions holding a window, the
    first trade date their values were computed from, from which a run's snapshots pin it, None
    for a graph without slots, which reads nothing, and what `load` warns of the datasets they
    were computed from, which a run's record keeps."""

    values: pl.DataFrame
    first_read: date | None
    warnings: tuple[str, ...]


def cached_slots(
    graph: FeatureGraph,
    dates: tuple[date, date],
    provider: str | None = None,
    contract: str | None = None,
) -> CachedSlots:
    """The columns of the graph's slots on the partitions holding the trade dates `dates`
    spans, of the graph's root from `provider` or of the one `contract` a run trades, read from
    the cache or computed there; a graph without slots reads nothing."""
    if not graph.slots:
        return CachedSlots(pl.DataFrame(schema={"ts_close": pl.Int64}), None, ())
    window = cached_window(graph, dates, provider, contract)
    return CachedSlots(window.slots, window.first_read, window.warnings)


@dataclass(frozen=True)
class CachedWindow:
    """The cached partitions that hold a window: their signal bars, sorted as `load` sorts them,
    the slots' columns on them by `ts_close`, the first trade date their values were computed
    from, and what `load` warns of the datasets the window's bars come from."""

    bars: pl.DataFrame
    slots: pl.DataFrame
    first_read: date
    warnings: tuple[str, ...]


def cached_window(
    graph: FeatureGraph,
    dates: tuple[date, date],
    provider: str | None = None,
    contract: str | None = None,
) -> CachedWindow:
    """The partitions holding the trade dates `dates` spans, of the graph's root, or of the one
    `contract`, from `provider`, each read from the cache while its key is unchanged and computed
    and kept there otherwise (module docstring); a window without bars is refused, as `load`
    refuses one."""
    signal = series_source(graph.root if contract is None else contract, provider=provider)
    others = sorted({grid.root for grid in graph.grids()} - {graph.root})
    sources = {graph.root: signal, **{root: series_source(root) for root in others}}
    levels = held_levels(signal, graph.timeframe, dates)
    partitions = cache_partitions(signal, graph.timeframe, dates, levels)
    if not partitions:
        first, last = dates
        raise ValueError(
            f"Expected bars of {signal.symbol} from {first} to {last} in the store, got none."
        )
    warned = [
        *_warnings(signal, graph.timeframe, dates, levels),
        *_inputs_warnings(graph, sources, dates),
    ]
    cache_dir = resolve_paths(os.environ).cache_dir
    folder = cache_dir / FEATURE_CACHE_FOLDER_NAME / signal.provider / signal.symbol
    window = _Computation(graph, sources, partitions, folder / str(graph.timeframe)).window()
    return dataclasses.replace(window, warnings=tuple(dict.fromkeys(warned)))


def _inputs_warnings(
    graph: FeatureGraph, sources: Mapping[str, SeriesSource], dates: tuple[date, date]
) -> list[str]:
    """What `load` warns of the datasets of each other instrument the graph reads, over the
    trade dates it reads them for (`FeatureGraph.grid_dates`); an instrument without bars
    there is refused, as `load` refused it when a window read it whole (step 3.2)."""
    warned: list[str] = []
    for grid in graph.grids():
        if grid.root == graph.root:
            continue
        source = sources[grid.root]
        first, last = graph.grid_dates(grid, dates, source.sessions)
        levels = held_levels(source, grid.timeframe, (first, last))
        if not any(first <= day <= last for day in levels):
            raise ValueError(
                f"Expected bars of {grid.root} from {first} to {last} in the store, got none."
            )
        warned += _warnings(source, grid.timeframe, (first, last), levels)
    return warned


def _warnings(
    source: SeriesSource, timeframe: Timeframe, dates: tuple[date, date], levels: Levels
) -> tuple[str, ...]:
    """What `load` warns of the datasets that build the bars of the trade dates `dates` spans."""
    first, last = dates
    root = source.instrument.root
    held = {str(level): level for day, level in levels.items() if first <= day <= last}
    used = dict.fromkeys(
        source_dataset(source.datasets, level, timeframe, root) for level in held.values()
    )
    return tuple(
        warning for dataset in used for warning in dataset_warnings(dataset, source.series)
    )


class _Computation:
    """One computation of a window's partitions through the cache (module docstring)."""

    def __init__(
        self,
        graph: FeatureGraph,
        sources: Mapping[str, SeriesSource],
        partitions: Sequence[CachePartition],
        folder: Path,
    ) -> None:
        self._graph = graph
        self._sources = sources
        self._signal = sources[graph.root]
        self._partitions = tuple(partitions)
        self._keys = PartitionKeys(sources)
        self._bars = bars_folder(folder, self._signal, graph.timeframe)
        self._slots = {
            slot: feature_folder(folder, graph, slot, self._signal) for slot in graph.slots
        }
        self._features = tuple({each.path: each for each in self._slots.values()}.values())

    def window(self) -> CachedWindow:
        folders = (self._bars, *self._features)
        keys: dict[Place, str] = {}
        frames: dict[Place, pl.DataFrame | None] = {}
        for folder in folders:
            for partition in self._partitions:
                place = (folder.path, partition.name)
                keys[place] = self._key(folder, partition)
                frames[place] = folder.cached(partition, keys[place])
        missing = [
            partition
            for partition in self._partitions
            if any(frames[(folder.path, partition.name)] is None for folder in folders)
        ]
        evaluations = self._evaluations(missing, frames)
        computed = {(path, name) for name, done in evaluations.items() for path in done.frames}
        for name, done in evaluations.items():
            frames.update({(path, name): frame for path, frame in done.frames.items()})
        held = {place: _present(frame, place) for place, frame in frames.items()}
        self._check(evaluations, held)
        self._write(folders, keys, held, computed)
        return self._assembled(held)

    def _key(self, folder: CacheFolder, partition: CachePartition) -> str:
        if isinstance(folder, FeatureFolder):
            return self._keys.of_values(folder.graph, folder.identity, partition)
        return self._keys.of_bars(self._graph.root, self._graph.timeframe, partition)

    def _evaluations(
        self, missing: Sequence[CachePartition], frames: Mapping[Place, pl.DataFrame | None]
    ) -> dict[str, Evaluation]:
        """Each partition lacking a frame evaluated, past its end where the next lacks one too;
        `load`'s warnings come once from `compute`, not once a partition."""
        evaluations = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for partition in missing:
                evaluations[partition.name] = self._evaluated(partition, missing, frames)
        return evaluations

    def _evaluated(
        self,
        partition: CachePartition,
        missing: Sequence[CachePartition],
        frames: Mapping[Place, pl.DataFrame | None],
    ) -> Evaluation:
        bars = frames[(self._bars.path, partition.name)]
        computed: dict[Path, pl.DataFrame] = {}
        if bars is None:
            dates = (partition.first, partition.last)
            bars = self._signal.signal_bars(self._graph.timeframe, dates).filter(partition.holds())
            computed[self._bars.path] = bars
        lacking = [
            folder for folder in self._features if frames[(folder.path, partition.name)] is None
        ]
        end = self._end_of(partition, missing)
        done = evaluated_features(lacking, self._sources, partition, bars, end)
        return dataclasses.replace(done, frames={**computed, **done.frames})

    def _end_of(self, partition: CachePartition, missing: Sequence[CachePartition]) -> date:
        """The partition's last day, or the next session's where a partition lacking a frame
        too holds it, so that the warm-up check compares the two (module docstring)."""
        following = self._signal.sessions.following(partition.last).trade_date
        if any(other.holds_day(following) for other in missing):
            return following
        return partition.last

    def _check(
        self, evaluations: Mapping[str, Evaluation], frames: Mapping[Place, pl.DataFrame]
    ) -> None:
        """Refuse a feature whose values one partition read past its end differ from those the
        partition holding them gives from its own warm-up (module docstring)."""
        for (name, done), other in product(evaluations.items(), self._partitions):
            if other.name == name or other.name not in evaluations:
                continue
            for folder in self._features:
                self._require_agreement(folder, done, other, frames)

    def _require_agreement(
        self,
        folder: FeatureFolder,
        done: Evaluation,
        other: CachePartition,
        frames: Mapping[Place, pl.DataFrame],
    ) -> None:
        """Refuse the folder's feature where its values one evaluation read on the trade dates
        of `other` differ from those `other` holds."""
        beyond = done.beyond.get(folder.path)
        read = None if beyond is None else beyond.filter(other.holds())
        if read is None or read.is_empty():
            return
        held = frames[(folder.path, other.name)]
        difference = first_difference(read.drop("trade_date"), held, folder.outputs())
        if difference is not None:
            starts = (done.starts[folder.path], self._start_of(folder, other))
            raise ValueError(disagreement(folder, starts, difference))

    def _start_of(self, folder: FeatureFolder, partition: CachePartition) -> date:
        """The trade date the folder's feature is read from for the partition."""
        return folder.graph.lead_in(self._signal.sessions, partition.first)

    def _write(
        self,
        folders: Iterable[CacheFolder],
        keys: Mapping[Place, str],
        frames: Mapping[Place, pl.DataFrame],
        computed: set[Place],
    ) -> None:
        """Write each frame computed, then the index of each folder that gained a partition,
        or whose partitions read here were last used more than `LAST_USE_STEP` ago, so that
        a computation read back within the hour writes nothing."""
        now = datetime.now(UTC)
        for folder in folders:
            partitions = dict(folder.index.partitions)
            for partition in self._partitions:
                place = (folder.path, partition.name)
                held = partitions.get(partition.name)
                if place in computed or held is None or now - held.last_used >= LAST_USE_STEP:
                    partitions[partition.name] = _kept(
                        place, frames[place], keys[place], now, place in computed
                    )
            if partitions != folder.index.partitions:
                write_cache_index(folder.path, folder.index.with_partitions(partitions))

    def _assembled(self, frames: Mapping[Place, pl.DataFrame]) -> CachedWindow:
        order = ("ts_open",) if self._signal.calendar is not None else ("contract", "ts_open")
        bars_of = [frames[(self._bars.path, partition.name)] for partition in self._partitions]
        bars = pl.concat(bars_of).sort(*order)
        slots = bars.select("ts_close")
        for slot, folder in self._slots.items():
            values = pl.concat(frames[(folder.path, each.name)] for each in self._partitions)
            columns = slot_columns(slot, self._graph.slots[slot].spec)
            slots = slots.join(
                values.rename(columns), on="ts_close", how="left", maintain_order="left"
            )
        first = self._partitions[0]
        starts = [self._start_of(folder, first) for folder in self._features]
        return CachedWindow(bars, slots, min(starts, default=first.first), ())


def _present(frame: pl.DataFrame | None, place: Place) -> pl.DataFrame:
    if frame is None:
        raise ValueError(f"Expected the frame of {place[1]} in {place[0]}, got none.")
    return frame


def _kept(
    place: Place, frame: pl.DataFrame, key: str, now: datetime, computed: bool
) -> CachedPartition:
    """The partition's entry in its folder's index, its frame written where it was computed,
    with its key in the file's own metadata (`CacheFolder.cached`)."""
    folder, name = place
    file = folder / f"{name}.parquet"
    if computed:
        write_atomically(
            file, lambda temporary: frame.write_parquet(temporary, metadata={KEY_METADATA: key})
        )
    size = file.stat().st_size
    return CachedPartition(key=key, rows=frame.height, size_bytes=size, last_used=now)
