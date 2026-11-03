"""The folders of the feature cache in one computation (`fefat.features.cache`, step 3.3): the
signal bars' folder, `bars`, and a folder for each slot's feature, named by the feature and a key
of its parameters and those of the features it reads, each with its timeframe, on the reader's
grid. Each holds its index as read (`fefat.features.cache_index`) and reads a partition back
while its key is the one given."""

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from fefat.features.cache_index import (
    BARS_FOLDER_NAME,
    KEY_METADATA,
    CachedFeature,
    FeatureCacheIndex,
    readable_index,
)
from fefat.features.cache_keys import CachePartition
from fefat.features.evaluation import FeatureSpec
from fefat.features.runtime import FeatureGraph
from fefat.market.api import SeriesSource
from fefat.market.schema import Timeframe


@dataclass(frozen=True)
class CacheFolder:
    """A folder of the cache in one computation, with its index as read."""

    path: Path
    index: FeatureCacheIndex

    def cached(self, partition: CachePartition, key: str) -> pl.DataFrame | None:
        """The partition's frame, read while its key is `key` in the index and in the file
        itself, which two processes writing one folder at once can leave apart; None
        otherwise, and where its file cannot be read, as one another program damaged,
        which the computation writes again."""
        held = self.index.partitions.get(partition.name)
        path = self.path / f"{partition.name}.parquet"
        if held is None or held.key != key or not path.is_file():
            return None
        try:
            content = path.read_bytes()
            if pl.read_parquet_metadata(io.BytesIO(content)).get(KEY_METADATA) != key:
                return None
            return pl.read_parquet(io.BytesIO(content))
        except (OSError, pl.exceptions.PolarsError):
            return None


@dataclass(frozen=True)
class FeatureFolder(CacheFolder):
    """The folder of a slot's feature: the graph of the slot (`FeatureGraph.of_slot`) and what
    names its feature with its parameters and the features it reads on the reader's grid."""

    graph: FeatureGraph
    identity: str

    @property
    def slot(self) -> str:
        return next(iter(self.graph.slots))

    def outputs(self) -> list[str]:
        return list(self.graph.slots[self.slot].spec.definition.outputs)


def bars_folder(folder: Path, source: SeriesSource, timeframe: Timeframe) -> CacheFolder:
    fresh = FeatureCacheIndex(
        provider=source.provider,
        symbol=source.symbol,
        timeframe=str(timeframe),
        feature=None,
        reads=(),
        partitions={},
    )
    path = folder / BARS_FOLDER_NAME
    return CacheFolder(path, _readable(path, fresh))


def feature_folder(
    folder: Path, graph: FeatureGraph, slot: str, source: SeriesSource
) -> FeatureFolder:
    """The folder of the slot's feature, named by the feature and a key of its parameters and
    those of the features it reads, each with its timeframe, on the graph's grid."""
    sub = graph.of_slot(slot)
    node = sub.slots[slot]
    feature = _cached_feature(node.spec, node.timeframe)
    reads = tuple(
        sorted(
            (_cached_feature(read.spec, read.timeframe) for read in sub.order if read != node),
            key=lambda each: each.model_dump_json(),
        )
    )
    described = [each.model_dump(mode="json") for each in (*reads, feature)]
    identity = f"values on {graph.timeframe} {json.dumps(described, sort_keys=True)}"
    path = folder / f"{feature.name}-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
    fresh = FeatureCacheIndex(
        provider=source.provider,
        symbol=source.symbol,
        timeframe=str(graph.timeframe),
        feature=feature,
        reads=reads,
        partitions={},
    )
    return FeatureFolder(path, _readable(path, fresh), sub, identity)


def _cached_feature(spec: FeatureSpec, timeframe: Timeframe) -> CachedFeature:
    return CachedFeature(
        name=spec.definition.name,
        hash=spec.definition.hash,
        parameters=spec.parameters.model_dump(mode="json"),
        timeframe=str(timeframe),
    )


def _readable(path: Path, fresh: FeatureCacheIndex) -> FeatureCacheIndex:
    """The folder's index; `fresh` where it has none, or one this code cannot read
    (`readable_index`)."""
    index = readable_index(path)
    return fresh if index is None else index
