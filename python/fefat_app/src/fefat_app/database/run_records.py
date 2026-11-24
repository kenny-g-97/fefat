"""The runs' records over the app's database (step 5.3, `fefat_app.ports.RunRecords`, ADR-0020):
the `runs` table, a row for each backtest asked for through the API, with its queued `backtest`
job until its folder is saved, then the index of the folder, `runs/<run key>/run.json`, which
stays the record; and, through `index_runs`, a row for each saved folder no row holds, which
`fefat db import-workspace` and the lists find (step 5.6). Each call is a transaction of its own
(`fefat_app.database.schema`); a folder's record is read through the SDK before the write lock is
taken, so that no writer waits on a file read. A row's columns, once its run key is set, are
those of its folder's record, whatever its submission asked, so that the index holds the folders
as `--rebuild` would. A page of the list is one joined select, which takes four paths of each
run's metrics rather than their whole document."""

import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, Engine, Row, Select, and_, func, or_, select
from sqlalchemy.orm import Session, undefer

from fefat.backtest import Run
from fefat.backtest.run_config import AppliedRunConfig
from fefat.backtest.saved_runs import saved_run
from fefat.config import FefatPaths
from fefat.market.fees import CryptoFee, FuturesFee, fee_in_force, tables_pricing
from fefat.market.instruments import Currency, InstrumentTable
from fefat.market.saved_instruments import instrument_table
from fefat.strategy import StrategyPin
from fefat_app.database.job_records import queued_job
from fefat_app.database.models import JobRow, RunRow, StrategyRow, StrategyVersionRow
from fefat_app.database.schema import reading
from fefat_app.job_models import ACTIVE, JobKind, JobStatus
from fefat_app.runs import (
    IndexedRun,
    KeyMetrics,
    NewRun,
    RunCursorError,
    RunOrigin,
    RunPage,
    RunStrategy,
    SavedRun,
    Submitted,
    SubmittedRun,
)

type _PageSelect = Select[RunRow, JobRow, StrategyVersionRow, StrategyRow, Any, Any, Any, Any]
"""A page's select: a run with its job, its version, its strategy, each None for a run without
one (outer joins), and four paths of its metrics."""
type _PageRow = Row[RunRow, JobRow, StrategyVersionRow, StrategyRow, Any, Any, Any, Any]

_RUN_KEY = re.compile(r"[0-9a-f]{64}")
_CURSOR_PARTS = "|"
_PNL = func.json_extract(RunRow.metrics_json, "$.pnl")
_TRADES = func.json_extract(RunRow.metrics_json, "$.trades.trades")
_MAX_DRAWDOWN = func.json_extract(RunRow.metrics_json, "$.drawdown.max_drawdown")
_VERDICT = func.json_extract(RunRow.metrics_json, "$.robustness.verdict")


@dataclass(frozen=True)
class RunTables:
    """`RunRecords` in the tables of `engine`'s database, over the run folders under `paths`."""

    engine: Engine
    paths: FefatPaths

    def submitted(self, new: NewRun, max_attempts: int, now: datetime) -> Submitted:
        instruments = self._instruments()
        with Session(self.engine) as session, session.begin():
            waiting = None if new.request_key is None else _waiting_on(session, new.request_key)
            if waiting is not None:
                return Submitted(
                    run=_submitted_row(session, waiting, instruments), queued_job_id=None
                )
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
            return Submitted(run=_submitted_row(session, row, instruments), queued_job_id=job.id)

    def saved(
        self, run_key: str, *, job_id: str | None = None, request_key: str | None = None
    ) -> SavedRun:
        run = saved_run(self.paths.runs_dir, run_key)
        instruments = self._instruments()
        with Session(self.engine) as session, session.begin():
            held = session.scalars(select(RunRow).where(RunRow.run_key == run_key)).one_or_none()
            own = None if job_id is None else _unsaved_of_job(session, job_id)
            if held is not None:
                if own is not None:
                    session.delete(own)
                return _saved_row(session, held, instruments)
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
            return _saved_row(session, taker, instruments)

    def by_id(self, run: str) -> SubmittedRun | SavedRun | None:
        named = RunRow.run_key == run if _RUN_KEY.fullmatch(run) else RunRow.id == run
        instruments = self._instruments()
        with Session(reading(self.engine)) as session:
            row = session.scalars(
                select(RunRow).where(named).options(undefer(RunRow.metrics_json))
            ).one_or_none()
            if row is None:
                return None
            if row.run_key is None:
                return _submitted_row(session, row, instruments)
            return _saved_row(session, row, instruments)

    def page(
        self,
        *,
        strategy: str | None,
        versioned: bool | None,
        status: JobStatus | None,
        cursor: str | None,
        limit: int,
    ) -> RunPage:
        after = None if cursor is None else _parsed_cursor(cursor)
        query = _page_query(strategy, versioned, status, after).limit(limit + 1)
        instruments = self._instruments()
        with Session(reading(self.engine)) as session:
            rows = session.execute(query).all()
            shown = rows[:limit]
            more = len(rows) > limit
            last: RunRow | None = shown[-1][0] if more else None
            return RunPage(
                runs=tuple(_listed(row, instruments) for row in shown),
                next_cursor=None if last is None else _cursor_of(last),
            )

    def _instruments(self) -> InstrumentTable:
        """The instruments a run's row may trade, read once a call: the static table's and those
        saved in the data folder."""
        return instrument_table(self.paths.data_dir)


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


def _page_query(
    strategy: str | None,
    versioned: bool | None,
    status: JobStatus | None,
    after: tuple[datetime, str] | None,
) -> _PageSelect:
    """The runs that the filters keep, newest first, after `after`'s instant and id, each with
    its job, its version, its strategy, and four paths of its metrics. The cursor compares
    column by column, so that its instant binds through `UtcInstant` as the column's text; a
    comparison of row values binds it in SQLite's own form and skips the rest of its day."""
    query = (
        select(
            RunRow, JobRow, StrategyVersionRow, StrategyRow, _PNL, _TRADES, _MAX_DRAWDOWN, _VERDICT
        )
        .outerjoin(JobRow, RunRow.job_id == JobRow.id)
        .outerjoin(StrategyVersionRow, RunRow.strategy_version_id == StrategyVersionRow.id)
        .outerjoin(StrategyRow, StrategyVersionRow.strategy_id == StrategyRow.id)
        .order_by(RunRow.created_at.desc(), RunRow.id.desc())
    )
    kept: list[ColumnElement[bool]] = []
    if strategy is not None:
        kept.append(StrategyRow.name == strategy)
    if versioned is not None:
        names = RunRow.strategy_version_id
        kept.append(names.is_not(None) if versioned else names.is_(None))
    if status is JobStatus.SUCCEEDED:
        kept.append(RunRow.run_key.is_not(None))
    elif status is not None:
        kept.extend((RunRow.run_key.is_(None), JobRow.status == status))
    if after is not None:
        instant, run_id = after
        kept.append(
            or_(
                RunRow.created_at < instant,
                and_(RunRow.created_at == instant, RunRow.id < run_id),
            )
        )
    return query.where(*kept)


def _cursor_of(row: RunRow) -> str:
    """The cursor of the page after `row`: its instant and its id, opaque to a client."""
    instant = row.created_at.astimezone(UTC).isoformat(timespec="microseconds")
    return urlsafe_b64encode(f"{instant}{_CURSOR_PARTS}{row.id}".encode()).decode()


def _parsed_cursor(cursor: str) -> tuple[datetime, str]:
    """The instant in UTC and the id `cursor` holds, refused where the list did not give it, as
    an instant with no offset, or one UTC cannot write."""
    try:
        text = urlsafe_b64decode(cursor.encode()).decode()
        instant, run_id = text.split(_CURSOR_PARTS)
        created_at = datetime.fromisoformat(instant)
        in_utc = None if created_at.tzinfo is None else created_at.astimezone(UTC)
    except (ValueError, OverflowError) as unreadable:
        raise RunCursorError(cursor) from unreadable
    if in_utc is None:
        raise RunCursorError(cursor)
    return in_utc, run_id


def _listed(row: _PageRow, instruments: InstrumentTable) -> IndexedRun:
    """A run of a page, from the page query's joined columns."""
    run = row[0]
    named = _named(row[2], row[3])
    if run.run_key is None:
        return _submitted(run, row[1], named, instruments)
    metrics = KeyMetrics(pnl=row[4], trades=row[5], max_drawdown=row[6], verdict=row[7])
    return _saved(run, named, metrics, instruments)


def _named(version: StrategyVersionRow | None, strategy: StrategyRow | None) -> RunStrategy | None:
    """What a page's outer joins give of a run's version, None for a run that names none."""
    return None if version is None or strategy is None else _strategy_of(version, strategy)


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
    traded = record.config.model_copy(update={"instrument": record.instrument.root})
    row.settings_json = traded.model_dump(mode="json")
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


def _submitted_row(session: Session, row: RunRow, instruments: InstrumentTable) -> SubmittedRun:
    job = None if row.job_id is None else session.get(JobRow, row.job_id)
    return _submitted(row, job, _run_strategy(session, row.strategy_version_id), instruments)


def _saved_row(session: Session, row: RunRow, instruments: InstrumentTable) -> SavedRun:
    strategy = _run_strategy(session, row.strategy_version_id)
    return _saved(row, strategy, _key_metrics(row), instruments)


def _head(
    row: RunRow, strategy: RunStrategy | None, instruments: InstrumentTable
) -> dict[str, Any]:
    """What a run's row holds in either state, its settings naming the instrument it trades: its
    own, or its version's for a row written before D-114; with the currency and the fee of that
    instrument (`_charges`)."""
    settings = AppliedRunConfig.model_validate(row.settings_json)
    if strategy is not None and settings.instrument is None:
        settings = settings.model_copy(update={"instrument": strategy.instrument})
    currency, fee = _charges(settings, row.window_end, instruments)
    return {
        "id": row.id,
        "created_at": row.created_at,
        "origin": row.origin,
        "parameters": row.parameters_json,
        "start": row.window_start,
        "end": row.window_end,
        "settings": settings,
        "currency": currency,
        "fee": fee,
        "strategy": strategy,
    }


def _charges(
    settings: AppliedRunConfig, last_day: date, instruments: InstrumentTable
) -> tuple[Currency | None, FuturesFee | CryptoFee | None]:
    """The currency the money of a run under `settings` counts in, and the fee its table charges
    the instrument it trades on `last_day`, as the engines charge it (D-117): neither where the
    settings name no instrument or one this store no longer defines, and no fee where the table
    does not price it, as a submission the lookup refuses since, so that no row fails a list."""
    root = settings.instrument
    if root is None or root not in instruments.roots():
        return None, None
    currency = instruments.get(root).currency
    if settings.fee_table not in tables_pricing(root):
        return currency, None
    # shortcut: a saved run's fee comes from today's tables, not its record's schedules; read the
    # record's once a table's figure is ever corrected in place (BACKLOG.md).
    return currency, fee_in_force(settings.fee_table, root, last_day)


def _submitted(
    row: RunRow, job: JobRow | None, strategy: RunStrategy | None, instruments: InstrumentTable
) -> SubmittedRun:
    """The unsaved run `row`, its status its job's (`fefat_app.runs`)."""
    if job is None:
        raise ValueError(f"Expected the job of the unsaved run {row.id}, got none.")
    if strategy is None:
        raise ValueError(f"Expected the strategy version of the unsaved run {row.id}, got none.")
    return SubmittedRun(
        **_head(row, strategy, instruments),
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
        job_id=job.id,
        cancel_requested_at=job.cancel_requested_at,
    )


def _saved(
    row: RunRow, strategy: RunStrategy | None, metrics: KeyMetrics, instruments: InstrumentTable
) -> SavedRun:
    """The saved run `row`, with what a list shows of how it went."""
    if row.run_key is None:
        raise ValueError(f"Expected the run key of the saved run {row.id}, got none.")
    return SavedRun(
        **_head(row, strategy, instruments),
        job_id=row.job_id,
        run_key=row.run_key,
        key_metrics=metrics,
    )


def _key_metrics(row: RunRow) -> KeyMetrics:
    """The four figures a list shows of the saved run `row`, from its metrics' document."""
    document: Mapping[str, Any] | None = row.metrics_json
    if document is None:
        raise ValueError(f"Expected the metrics of the saved run {row.id}, got none.")
    return KeyMetrics(
        pnl=document["pnl"],
        trades=document["trades"]["trades"],
        max_drawdown=document["drawdown"]["max_drawdown"],
        verdict=document["robustness"]["verdict"],
    )


def _run_strategy(session: Session, version_id: str | None) -> RunStrategy | None:
    if version_id is None:
        return None
    version = session.get_one(StrategyVersionRow, version_id)
    return _strategy_of(version, session.get_one(StrategyRow, version.strategy_id))


def _strategy_of(version: StrategyVersionRow, strategy: StrategyRow) -> RunStrategy:
    return RunStrategy(
        strategy_id=strategy.id,
        name=strategy.name,
        version_id=version.id,
        version=version.version_no,
        instrument=version.instrument,
        timeframe=version.timeframe,
    )
