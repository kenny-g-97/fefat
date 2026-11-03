"""The engine's market-data cache (`02` §1.6, D-56): a root's data from one provider, each
contract-month as uncompressed Arrow IPC files that the engine maps into memory, under
`<FEFAT_HOME>/cache/engine/<provider>/<root>/<contract>/<YYYY-MM>/`, written by `fefat_engine`
and rebuilt when the store partitions it was built from change:

    paths = resolve_paths(os.environ)
    build = build_engine_cache(Store(paths.data_dir), paths.cache_dir, "MES", 2025)
    print(build.summary())

A month holds a file per level, named by the fidelity type (`tbbo`, `trades`, `1s`, `1m`, or an
import's coarser bars), a file per descent from a timeframe's bars to a finer level, and an
`index.json` with each trade date's levels, the records cut after its last bar, the levels left
out of it, and the partitions the month was built from, by path and SHA-256: the hashes a
snapshot pins (ADR-0019). The builder reads the store through snapshots, one partition at a
time, and records each partition's digest beside it, so that a later build reads only the
partitions that changed. What a month holds, and the status of the cache, are
`fefat.market.engine_cache_index`.
"""

import shutil
from collections import defaultdict
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import polars as pl
from fefat_engine import write_cache_month

from fefat.market.calendar import counted
from fefat.market.dataset_choice import provider_datasets
from fefat.market.engine_cache_index import (
    ENGINE_CACHE_FOLDER_NAME,
    LAYOUT_VERSION,
    PARTIAL_SUFFIX,
    CacheMonthIndex,
    read_cache_month_index,
    size_text,
)
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, Partition, PartitionRequest, YearMonth
from fefat.market.schema import BarSchemaName, FrozenModel, SchemaKind, Timeframe
from fefat.market.snapshot import FileDigest, Snapshot
from fefat.market.store import Store

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
        size = size_text(index.size_bytes())
        return f"{index.contract} {index.month}: {self.outcome}, {index.levels_summary()}, {size}"


class EngineCacheBuild(FrozenModel):
    """What `build_engine_cache` did for a root's year."""

    provider: str
    root: str
    year: int
    months: tuple[CachedMonthBuild, ...]
    removed: tuple[str, ...]
    refused: tuple[str, ...]

    def summary(self) -> str:
        """A line for the year, one per contract-month, one per cut or left-out level, and
        one per contract-month removed or refused."""
        heading = f"{self.root} ({self.provider}) {self.year}"
        if not (self.months or self.removed or self.refused):
            return f"{heading}: no trade dates in the store, so nothing to cache."
        built = sum(month.outcome is MonthOutcome.BUILT for month in self.months)
        up_to_date = len(self.months) - built
        trade_dates = sum(len(month.index.trade_dates) for month in self.months)
        size = size_text(sum(month.index.size_bytes() for month in self.months))
        lines = [
            f"{heading}: {counted(built, 'contract-month')} built, {up_to_date} up to date, "
            f"{counted(trade_dates, 'trade date')}, {size}."
        ]
        for month in self.months:
            lines.append(f"  {month.summary()}")
            lines += [f"    {note}" for note in month.index.notes()]
        lines += [f"  {month}: removed, since the store holds none of it" for month in self.removed]
        lines += [f"  {refusal}" for refusal in self.refused]
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
    whose partitions changed since it was cached, is written again, and a month the store no
    longer holds is removed. A month the engine cannot read is refused, and the other
    months still built."""
    months = [YearMonth(year=year, month=number) for number in range(1, 13)]
    built = build_cache_months(store, cache_folder, root, months, provider)
    return EngineCacheBuild(
        provider=built.provider,
        root=root,
        year=year,
        months=built.months,
        removed=built.removed,
        refused=built.refused,
    )


class CachedMonths(NamedTuple):
    """What `build_cache_months` did: the provider it chose, the contract-months built or up to
    date, those removed, and those refused, each with its reason."""

    provider: str
    months: tuple[CachedMonthBuild, ...]
    removed: tuple[str, ...]
    refused: tuple[str, ...]


def build_cache_months(
    store: Store,
    cache_folder: Path,
    root: str,
    months: Sequence[YearMonth],
    provider: str | None = None,
    contracts: Collection[str] | None = None,
) -> CachedMonths:
    """Build the engine cache of `root`'s trade dates of `months`, as `build_engine_cache`
    builds a year's, so that a backtest builds the months it reads alone (step 2.10), of the
    `contracts` it trades where it names them, whose months alone can then refuse it."""
    datasets = tuple(provider_datasets(store, root, provider, origin=None).values())
    chosen = datasets[0].provider
    levels = {dataset: level_of(dataset) for dataset in datasets}
    listed = {
        dataset: tuple(file.partition for file in store.list_partitions(dataset))
        for dataset in datasets
    }
    root_folder = cache_folder / ENGINE_CACHE_FOLDER_NAME / chosen / root
    built: list[CachedMonthBuild] = []
    removed: list[str] = []
    refused: list[str] = []
    for month in months:
        month_built, month_refused, held = _build_month(
            store, root_folder, levels, listed, month, contracts
        )
        built += month_built
        refused += month_refused
        removed += _remove_months_left_behind(root_folder, month, held)
    return CachedMonths(chosen, tuple(built), tuple(removed), tuple(refused))


def level_of(dataset: Dataset) -> Level:
    """The level of the engine cache a dataset of trades, TBBO, or bars feeds."""
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
    contracts: Collection[str] | None,
) -> tuple[list[CachedMonthBuild], list[str], set[str]]:
    """The month's contract-months, built or up to date, those refused, each with its reason,
    of `contracts` where they are named, and the contracts the store holds partitions of in the
    month, whose other months a build keeps."""
    start, end = month.days()
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
    built: list[CachedMonthBuild] = []
    refused: list[str] = []
    for contract, pinned in sorted(by_contract.items()):
        if contracts is not None and contract not in contracts:
            continue
        try:
            month_build = _build_contract_month(store, root_folder / contract, month, pinned)
        except ValueError as error:
            refused.append(f"{contract} {month}: refused, {error}")
            continue
        if month_build is not None:
            built.append(month_build)
    return built, refused, set(by_contract)


def _remove_months_left_behind(root_folder: Path, month: YearMonth, held: set[str]) -> list[str]:
    """Remove the cached `month` of each contract outside `held`, the contracts the store holds
    partitions of in the month, and name each one removed."""
    if not root_folder.is_dir():
        return []
    left_behind = [
        folder
        for folder in sorted(root_folder.iterdir())
        if folder.name not in held and (folder / str(month)).is_dir()
    ]
    for folder in left_behind:
        _remove_stale(folder / str(month))
    return [f"{folder.name} {month}" for folder in left_behind]


def _build_contract_month(
    store: Store, contract_folder: Path, month: YearMonth, pinned: list[_PinnedPartition]
) -> CachedMonthBuild | None:
    """The contract-month as cached, written again unless its index names the same partitions;
    None for a month whose partitions hold no record of it."""
    month_folder = contract_folder / str(month)
    sources = sorted((item.digest.path, item.digest.sha256) for item in pinned)
    cached = _reusable_index(month_folder)
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


def _reusable_index(month_folder: Path) -> CacheMonthIndex | None:
    """The month's index, or None while it has none or one this layout cannot read, such as
    another layout's or one cut short, which the build then writes again."""
    try:
        return read_cache_month_index(month_folder)
    except ValueError:
        return None


def _is_built_from(index: CacheMonthIndex, sources: list[tuple[str, str]]) -> bool:
    built_from = [(source.path, source.sha256) for source in index.sources]
    return index.layout_version == LAYOUT_VERSION and built_from == sources


def _remove_stale(month_folder: Path) -> None:
    """Remove a month's stale cache and any build of it left part way."""
    partial = month_folder.with_name(month_folder.name + PARTIAL_SUFFIX)
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
