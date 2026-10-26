"""The engine's market-data cache (`02` §1.6, D-56): a root's data from one provider, each
contract-month as uncompressed Arrow IPC files that the engine maps into memory, under
`<FEFAT_HOME>/cache/engine/<provider>/<root>/<contract>/<YYYY-MM>/`, written by `fefat_engine`
and rebuilt when the store partitions it was built from change:

    paths = resolve_paths(os.environ)
    build = build_engine_cache(Store(paths.data_dir), paths.cache_dir, "MES", 2025)
    print(build.summary())
    for month in engine_cache_status(paths.cache_dir):
        print(month.summary())

A month holds a file per level, named by the fidelity type (`tbbo`, `trades`, `1s`, `1m`, or an
import's coarser bars), a file per descent from a timeframe's bars to a finer level, and an
`index.json` with each trade date's levels, the records cut after its last bar, the levels left
out of it, and the partitions the month was built from, by path and SHA-256: the hashes a
snapshot pins (ADR-0019). The builder reads the store through snapshots, one partition at a
time, and records each partition's digest beside it, so that a later build reads only the
partitions that changed.
"""

import shutil
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated

import polars as pl
from fefat_engine import write_cache_month
from pydantic import BeforeValidator, Field

from fefat.market.dataset_choice import provider_datasets
from fefat.market.fidelity import Fidelity, TickFidelity
from fefat.market.layout import Dataset, Partition, PartitionRequest, YearMonth
from fefat.market.schema import BarSchemaName, FrozenModel, SchemaKind, Timeframe
from fefat.market.snapshot import FileDigest, Sha256, Snapshot
from fefat.market.store import Store
from fefat.market.store_files import parsed_json

ENGINE_CACHE_FOLDER_NAME = "engine"
"""The engine cache's folder in `FEFAT_HOME/cache` (`fefat.config.FefatPaths.cache_dir`)."""
INDEX_FILE_NAME = "index.json"
LAYOUT_VERSION = 1
"""The layout `fefat-data` writes; a month of another layout is rebuilt."""
_PARTIAL_SUFFIX = ".partial"

type Level = TickFidelity | Timeframe

_TRADE_COLUMNS = {"ts_recv": "ts_recv", "price": "price", "size": "size"}
_TBBO_COLUMNS = {
    **_TRADE_COLUMNS,
    "bid_px_00": "bid",
    "ask_px_00": "ask",
    "bid_sz_00": "bid_size",
    "ask_sz_00": "ask_size",
}
_BAR_COLUMNS = {
    name: name for name in ("ts_open", "ts_close", "open", "high", "low", "close", "volume")
}
"""The store's columns of each level, and their names in the cache, where each is int64."""


def _month_of(value: object) -> object:
    return YearMonth.parse(value) if isinstance(value, str) else value


Month = Annotated[YearMonth, BeforeValidator(_month_of)]
"""A month as the index writes it, `2026-03`."""


class CachedSource(FrozenModel):
    """A store partition a month was built from: its path in the store and its SHA-256."""

    path: str
    sha256: Sha256


class CachedTradeDate(FrozenModel):
    """A trade date of a month: its levels, finest first, the records cut at and after the
    close of the last bar that holds them, and the levels left out, each with its reason."""

    trade_date: date
    levels: tuple[Fidelity, ...]
    cut: dict[Fidelity, int]
    left_out: dict[Fidelity, str]


class CachedFile(FrozenModel):
    """A file of a month: the rows of its batches and its size."""

    rows: int = Field(ge=0)
    bytes: int = Field(ge=0)


class CacheMonthIndex(FrozenModel):
    """A cached contract-month's `index.json`, as `fefat-data` writes it."""

    layout_version: int
    contract: str
    month: Month
    sources: tuple[CachedSource, ...]
    trade_dates: tuple[CachedTradeDate, ...]
    files: dict[str, CachedFile]

    def size_bytes(self) -> int:
        return sum(file.bytes for file in self.files.values())

    def levels_summary(self) -> str:
        """Each level with the trade dates that hold it, coarsest first: `1m 21 days, ...`."""
        days = Counter(level for trade_date in self.trade_dates for level in trade_date.levels)
        ordered = sorted(days.items(), key=lambda level_days: _coarsest_first(level_days[0]))
        return ", ".join(f"{level} {_counted(count, 'day')}" for level, count in ordered)

    def notes(self) -> list[str]:
        """The records cut from each trade date and the levels left out of it."""
        notes: list[str] = []
        for day in self.trade_dates:
            if day.cut:
                cut = ", ".join(
                    f"{_counted(count, 'record')} of {level}" for level, count in day.cut.items()
                )
                notes.append(f"{day.trade_date}: cut {cut} after the last bar that holds them")
            notes += [
                f"{day.trade_date}: left out {level}, since {reason}"
                for level, reason in day.left_out.items()
            ]
        return notes


def _coarsest_first(level: TickFidelity | Timeframe) -> tuple[int, int]:
    if isinstance(level, Timeframe):
        return (0, -level.nominal_seconds())
    return (1, 0 if level is TickFidelity.TRADES else 1)


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _size(size_bytes: int) -> str:
    if size_bytes < 1_000_000:
        return f"{size_bytes / 1_000:.0f} kB"
    return f"{size_bytes / 1_000_000:.1f} MB"


def read_cache_month_index(month_folder: Path) -> CacheMonthIndex | None:
    """The index of a cached month, or None while the folder holds none."""
    path = month_folder / INDEX_FILE_NAME
    if not path.is_file():
        return None
    return parsed_json(CacheMonthIndex, path.read_bytes(), str(path))


class MonthOutcome(StrEnum):
    """What a build did with a contract-month."""

    BUILT = "built"
    UP_TO_DATE = "up to date"


class CachedMonthBuild(FrozenModel):
    """A contract-month a build wrote, or found up to date."""

    outcome: MonthOutcome
    index: CacheMonthIndex

    def summary(self) -> str:
        index = self.index
        size = _size(index.size_bytes())
        return f"{index.contract} {index.month}: {self.outcome}, {index.levels_summary()}, {size}"


class EngineCacheBuild(FrozenModel):
    """What `build_engine_cache` did for a root's year."""

    provider: str
    root: str
    year: int
    months: tuple[CachedMonthBuild, ...]

    def summary(self) -> str:
        """A line for the year, one per contract-month, and one per cut or left-out level."""
        heading = f"{self.root} ({self.provider}) {self.year}"
        if not self.months:
            return f"{heading}: no trade dates in the store, so nothing to cache."
        built = sum(month.outcome is MonthOutcome.BUILT for month in self.months)
        up_to_date = len(self.months) - built
        trade_dates = sum(len(month.index.trade_dates) for month in self.months)
        size = _size(sum(month.index.size_bytes() for month in self.months))
        lines = [
            f"{heading}: {_counted(built, 'contract-month')} built, {up_to_date} up to date, "
            f"{_counted(trade_dates, 'trade date')}, {size}."
        ]
        for month in self.months:
            lines.append(f"  {month.summary()}")
            lines += [f"    {note}" for note in month.index.notes()]
        return "\n".join(lines)


@dataclass(frozen=True)
class _PinnedPartition:
    """A partition a snapshot pinned, with the level its records are."""

    level: Level
    snapshot: Snapshot
    digest: FileDigest
    partition: Partition


def build_engine_cache(
    store: Store, cache_folder: Path, root: str, year: int, provider: str | None = None
) -> EngineCacheBuild:
    """Build the engine cache of `root`'s trade dates of `year` in `cache_folder`
    (`FEFAT_HOME/cache`) from one provider's datasets of trades, TBBO, and bars, chosen as
    `load` chooses them (`fefat.market.dataset_choice`): each contract-month without a cache, or
    whose partitions changed since it was cached, is written again."""
    datasets = tuple(provider_datasets(store, root, provider, origin=None).values())
    chosen = datasets[0].provider
    levels = {dataset: _level_of(dataset) for dataset in datasets}
    listed = {
        dataset: tuple(file.partition for file in store.list_partitions(dataset))
        for dataset in datasets
    }
    root_folder = cache_folder / ENGINE_CACHE_FOLDER_NAME / chosen / root
    months = (YearMonth(year=year, month=number) for number in range(1, 13))
    built = tuple(
        month_build
        for month in months
        for month_build in _build_month(store, root_folder, levels, listed, month)
    )
    return EngineCacheBuild(provider=chosen, root=root, year=year, months=built)


def _level_of(dataset: Dataset) -> Level:
    schema_name = dataset.schema_name
    if isinstance(schema_name, BarSchemaName):
        return schema_name.timeframe
    if schema_name.kind is SchemaKind.TBBO:
        return TickFidelity.TBBO
    if schema_name.kind is SchemaKind.TRADES:
        return TickFidelity.TRADES
    raise ValueError(
        f"Expected a dataset of trades, TBBO, or bars, got {dataset.relative_folder()}."
    )


def _build_month(
    store: Store,
    root_folder: Path,
    levels: dict[Dataset, Level],
    listed: dict[Dataset, tuple[Partition, ...]],
    month: YearMonth,
) -> list[CachedMonthBuild]:
    start = date(month.year, month.month, 1)
    end = date(month.year + month.month // 12, month.month % 12 + 1, 1) - timedelta(days=1)
    by_contract: defaultdict[str, list[_PinnedPartition]] = defaultdict(list)
    for dataset, level in levels.items():
        request = PartitionRequest(dataset=dataset, start=start, end=end)
        if not any(request.selects(partition) for partition in listed[dataset]):
            continue
        snapshot = store.record_digests(request)
        for digest in snapshot.partitions:
            partition = Partition.from_relative_path(PurePosixPath(digest.path))
            pinned = _PinnedPartition(level, snapshot, digest, partition)
            by_contract[partition.contract].append(pinned)
    built = (
        _build_contract_month(store, root_folder / contract, month, pinned)
        for contract, pinned in sorted(by_contract.items())
    )
    return [month_build for month_build in built if month_build is not None]


def _build_contract_month(
    store: Store, contract_folder: Path, month: YearMonth, pinned: list[_PinnedPartition]
) -> CachedMonthBuild | None:
    """The contract-month as cached, written again unless its index names the same partitions;
    None for a month whose partitions hold no record of it."""
    month_folder = contract_folder / str(month)
    sources = sorted((item.digest.path, item.digest.sha256) for item in pinned)
    cached = read_cache_month_index(month_folder)
    if cached is not None and _is_built_from(cached, sources):
        return CachedMonthBuild(outcome=MonthOutcome.UP_TO_DATE, index=cached)
    frames = _MonthFrames.of(store, pinned)
    _remove_stale(month_folder)
    if not frames.trade_dates:
        return None
    trade_dates = frames.by_trade_date(store)
    write_cache_month(contract_folder, contract_folder.name, str(month), sources, trade_dates)
    index = read_cache_month_index(month_folder)
    if index is None:
        raise ValueError(f"Expected the index of the cache just written in {month_folder}.")
    return CachedMonthBuild(outcome=MonthOutcome.BUILT, index=index)


def _is_built_from(index: CacheMonthIndex, sources: list[tuple[str, str]]) -> bool:
    built_from = [(source.path, source.sha256) for source in index.sources]
    return index.layout_version == LAYOUT_VERSION and built_from == sources


def _remove_stale(month_folder: Path) -> None:
    """Remove a month's stale cache and any build of it left part way."""
    partial = month_folder.with_name(month_folder.name + _PARTIAL_SUFFIX)
    for folder in (month_folder, partial):
        if not folder.exists():
            continue
        try:
            shutil.rmtree(folder)
        except OSError as error:
            raise ValueError(
                f"Expected to remove the stale engine cache {folder}, got: {error}; close "
                "the programs that read it and build again."
            ) from error


@dataclass(frozen=True)
class _MonthFrames:
    """A contract-month's records by trade date: the bars of month and contract partitions read
    once and split by their trade date, and each trade-date partition read when its date comes,
    so that the builder holds one day of ticks at a time."""

    split: dict[Level, dict[date, pl.DataFrame]]
    daily: dict[tuple[date, Level], _PinnedPartition]
    trade_dates: tuple[date, ...]

    @classmethod
    def of(cls, store: Store, pinned: list[_PinnedPartition]) -> "_MonthFrames":
        split: dict[Level, dict[date, pl.DataFrame]] = {}
        daily: dict[tuple[date, Level], _PinnedPartition] = {}
        for item in pinned:
            if isinstance(item.partition.key, date):
                daily[(item.partition.key, item.level)] = item
                continue
            frame = store.read_pinned_partition(item.snapshot, item.digest)
            parts = frame.partition_by("trade_date", as_dict=True, maintain_order=True)
            split[item.level] = {key[0]: part for key, part in parts.items()}
        dates = {day for by_date in split.values() for day in by_date}
        dates |= {day for day, _ in daily}
        return cls(split=split, daily=daily, trade_dates=tuple(sorted(dates)))

    def by_trade_date(self, store: Store) -> Iterator[tuple[str, list[tuple[str, pl.DataFrame]]]]:
        """Each trade date with a frame per level in the cache's columns, read as it comes."""
        for trade_date in self.trade_dates:
            frames = [
                (level, by_date[trade_date])
                for level, by_date in self.split.items()
                if trade_date in by_date
            ]
            frames += [
                (level, store.read_pinned_partition(item.snapshot, item.digest))
                for (day, level), item in self.daily.items()
                if day == trade_date
            ]
            levels = [
                (str(level), _cache_columns(level, frame))
                for level, frame in frames
                if not frame.is_empty()
            ]
            if levels:
                yield trade_date.isoformat(), levels


def _cache_columns(level: Level, frame: pl.DataFrame) -> pl.DataFrame:
    """A level's records in the cache's columns, each int64, in the store's order."""
    if isinstance(level, Timeframe):
        columns = _BAR_COLUMNS
    elif level is TickFidelity.TBBO:
        columns = _TBBO_COLUMNS
    else:
        columns = _TRADE_COLUMNS
    return frame.select(
        pl.col(stored).cast(pl.Int64).alias(cached) for stored, cached in columns.items()
    )


class CachedMonth(FrozenModel):
    """A contract-month in the engine cache, with its provider and root."""

    provider: str
    root: str
    index: CacheMonthIndex

    def summary(self) -> str:
        """`<provider> <root> <contract> <month>: <level> <days>, ..., <size>`."""
        index = self.index
        size = _size(index.size_bytes())
        place = f"{self.provider} {self.root} {index.contract} {index.month}"
        return f"{place}: {index.levels_summary()}, {size}"


def engine_cache_status(cache_folder: Path, root: str | None = None) -> tuple[CachedMonth, ...]:
    """Each contract-month in the engine cache of `cache_folder`, or only `root`'s, with the
    levels of its trade dates, sorted by provider, root, contract, and month."""
    engine_folder = cache_folder / ENGINE_CACHE_FOLDER_NAME
    cached: list[CachedMonth] = []
    for path in sorted(engine_folder.glob(f"*/*/*/*/{INDEX_FILE_NAME}")):
        month_folder = path.parent
        root_folder = month_folder.parent.parent
        if month_folder.name.endswith(_PARTIAL_SUFFIX) or root not in (None, root_folder.name):
            continue
        index = parsed_json(CacheMonthIndex, path.read_bytes(), str(path))
        provider = root_folder.parent.name
        cached.append(CachedMonth(provider=provider, root=root_folder.name, index=index))
    return tuple(cached)
