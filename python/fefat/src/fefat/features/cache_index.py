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
import shutil
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
        month = YearMonth.parse(name)
        following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        return date(month.year, month.month, 1), following - timedelta(days=1)
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
    """What `prune_feature_cache` did: the partitions removed and those kept, with their
    sizes."""

    removed: int
    removed_bytes: int
    kept: int
    kept_bytes: int


def prune_feature_cache(cache_folder: Path, older_than: timedelta, now: datetime) -> PrunedCache:
    """Remove from the feature cache in `cache_folder` each partition last used `older_than`
    or longer before `now`, and each file of a folder its index does not name, and a folder
    left without partitions, so that what remains is what was used since."""
    removed = removed_bytes = kept = kept_bytes = 0
    for folder, index in _indexes(cache_folder):
        fresh = {
            name: partition
            for name, partition in index.partitions.items()
            if partition.last_used > now - older_than
        }
        stale = [partition for name, partition in index.partitions.items() if name not in fresh]
        removed += len(stale)
        removed_bytes += sum(partition.size_bytes for partition in stale)
        kept += len(fresh)
        kept_bytes += sum(partition.size_bytes for partition in fresh.values())
        _keep_only(folder, index.with_partitions(fresh))
    _remove_empty_folders(cache_folder / FEATURE_CACHE_FOLDER_NAME)
    return PrunedCache(removed, removed_bytes, kept, kept_bytes)


def _keep_only(folder: Path, index: FeatureCacheIndex) -> None:
    """Leave in `folder` the partitions `index` names, and the index; the folder goes when it
    names none."""
    if not index.partitions:
        shutil.rmtree(folder)
        return
    for path in folder.glob("*.parquet"):
        if path.stem not in index.partitions:
            path.unlink()
    write_cache_index(folder, index)


def _remove_empty_folders(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*"), key=lambda each: len(each.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _indexes(cache_folder: Path) -> list[tuple[Path, FeatureCacheIndex]]:
    """Each folder of the feature cache with its index, in path order."""
    found = []
    for path in sorted(
        (cache_folder / FEATURE_CACHE_FOLDER_NAME).glob(f"*/*/*/*/{INDEX_FILE_NAME}")
    ):
        index = read_cache_index(path.parent)
        if index is not None:
            found.append((path.parent, index))
    return found
