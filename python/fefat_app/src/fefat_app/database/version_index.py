"""The index of the library's versions (step 4.1, D-84, ADR-0020; step 5.2, D-93): the feature
versions and the strategy versions the SDK saved under the folders it is given, read through the
SDK, a row added for each version not seen yet, and a row for each feature version a strategy
version pins, which are indexed first; `index_library` indexes them alone, in one transaction,
which the app does around each save, so that a report or a profile the SDK refuses holds up no
save, and `fefat_app.database.workspace_index` with the rest of the workspace.

A version is seen by its feature or strategy, number, and hash. A version file the SDK refuses,
such as one changed after it was written, or one deleted or replaced by hand after it was
indexed, stops the indexing with the reason, and no row is added."""

from collections.abc import Iterable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from fefat.config import WORKSPACE_FOLDER, FefatPaths
from fefat.features.versions import FeatureVersion, saved_versions_in
from fefat.strategy.versions import StrategyVersion
from fefat.strategy.versions import saved_versions_in as saved_strategy_versions_in
from fefat_app.database.models import (
    FeatureRow,
    FeatureVersionRow,
    StrategyRow,
    StrategyVersionFeatureRow,
    StrategyVersionRow,
    WorkspaceRow,
)
from fefat_app.database.uuid7 import new_uuid7

DEFAULT_WORKSPACE = "default"


def index_library(engine: Engine, paths: FefatPaths) -> None:
    """Index the feature and strategy versions under `paths` that the database has not seen, in
    one transaction, without the reports and the profiles (module docstring)."""
    with Session(engine) as session, session.begin():
        index_versions(session, paths)


def index_versions(session: Session, paths: FefatPaths) -> tuple[int, int]:
    """Index the feature versions, then the strategy versions that pin them; how many of each
    were added."""
    workspace_id = _default_workspace(session)
    features = _index_feature_versions(session, workspace_id, saved_versions_in(paths.features_dir))
    strategies = _index_strategy_versions(
        session, workspace_id, saved_strategy_versions_in(paths.strategies_dir)
    )
    return features, strategies


def _default_workspace(session: Session) -> str:
    """The id of the one workspace of the first release, added where it has no row."""
    found = session.scalars(
        select(WorkspaceRow.id).where(WorkspaceRow.name == DEFAULT_WORKSPACE)
    ).one_or_none()
    if found is not None:
        return found
    workspace = WorkspaceRow(name=DEFAULT_WORKSPACE, path=WORKSPACE_FOLDER.as_posix())
    session.add(workspace)
    session.flush()
    return workspace.id


def _index_feature_versions(
    session: Session, workspace_id: str, records: Iterable[FeatureVersion]
) -> int:
    """A row for each saved feature version not indexed yet, and one for its feature where it has
    none; the number of versions added."""
    feature_ids = {
        name: feature_id
        for name, feature_id in session.execute(
            select(FeatureRow.name, FeatureRow.id).where(FeatureRow.workspace_id == workspace_id)
        )
    }
    indexed = session.execute(
        select(
            FeatureVersionRow.feature_id,
            FeatureVersionRow.version_no,
            FeatureVersionRow.content_hash,
        )
    ).all()
    hashes = {(feature_id, number): content_hash for feature_id, number, content_hash in indexed}
    numbers = {(feature_id, content_hash): number for feature_id, number, content_hash in indexed}
    added = 0
    for record in records:
        if record.name not in feature_ids:
            feature_ids[record.name] = _new_feature(session, workspace_id, record.name)
        feature_id = feature_ids[record.name]
        indexed_hash = hashes.get((feature_id, record.version))
        indexed_number = numbers.get((feature_id, record.hash))
        if _seen("feature", record, indexed_hash, indexed_number):
            continue
        session.add(_feature_version_row(feature_id, record))
        added += 1
    session.flush()
    return added


def _new_feature(session: Session, workspace_id: str, name: str) -> str:
    feature = FeatureRow(workspace_id=workspace_id, name=name)
    session.add(feature)
    session.flush()
    return feature.id


def _seen(
    kind: str,
    record: FeatureVersion | StrategyVersion,
    indexed_hash: str | None,
    indexed_number: int | None,
) -> bool:
    """Whether the version of a feature or a strategy, as `kind` names it, is indexed, given the
    hash the index holds for its number and the number it holds for its hash; refused where
    either holds another, as a version file deleted or replaced by hand after it was indexed
    leaves them."""
    if indexed_hash is None and indexed_number is None:
        return False
    redone = (
        "a version file was deleted or replaced by hand after it was indexed, which the index, "
        "kept insert-only, cannot follow: put the files back as they were, or index the files "
        "as they are now with `fefat db import-workspace --rebuild`."
    )
    if indexed_hash is not None and indexed_hash != record.hash:
        raise ValueError(
            f"Expected version {record.version} of {kind} {record.name} with the hash "
            f"{indexed_hash[:12]} as indexed, got {record.hash[:12]}: {redone}"
        )
    if indexed_number is not None and indexed_number != record.version:
        raise ValueError(
            f"Expected the hash {record.hash[:12]} of {kind} {record.name} as version "
            f"{indexed_number}, as indexed, got version {record.version}: {redone}"
        )
    return True


def _feature_version_row(feature_id: str, record: FeatureVersion) -> FeatureVersionRow:
    written = record.model_dump(mode="json")
    return FeatureVersionRow(
        feature_id=feature_id,
        version_no=record.version,
        content_hash=record.hash,
        code=record.code,
        params_schema_json=record.parameter_schema,
        inputs_json=written["inputs"],
        outputs_json=written["outputs"],
        warmup=record.warmup,
        warmup_sessions=record.warmup_sessions,
        combination_json=written["combination"],
        created_at=record.created_at,
    )


def _index_strategy_versions(
    session: Session, workspace_id: str, records: Iterable[StrategyVersion]
) -> int:
    """A row for each saved strategy version not indexed yet, one for its strategy where it has
    none, and one for each feature version it pins; the number of versions added. The versions
    are kept before their pins, which name them, since no relationship orders their rows."""
    strategy_ids = {
        name: strategy_id
        for name, strategy_id in session.execute(
            select(StrategyRow.name, StrategyRow.id).where(StrategyRow.workspace_id == workspace_id)
        )
    }
    indexed = session.execute(
        select(
            StrategyVersionRow.strategy_id,
            StrategyVersionRow.version_no,
            StrategyVersionRow.content_hash,
        )
    ).all()
    hashes = {(strategy_id, number): found for strategy_id, number, found in indexed}
    numbers = {(strategy_id, found): number for strategy_id, number, found in indexed}
    feature_versions = _feature_versions(session, workspace_id)
    versions: list[StrategyVersionRow] = []
    pins: list[StrategyVersionFeatureRow] = []
    for record in records:
        if record.name not in strategy_ids:
            strategy_ids[record.name] = _new_strategy(session, workspace_id, record)
        strategy_id = strategy_ids[record.name]
        indexed_hash = hashes.get((strategy_id, record.version))
        indexed_number = numbers.get((strategy_id, record.hash))
        if _seen("strategy", record, indexed_hash, indexed_number):
            continue
        version = _strategy_version_row(strategy_id, record)
        versions.append(version)
        pins.extend(_pin_rows(version.id, record, feature_versions))
    session.add_all(versions)
    session.flush()
    session.add_all(pins)
    session.flush()
    return len(versions)


def _new_strategy(session: Session, workspace_id: str, record: StrategyVersion) -> str:
    strategy = StrategyRow(workspace_id=workspace_id, name=record.name, kind=record.kind)
    session.add(strategy)
    session.flush()
    return strategy.id


def _strategy_version_row(strategy_id: str, record: StrategyVersion) -> StrategyVersionRow:
    return StrategyVersionRow(
        id=new_uuid7(),
        strategy_id=strategy_id,
        version_no=record.version,
        content_hash=record.hash,
        code=record.code,
        hypothesis=record.hypothesis,
        instrument=record.instrument,
        timeframe=record.timeframe,
        params_schema_json=record.parameter_schema,
        changelog=record.changelog,
        created_at=record.created_at,
    )


def _feature_versions(
    session: Session, workspace_id: str
) -> dict[tuple[str, int], tuple[str, str]]:
    """Each indexed feature version's id and hash, by its feature's name and its number."""
    rows = session.execute(
        select(
            FeatureRow.name,
            FeatureVersionRow.version_no,
            FeatureVersionRow.id,
            FeatureVersionRow.content_hash,
        )
        .join(FeatureRow, FeatureVersionRow.feature_id == FeatureRow.id)
        .where(FeatureRow.workspace_id == workspace_id)
    )
    return {(name, number): (version_id, found) for name, number, version_id, found in rows}


def _pin_rows(
    version_id: str,
    record: StrategyVersion,
    feature_versions: dict[tuple[str, int], tuple[str, str]],
) -> list[StrategyVersionFeatureRow]:
    """A row for each feature version `record` pins, refused where the library holds no version
    of its name, number, and hash, as a feature's version file deleted by hand leaves it."""
    rows: list[StrategyVersionFeatureRow] = []
    for pin in record.pinned_features:
        indexed = feature_versions.get((pin.name, pin.version))
        if indexed is None or indexed[1] != pin.hash:
            got = "none" if indexed is None else f"the hash {indexed[1][:12]}"
            raise ValueError(
                f"Expected version {pin.version} of feature {pin.name}, which version "
                f"{record.version} of strategy {record.name} pins, in the library with the hash "
                f"{pin.hash[:12]}, got {got}: put that version's file back as it was saved."
            )
        rows.append(
            StrategyVersionFeatureRow(
                strategy_version_id=version_id,
                feature_version_id=indexed[0],
                created_at=record.created_at,
            )
        )
    return rows
