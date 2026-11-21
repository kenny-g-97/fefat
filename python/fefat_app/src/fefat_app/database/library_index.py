"""The index of the saved features and strategies in the app's database (step 5.2, D-84,
ADR-0020), `fefat_app.ports.LibraryIndex`: `refresh` indexes the versions under the workspace's
folders through `index_library`, its refusal a `LibraryRefusedError` in the indexer's words, and
the lists read the tables, each in a transaction of its own that only reads; a strategy's with
its abandoned mark and the time of its newest saved run (step 5.5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fefat.config import FefatPaths
from fefat.strategy.abandoned_marks import AbandonedMark
from fefat_app.database.models import (
    FeatureRow,
    FeatureVersionRow,
    RunRow,
    StrategyRow,
    StrategyVersionRow,
)
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
            last_runs = _last_saved_runs(session)
            rows = session.execute(
                select(StrategyRow, StrategyVersionRow)
                .join(StrategyVersionRow, StrategyVersionRow.strategy_id == StrategyRow.id)
                .order_by(StrategyRow.name, StrategyVersionRow.version_no)
            )
            return tuple(
                _strategy(strategy, [version for _, version in grouped], last_runs)
                for strategy, grouped in groupby(rows, key=lambda row: row[0])
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


def _last_saved_runs(session: Session) -> dict[str, datetime]:
    """When each strategy's newest saved run was made, by the strategy's row: a run's row, once
    its folder is saved, keeps its submission's time, or its folder's where no submission made
    it (`fefat_app.database.run_records`)."""
    # shortcut: the runs the index holds alone, so a run a notebook saved counts once a run's
    # POST or `fefat db import-workspace` indexes it; index the run folders as step 5.6's runs
    # page does, when it does.
    rows = session.execute(
        select(StrategyVersionRow.strategy_id, func.max(RunRow.created_at))
        .join(RunRow, RunRow.strategy_version_id == StrategyVersionRow.id)
        .where(RunRow.run_key.is_not(None))
        .group_by(StrategyVersionRow.strategy_id)
    )
    return {strategy_id: made for strategy_id, made in rows}


def _strategy(
    strategy: StrategyRow,
    versions: Sequence[StrategyVersionRow],
    last_runs: dict[str, datetime],
) -> IndexedStrategy:
    mark = strategy.abandoned_json
    return IndexedStrategy(
        id=strategy.id,
        name=strategy.name,
        kind=strategy.kind,
        versions=tuple(_strategy_version(version) for version in versions),
        abandoned=None if mark is None else AbandonedMark.model_validate(mark),
        last_run_at=last_runs.get(strategy.id),
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
