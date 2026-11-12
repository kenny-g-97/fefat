"""The runs' records over the app's database (step 5.3, `fefat_app.ports.RunRecords`, ADR-0020):
the `runs` table, a row for each backtest asked for through the API, with its queued `backtest`
job until its folder is saved, then the index of the folder, `runs/<run key>/run.json`, which
stays the record; and, through `index_runs`, a row for each saved folder no row holds, which
`fefat db import-workspace` finds. Each call is a transaction of its own
(`fefat_app.database.schema`); a folder's record is read through the SDK before the write lock is
taken, so that no writer waits on a file read. A row's columns, once its run key is set, are
those of its folder's record, whatever its submission asked, so that the index holds the folders
as `--rebuild` would."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, undefer

from fefat.backtest import Run
from fefat.backtest.metrics import Metrics
from fefat.backtest.run_config import AppliedRunConfig
from fefat.backtest.saved_runs import saved_run
from fefat.config import FefatPaths
from fefat.market.fidelity import FidelityEra
from fefat.strategy import StrategyPin
from fefat_app.database.job_records import queued_job
from fefat_app.database.models import JobRow, RunRow, StrategyRow, StrategyVersionRow
from fefat_app.database.schema import reading
from fefat_app.job_models import ACTIVE, JobKind, JobStatus
from fefat_app.runs import (
    IndexedRun,
    NewRun,
    RunOrigin,
    RunStrategy,
    RunWithMetrics,
    Submitted,
)


@dataclass(frozen=True)
class RunTables:
    """`RunRecords` in the tables of `engine`'s database, over the run folders under `paths`."""

    engine: Engine
    paths: FefatPaths

    def submitted(self, new: NewRun, max_attempts: int, now: datetime) -> Submitted:
        with Session(self.engine) as session, session.begin():
            waiting = None if new.request_key is None else _waiting_on(session, new.request_key)
            if waiting is not None:
                return Submitted(run=_indexed(session, waiting), queued_job_id=None)
            job = queued_job(session, JobKind.BACKTEST, new.payload, max_attempts, now)
            row = RunRow(
                origin=RunOrigin.MANUAL,
                strategy_version_id=new.strategy_version_id,
                parameters_json=dict(new.parameters),
                window_start=new.start,
                window_end=new.end,
                settings_json=new.settings.model_dump(mode="json"),
                request_key=new.request_key,
                job_id=job.id,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return Submitted(run=_indexed(session, row), queued_job_id=job.id)

    def saved(
        self, run_key: str, *, job_id: str | None = None, request_key: str | None = None
    ) -> IndexedRun:
        run = saved_run(self.paths.runs_dir, run_key)
        with Session(self.engine) as session, session.begin():
            held = session.scalars(select(RunRow).where(RunRow.run_key == run_key)).one_or_none()
            own = None if job_id is None else _unsaved_of_job(session, job_id)
            if held is not None:
                if own is not None:
                    session.delete(own)
                return _indexed(session, held)
            taker = own
            if taker is None and request_key is not None:
                taker = _waiting_on(session, request_key)
            if taker is None:
                taker = RunRow(
                    origin=RunOrigin.MANUAL,
                    job_id=job_id,
                    request_key=request_key,
                    created_at=run.saved_at,
                )
            _hold_the_record(session, taker, run)
            session.add(taker)
            session.flush()
            return _indexed(session, taker)

    def by_id(self, run_id: str) -> RunWithMetrics | None:
        with Session(reading(self.engine)) as session:
            row = session.get(RunRow, run_id, options=[undefer(RunRow.metrics_json)])
            if row is None:
                return None
            eras = () if row.fidelity_eras_json is None else row.fidelity_eras_json
            return RunWithMetrics(
                **dict(_indexed(session, row)),
                metrics=None
                if row.metrics_json is None
                else Metrics.model_validate(row.metrics_json),
                fidelity_eras=tuple(FidelityEra.model_validate(era) for era in eras),
                warnings=() if row.warnings_json is None else tuple(row.warnings_json),
            )

    def newest(self, limit: int) -> tuple[IndexedRun, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.scalars(
                select(RunRow).order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(limit)
            ).all()
            return tuple(_indexed(session, row) for row in rows)


def index_runs(session: Session, runs: Sequence[Run]) -> int:
    """A row for each of `runs`, saved folders read before the session's write lock, whose run
    key no row holds, in the session's transaction; how many it added."""
    held = set(session.scalars(select(RunRow.run_key).where(RunRow.run_key.is_not(None))))
    added = 0
    for run in runs:
        if run.hash in held:
            continue
        row = RunRow(origin=RunOrigin.MANUAL, created_at=run.saved_at)
        _hold_the_record(session, row, run)
        session.add(row)
        added += 1
    session.flush()
    return added


def _waiting_on(session: Session, request_key: str) -> RunRow | None:
    """The oldest unsaved run of `request_key` whose job is queued or running and not asked to
    stop, which a submission of the same request is."""
    return session.scalars(
        select(RunRow)
        .join(JobRow, RunRow.job_id == JobRow.id)
        .where(
            RunRow.request_key == request_key,
            RunRow.run_key.is_(None),
            JobRow.status.in_(ACTIVE),
            JobRow.cancel_requested_at.is_(None),
        )
        .order_by(RunRow.created_at, RunRow.id)
        .limit(1)
    ).first()


def _unsaved_of_job(session: Session, job_id: str) -> RunRow | None:
    return session.scalars(
        select(RunRow).where(RunRow.job_id == job_id, RunRow.run_key.is_(None))
    ).one_or_none()


def _hold_the_record(session: Session, row: RunRow, run: Run) -> None:
    """Give `row` the run key of `run` and the columns of its record: the strategy version it
    names, where the index holds it, its parameters, its window, its settings, its metrics, its
    fidelity eras, and its warnings. The version is read before the row changes, so that no
    flush writes it half changed: a saved row takes one update, the last its triggers allow."""
    record = run.record
    pin = record.strategy.saved_version
    version_id = _version_id(session, pin)
    row.run_key = run.hash
    row.strategy_version_id = version_id
    row.parameters_json = {} if pin is None else pin.model_dump(mode="json")["parameters"]
    row.window_start, row.window_end = record.window.start, record.window.end
    row.settings_json = record.config.model_dump(mode="json")
    row.metrics_json = record.metrics.model_dump(mode="json")
    row.fidelity_eras_json = [era.model_dump(mode="json") for era in record.fidelity_eras]
    row.warnings_json = list(record.warnings)


def _version_id(session: Session, pin: StrategyPin | None) -> str | None:
    """The row of the strategy version `pin` names, by its strategy's name, its number, and its
    hash; None for a run without one, or of a version the index does not hold."""
    if pin is None:
        return None
    return session.scalars(
        select(StrategyVersionRow.id)
        .join(StrategyRow, StrategyVersionRow.strategy_id == StrategyRow.id)
        .where(
            StrategyRow.name == pin.name,
            StrategyVersionRow.version_no == pin.version,
            StrategyVersionRow.content_hash == pin.hash,
        )
    ).one_or_none()


def _indexed(session: Session, row: RunRow) -> IndexedRun:
    job = None if row.job_id is None else session.get(JobRow, row.job_id)
    status, progress, message, error = _state(row, job)
    return IndexedRun(
        id=row.id,
        created_at=row.created_at,
        origin=row.origin,
        strategy=_run_strategy(session, row.strategy_version_id),
        parameters=row.parameters_json,
        start=row.window_start,
        end=row.window_end,
        settings=AppliedRunConfig.model_validate(row.settings_json),
        status=status,
        progress=progress,
        message=message,
        error=error,
        job_id=row.job_id,
        run_key=row.run_key,
    )


def _state(row: RunRow, job: JobRow | None) -> tuple[JobStatus, float, str | None, str | None]:
    """A run's status, progress, message, and error: `succeeded` once its folder is indexed,
    else its job's (`fefat_app.runs`)."""
    if row.run_key is not None:
        return JobStatus.SUCCEEDED, 100.0, None, None
    if job is None:
        raise ValueError(f"Expected the job of the unsaved run {row.id}, got none.")
    return job.status, job.progress, job.message, job.error


def _run_strategy(session: Session, version_id: str | None) -> RunStrategy | None:
    if version_id is None:
        return None
    version = session.get_one(StrategyVersionRow, version_id)
    strategy = session.get_one(StrategyRow, version.strategy_id)
    return RunStrategy(
        strategy_id=strategy.id,
        name=strategy.name,
        version_id=version.id,
        version=version.version_no,
    )
