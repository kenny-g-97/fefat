"""What the feature cache holds (step 3.3, `02-engine-and-data.md` §6): beside each folder of
cached partitions, an `index.json` that names each partition with the key of what it was
computed from, its rows, the size of its file, and when a computation last read or wrote it, as
the engine cache keeps its months' (D-56), until the database of Phase 4. `feature_cache_status`
lists the cache and `prune_feature_cache` removes the partitions unused for a while, which
`ff.features.cache_status()` and `fefat cache features [--prune]` run:

    ff.features.cache_status()

The cache is `<FEFAT_HOME>/cache/features/<provider>/<symbol>/<timeframe>/`, a folder `bars` of
the signal bars and a folder `<feature>-<key>` for each feature with its parameters and the
features it reads (`fefat.features.cache`). Each index is written whole in one step; two
processes writing one folder at once keep the index of the one that writes last, and a partition
that index leaves out is computed again when it is next asked for.
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import polars as pl
from pydantic import AwareDatetime, Field, JsonValue

from fefat.config import resolve_paths
from fefat.market.engine_cache_index import INDEX_FILE_NAME
from fefat.market.layout import YearMonth
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256
from fefat.market.store_files import json_writer, parsed_json, write_atomically

FEATURE_CACHE_FOLDER_NAME = "features"
"""The feature cache's folder in `FEFAT_HOME/cache` (`fefat.config.FefatPaths.cache_dir`)."""
BARS_FOLDER_NAME = "bars"
"""The folder of a timeframe's signal bars, which every feature of it reads."""
KEY_METADATA = "fefat_key"
"""The entry of a partition file's own metadata that holds the key it was computed under."""
FEATURE_CACHE_COLUMNS = pl.Schema(
    {
        "provider": pl.String,
        "instrument": pl.String,
        "timeframe": pl.String,
        "feature": pl.String,
        "parameters": pl.String,
        "key": pl.String,
        "partitions": pl.Int64,
        "first": pl.Date,
        "last": pl.Date,
        "size_bytes": pl.Int64,
        "last_used": pl.Datetime("us", "UTC"),
    }
)
"""A row of `feature_cache_status`: a folder's provider, symbol, and timeframe, its feature with
its parameters and the start of its folder's key, `bars` for the signal bars, its partitions,
the first and last trade dates they span, their size, and when one was last used."""


class CachedPartition(FrozenModel):
    """A partition of a folder: the key of what it was computed from, its rows, the size of its
    file, and when a computation last read or wrote it."""

    key: Sha256
    rows: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    last_used: AwareDatetime


class CachedFeature(FrozenModel):
    """A feature whose values a folder holds, or one it reads: its name, its content hash, its
    parameters, and the timeframe of the grid it is evaluated on."""

    name: str
    hash: Sha256
    parameters: dict[str, JsonValue]
    timeframe: str


class FeatureCacheIndex(FrozenModel):
    """A folder's `index.json`: the provider, symbol, and timeframe of the signal bars; the
    feature whose values the folder holds, None for the folder of the signal bars, and the
    features it reads, in the order they are evaluated; and each partition by its name, such as
    `2026-03` or `2026-03-05`."""

    provider: str
    symbol: str
    timeframe: str
    feature: CachedFeature | None
    reads: tuple[CachedFeature, ...]
    partitions: dict[str, CachedPartition]

    def with_partitions(self, partitions: dict[str, CachedPartition]) -> "FeatureCacheIndex":
        return self.model_copy(update={"partitions": partitions})


def readable_index(folder: Path) -> FeatureCacheIndex | None:
    """The folder's index, or None while it has none, or one this code cannot read, which a
    computation writes again, as the engine cache does a month's (D-56), and pruning
    removes."""
    try:
        return read_cache_index(folder)
    except ValueError:
        return None


def read_cache_index(folder: Path) -> FeatureCacheIndex | None:
    """The folder's index, or None while it has none."""
    path = folder / INDEX_FILE_NAME
    if not path.is_file():
        return None
    return parsed_json(FeatureCacheIndex, path.read_bytes(), str(path))


def write_cache_index(folder: Path, index: FeatureCacheIndex) -> None:
    """Write the folder's index in one step (`write_atomically`)."""
    write_atomically(folder / INDEX_FILE_NAME, json_writer(index))


def partition_dates(name: str) -> tuple[date, date]:
    """The first and last day of a partition: its month's, or its one trade date."""
    if len(name) == len("2026-03"):
        return YearMonth.parse(name).days()
    day = date.fromisoformat(name)
    return day, day


def cache_status() -> pl.DataFrame:
    """The feature cache in `FEFAT_HOME/cache/features/`, a row for each folder
    (`feature_cache_status`)."""
    return feature_cache_status(resolve_paths(os.environ).cache_dir)


def feature_cache_status(cache_folder: Path) -> pl.DataFrame:
    """A row for each folder of the feature cache in `cache_folder` (`FEFAT_HOME/cache`), with
    the columns of `FEATURE_CACHE_COLUMNS`, sorted by provider, instrument, timeframe, and
    feature; none while the cache is empty."""
    rows = [_status_row(folder, index) for folder, index in _indexes(cache_folder)]
    frame = pl.DataFrame(rows, schema=FEATURE_CACHE_COLUMNS, orient="row")
    return frame.sort("provider", "instrument", "timeframe", "feature", "key")


def _status_row(folder: Path, index: FeatureCacheIndex) -> tuple[object, ...]:
    spans = [partition_dates(name) for name in index.partitions]
    feature = index.feature
    named = BARS_FOLDER_NAME if feature is None else feature.name
    parameters = "" if feature is None else _parameters_text(feature)
    key = "" if feature is None else folder.name.removeprefix(f"{feature.name}-")
    return (
        index.provider,
        index.symbol,
        index.timeframe,
        named,
        parameters,
        key,
        len(index.partitions),
        min((first for first, _ in spans), default=None),
        max((last for _, last in spans), default=None),
        sum(partition.size_bytes for partition in index.partitions.values()),
        max((partition.last_used for partition in index.partitions.values()), default=None),
    )


def _parameters_text(feature: CachedFeature) -> str:
    return ", ".join(f"{name}={value}" for name, value in feature.parameters.items())


class PrunedCache(NamedTuple):
    """What `prune_feature_cache` did: the partitions removed and those kept, with their sizes,
    and the files another program held open, which Windows will not remove, kept with their
    partitions."""

    removed: int
    removed_bytes: int
    kept: int
    kept_bytes: int
    held: tuple[Path, ...]


def prune_feature_cache(cache_folder: Path, older_than: timedelta, now: datetime) -> PrunedCache:
    """Remove from the feature cache in `cache_folder` each partition last used `older_than`
    or longer before `now`, each file of a folder its index does not name, all of a folder whose
    index this code cannot read, and a folder left without partitions, so that what remains is
    what was used since; a file another program holds open stays, named in `held`."""
    pruned = PrunedCache(0, 0, 0, 0, ())
    folders = sorted((cache_folder / FEATURE_CACHE_FOLDER_NAME).glob(f"*/*/*/*/{INDEX_FILE_NAME}"))
    for path in folders:
        pruned = _pruned(path.parent, now - older_than, pruned)
    _remove_empty_folders(cache_folder / FEATURE_CACHE_FOLDER_NAME)
    return pruned


def _pruned(folder: Path, used_after: datetime, pruned: PrunedCache) -> PrunedCache:
    """`pruned` with the folder's partitions last used by `used_after` removed, and its files
    that its index does not name."""
    index = readable_index(folder)
    partitions = {} if index is None else index.partitions
    held: list[Path] = []
    kept = {
        name: partition
        for name, partition in partitions.items()
        if partition.last_used > used_after or not _unlinked(folder / f"{name}.parquet", held)
    }
    for path in folder.glob("*.parquet"):
        if path.stem not in partitions:
            _unlinked(path, held)
    if index is not None and kept:
        write_cache_index(folder, index.with_partitions(kept))
    else:
        _unlinked(folder / INDEX_FILE_NAME, held)
    gone = [partition for name, partition in partitions.items() if name not in kept]
    return PrunedCache(
        removed=pruned.removed + len(gone),
        removed_bytes=pruned.removed_bytes + sum(partition.size_bytes for partition in gone),
        kept=pruned.kept + len(kept),
        kept_bytes=pruned.kept_bytes + sum(partition.size_bytes for partition in kept.values()),
        held=(*pruned.held, *held),
    )


def _unlinked(path: Path, held: list[Path]) -> bool:
    """Whether the file is gone, removed now or before; one another program holds open stays,
    added to `held`."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        held.append(path)
        return False
    return True


def _remove_empty_folders(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*"), key=lambda each: len(each.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _indexes(cache_folder: Path) -> list[tuple[Path, FeatureCacheIndex]]:
    """Each folder of the feature cache with its index, in path order, but one whose index
    this code cannot read, which holds nothing a computation reads."""
    found = []
    for path in sorted(
        (cache_folder / FEATURE_CACHE_FOLDER_NAME).glob(f"*/*/*/*/{INDEX_FILE_NAME}")
    ):
        index = readable_index(path.parent)
        if index is not None:
            found.append((path.parent, index))
    return found
