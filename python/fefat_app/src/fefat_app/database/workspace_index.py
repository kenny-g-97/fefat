"""The index of the workspace's files (step 4.1, D-84, ADR-0020): `index_workspace` reads the
feature versions, the leak detector's reports, and the saved import profiles that the SDK wrote
under `FEFAT_HOME`, through the SDK, and adds a row for each file it has not seen, in one
transaction, moving and changing no file, so that it can run at any time.

A version is seen by its feature, number, and hash, a report and a profile by their file's
SHA-256, since the leak detector replaces a report with the next of its hash, whose row is added
beside the last. A file the SDK refuses, such as a version changed after it was written, or a
version file deleted or replaced by hand after it was indexed, stops the indexing with the
reason, and no row is added.

A rebuild (the Phase 4 exit, D-92) empties the tables that index the files first, in the same
transaction, lifting the triggers that keep them insert-only and laying them again from their own
text, so that the index holds the files as they are now; the app's own state, the password, the
sessions, the API tokens, and the jobs, stays, and the rows of the reports a validation replaced
leave with their files."""

import hashlib
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, bindparam, delete, select, text
from sqlalchemy.orm import Session

from fefat.config import WORKSPACE_FOLDER, resolve_paths
from fefat.features.validation_report import ValidationReport
from fefat.features.versions import FeatureVersion, saved_versions
from fefat.market.calendar import counted
from fefat.market.importers.profiles import parse_profile
from fefat.market.store_files import parsed_json
from fefat_app.database.models import (
    FeatureRow,
    FeatureValidationRow,
    FeatureVersionRow,
    ImportProfileRow,
    WorkspaceRow,
)

DEFAULT_WORKSPACE = "default"


INDEX_TABLES = ("feature_validations", "feature_versions", "import_profiles")
"""The tables whose rows each index a file, which triggers keep insert-only (migration 0001)."""
INDEX_TRIGGERS = text(
    "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN :tables"
).bindparams(bindparam("tables", expanding=True))


@dataclass(frozen=True)
class IndexSummary:
    """The rows an indexing added, for each kind of file, and whether it rebuilt the index."""

    versions: int
    validations: int
    profiles: int
    rebuilt: bool = False

    def summary(self) -> str:
        if self.rebuilt:
            return (
                "Rebuilt the index from the files as they are: "
                f"{counted(self.versions, 'feature version')}, "
                f"{counted(self.validations, 'validation report')}, and "
                f"{counted(self.profiles, 'import profile')}."
            )
        return (
            f"Indexed {counted(self.versions, 'new feature version')}, "
            f"{counted(self.validations, 'new validation report')}, and "
            f"{counted(self.profiles, 'new import profile')}."
        )


def index_workspace(engine: Engine, *, rebuild: bool = False) -> IndexSummary:
    """Index the files under `FEFAT_HOME` that the database has not seen, or with `rebuild` every
    file, the index emptied first (module docstring); the home is the one the SDK reads,
    `resolve_paths(os.environ)`."""
    paths = resolve_paths(os.environ)
    with Session(engine) as session, session.begin():
        if rebuild:
            _emptied_index(session)
        workspace_id = _default_workspace(session)
        versions = _index_versions(session, workspace_id)
        validations = _index_validations(session, paths.features_dir.glob("*/validations/*.json"))
        profiles = _index_profiles(session, paths.profiles_dir.glob("*.yaml"))
    return IndexSummary(versions, validations, profiles, rebuild)


def _emptied_index(session: Session) -> None:
    """Delete every row that indexes a file, and the features they name, in the session's
    transaction, the triggers that refuse it dropped for it and made again from their own text."""
    connection = session.connection()
    triggers = session.execute(INDEX_TRIGGERS, {"tables": list(INDEX_TABLES)}).all()
    for name, _ in triggers:
        connection.exec_driver_sql(f'DROP TRIGGER "{name}"')
    for model in (FeatureValidationRow, FeatureVersionRow, FeatureRow, ImportProfileRow):
        session.execute(delete(model))
    for _, made in triggers:
        connection.exec_driver_sql(made)


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


def _index_versions(session: Session, workspace_id: str) -> int:
    """A row for each saved version not indexed yet, and one for its feature where it has none;
    the number of versions added."""
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
    for record in saved_versions():
        if record.name not in feature_ids:
            feature_ids[record.name] = _new_feature(session, workspace_id, record.name)
        feature_id = feature_ids[record.name]
        if _seen(
            record, hashes.get((feature_id, record.version)), numbers.get((feature_id, record.hash))
        ):
            continue
        session.add(_version_row(feature_id, record))
        added += 1
    session.flush()
    return added


def _new_feature(session: Session, workspace_id: str, name: str) -> str:
    feature = FeatureRow(workspace_id=workspace_id, name=name)
    session.add(feature)
    session.flush()
    return feature.id


def _seen(record: FeatureVersion, indexed_hash: str | None, indexed_number: int | None) -> bool:
    """Whether the version is indexed, given the hash the index holds for its number and the
    number it holds for its hash; refused where either holds another, as a version file deleted
    or replaced by hand after it was indexed leaves them."""
    if indexed_hash is None and indexed_number is None:
        return False
    redone = (
        "a version file was deleted or replaced by hand after it was indexed, which the index, "
        "kept insert-only, cannot follow: put the files back as they were, or index the files "
        "as they are now with `fefat db import-workspace --rebuild`."
    )
    if indexed_hash is not None and indexed_hash != record.hash:
        raise ValueError(
            f"Expected version {record.version} of feature {record.name} with the hash "
            f"{indexed_hash[:12]} as indexed, got {record.hash[:12]}: {redone}"
        )
    if indexed_number is not None and indexed_number != record.version:
        raise ValueError(
            f"Expected the hash {record.hash[:12]} of feature {record.name} as version "
            f"{indexed_number}, as indexed, got version {record.version}: {redone}"
        )
    return True


def _version_row(feature_id: str, record: FeatureVersion) -> FeatureVersionRow:
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


def _index_validations(session: Session, files: Iterable[Path]) -> int:
    """A row for each report file not indexed yet, linked to the version of its feature and
    hash where one is indexed; the number added."""
    version_ids = {
        (name, content_hash): version_id
        for name, content_hash, version_id in session.execute(
            select(FeatureRow.name, FeatureVersionRow.content_hash, FeatureVersionRow.id).join(
                FeatureRow, FeatureVersionRow.feature_id == FeatureRow.id
            )
        )
    }
    indexed = session.scalars(select(FeatureValidationRow.report_sha256)).all()
    unseen = list(_unseen_files(files, indexed))
    for path, content, sha256 in unseen:
        report = _report(path, content)
        version_id = version_ids.get((report.feature, report.hash))
        session.add(_validation_row(report, sha256, version_id))
    return len(unseen)


def _report(path: Path, content: bytes) -> ValidationReport:
    """The report `path` holds, refused with the way out where the SDK no longer reads it, as
    one written before the leak detector's report took its present form."""
    try:
        return parsed_json(ValidationReport, content, str(path))
    except ValueError as error:
        raise ValueError(
            f"{error}\nValidate the feature again, which writes its report anew in the present "
            "form, or move the file out of the workspace."
        ) from error


def _validation_row(
    report: ValidationReport, sha256: str, version_id: str | None
) -> FeatureValidationRow:
    return FeatureValidationRow(
        feature_version_id=version_id,
        report_sha256=sha256,
        feature_name=report.feature,
        feature_hash=report.hash,
        instrument=report.instrument,
        timeframe=report.timeframe,
        provider=report.provider,
        window_start=report.start,
        window_end=report.end,
        parameters_json=report.parameters,
        passed=report.passed,
        created_at=report.created_at,
    )


def _index_profiles(session: Session, files: Iterable[Path]) -> int:
    """A row for each saved profile file not indexed yet; the number added."""
    indexed = session.scalars(select(ImportProfileRow.sha256)).all()
    unseen = list(_unseen_files(files, indexed))
    for path, content, sha256 in unseen:
        profile = parse_profile(content.decode("utf-8"), str(path))
        session.add(ImportProfileRow(kind=profile.kind, name=profile.name, sha256=sha256))
    return len(unseen)


def _unseen_files(
    files: Iterable[Path], indexed: Iterable[str]
) -> Iterator[tuple[Path, bytes, str]]:
    """The files of `files` in order with their bytes and SHA-256, but those whose SHA-256 is
    indexed or was given before."""
    seen = set(indexed)
    for path in sorted(files):
        content = path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        if sha256 in seen:
            continue
        seen.add(sha256)
        yield path, content, sha256
