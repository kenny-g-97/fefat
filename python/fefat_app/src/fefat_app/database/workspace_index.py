"""The index of the workspace's files (step 4.1, D-84, ADR-0020): `index_workspace` reads the
feature versions and, from step 5.2, the strategy versions (`fefat_app.database.version_index`),
the leak detector's reports, the saved import profiles, and, from step 5.3, the saved runs
(`fefat_app.database.run_records`) that the SDK wrote under the folders it is given (D-93),
through the SDK, and adds a row for each file it has not seen, in one transaction, moving and
changing no file, so that it can run at any time; the run folders are read before the write
lock is taken.

A report and a profile are seen by their file's SHA-256, since the leak detector replaces a
report with the next of its hash, whose row is added beside the last. A file the SDK refuses
stops the indexing with the reason, and no row is added.

A rebuild (the Phase 4 exit, D-92) empties the tables that index the files first, in the same
transaction, lifting the triggers that keep them insert-only and laying them again from their own
text, so that the index holds the files as they are now; the app's own state, the password, the
sessions, the API tokens, and the jobs, stays, and the rows of the reports a validation replaced
leave with their files, as do the runs asked for through the API that were never saved, whose
jobs keep their errors."""

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, bindparam, delete, select, text
from sqlalchemy.orm import Session

from fefat.backtest import saved_runs_in
from fefat.config import FefatPaths
from fefat.features.validation_report import ValidationReport
from fefat.market.calendar import counted
from fefat.market.importers.profiles import parse_profile
from fefat.market.store_files import parsed_json
from fefat_app.database.models import (
    FeatureRow,
    FeatureValidationRow,
    FeatureVersionRow,
    ImportProfileRow,
    RunRow,
    StrategyRow,
    StrategyVersionFeatureRow,
    StrategyVersionRow,
)
from fefat_app.database.run_records import index_runs
from fefat_app.database.version_index import index_versions

INDEX_TABLES = (
    "feature_validations",
    "feature_versions",
    "import_profiles",
    "strategy_versions",
    "strategy_version_features",
    "runs",
)
"""The tables whose rows each index a file, which triggers keep insert-only (migrations 0001,
0004, and 0005, a run's row once saved)."""
INDEX_TRIGGERS = text(
    "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN :tables"
).bindparams(bindparam("tables", expanding=True))
INDEXED_ROWS = (
    RunRow,
    FeatureValidationRow,
    StrategyVersionFeatureRow,
    StrategyVersionRow,
    StrategyRow,
    FeatureVersionRow,
    FeatureRow,
    ImportProfileRow,
)
"""The rows a rebuild deletes, each before the rows it names, since the foreign keys hold."""


@dataclass(frozen=True)
class IndexSummary:
    """The rows an indexing added, for each kind of file, and whether it rebuilt the index."""

    feature_versions: int
    strategy_versions: int
    validations: int
    profiles: int
    runs: int
    rebuilt: bool = False

    def summary(self) -> str:
        if self.rebuilt:
            return (
                "Rebuilt the index from the files as they are: "
                f"{counted(self.feature_versions, 'feature version')}, "
                f"{counted(self.strategy_versions, 'strategy version')}, "
                f"{counted(self.validations, 'validation report')}, "
                f"{counted(self.profiles, 'import profile')}, and "
                f"{counted(self.runs, 'run')}."
            )
        return (
            f"Indexed {counted(self.feature_versions, 'new feature version')}, "
            f"{counted(self.strategy_versions, 'new strategy version')}, "
            f"{counted(self.validations, 'new validation report')}, "
            f"{counted(self.profiles, 'new import profile')}, and "
            f"{counted(self.runs, 'new run')}."
        )


def index_workspace(engine: Engine, paths: FefatPaths, *, rebuild: bool = False) -> IndexSummary:
    """Index the files under `paths` that the database has not seen, or with `rebuild` every
    file, the index emptied first (module docstring)."""
    runs = saved_runs_in(paths.runs_dir)
    with Session(engine) as session, session.begin():
        if rebuild:
            _emptied_index(session)
        feature_versions, strategy_versions = index_versions(session, paths)
        validations = _index_validations(session, paths.features_dir.glob("*/validations/*.json"))
        profiles = _index_profiles(session, paths.profiles_dir.glob("*.yaml"))
        indexed_runs = index_runs(session, runs)
    return IndexSummary(
        feature_versions=feature_versions,
        strategy_versions=strategy_versions,
        validations=validations,
        profiles=profiles,
        runs=indexed_runs,
        rebuilt=rebuild,
    )


def _emptied_index(session: Session) -> None:
    """Delete every row that indexes a file, and the features and strategies they name, in the
    session's transaction, the triggers that refuse it dropped for it and made again from their
    own text."""
    connection = session.connection()
    triggers = session.execute(INDEX_TRIGGERS, {"tables": list(INDEX_TABLES)}).all()
    for name, _ in triggers:
        connection.exec_driver_sql(f'DROP TRIGGER "{name}"')
    for model in INDEXED_ROWS:
        session.execute(delete(model))
    for _, made in triggers:
        connection.exec_driver_sql(made)


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
