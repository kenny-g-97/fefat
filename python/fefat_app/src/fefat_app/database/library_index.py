"""The index of the saved features and strategies in the app's database (step 5.2, D-84,
ADR-0020), `fefat_app.ports.LibraryIndex`: `refresh` indexes the versions under the workspace's
folders through `index_library`, its refusal a `LibraryRefusedError` in the indexer's words, and
the lists read the tables, each in a transaction of its own that only reads."""

from dataclasses import dataclass
from itertools import groupby

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from fefat.config import FefatPaths
from fefat_app.database.models import FeatureRow, FeatureVersionRow, StrategyRow, StrategyVersionRow
from fefat_app.database.schema import reading
from fefat_app.database.version_index import index_library
from fefat_app.library import (
    IndexedFeature,
    IndexedStrategy,
    IndexedStrategyVersion,
    IndexedVersion,
    LibraryRefusedError,
)


@dataclass(frozen=True)
class LibraryTables:
    """`LibraryIndex` in the tables of `engine`'s database, over the library under `paths`."""

    engine: Engine
    paths: FefatPaths

    def refresh(self) -> None:
        try:
            index_library(self.engine, self.paths)
        except ValueError as refused:
            raise LibraryRefusedError(str(refused)) from refused

    def strategies(self) -> tuple[IndexedStrategy, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.execute(
                select(StrategyRow, StrategyVersionRow)
                .join(StrategyVersionRow, StrategyVersionRow.strategy_id == StrategyRow.id)
                .order_by(StrategyRow.name, StrategyVersionRow.version_no)
            )
            return tuple(
                IndexedStrategy(
                    id=strategy.id,
                    name=strategy.name,
                    kind=strategy.kind,
                    versions=tuple(_strategy_version(version) for _, version in versions),
                )
                for strategy, versions in groupby(rows, key=lambda row: row[0])
            )

    def features(self) -> tuple[IndexedFeature, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.execute(
                select(FeatureRow, FeatureVersionRow)
                .join(FeatureVersionRow, FeatureVersionRow.feature_id == FeatureRow.id)
                .order_by(FeatureRow.name, FeatureVersionRow.version_no)
            )
            return tuple(
                IndexedFeature(
                    id=feature.id,
                    name=feature.name,
                    versions=tuple(
                        IndexedVersion(
                            id=version.id,
                            version=version.version_no,
                            hash=version.content_hash,
                            created_at=version.created_at,
                        )
                        for _, version in versions
                    ),
                )
                for feature, versions in groupby(rows, key=lambda row: row[0])
            )


def _strategy_version(version: StrategyVersionRow) -> IndexedStrategyVersion:
    return IndexedStrategyVersion(
        id=version.id,
        version=version.version_no,
        hash=version.content_hash,
        created_at=version.created_at,
        instrument=version.instrument,
        timeframe=version.timeframe,
        hypothesis=version.hypothesis,
        changelog=version.changelog,
    )
