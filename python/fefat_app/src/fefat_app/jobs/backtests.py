"""A backtest as a job (step 5.3, `01-architecture.md` section 6): its payload a `BacktestSpec`, run
by the worker's executor as the other executions of the trader's code are
(`fefat_app.jobs.executions`), each stage the runner reports a `progress` event of the job's
stream, a request to stop read each second; then the run folder the runner saved is indexed into
the run's row (`fefat_app.ports.RunRecords.saved`), tried again while a writer holds the database
past its busy timeout, as the job's end is, and the job's result names the run. No report follows
the save, since one would read a request to stop and cancel the job of a run already saved."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.exc import OperationalError

from fefat_app.execution import BacktestOutput, BacktestSpec
from fefat_app.jobs.executions import executed
from fefat_app.jobs.progress import JobProgress
from fefat_app.ports import Executor, RunRecords
from fefat_app.runs import IndexedRun

SAVE_TRIES = 12
"""How many times a job indexes its run while a writer holds the database past its busy timeout
of five seconds: a minute, while the heartbeat keeps the lease."""


def run_backtest(
    executor: Executor, runs: RunRecords, payload: Mapping[str, Any], progress: JobProgress
) -> dict[str, Any]:
    """Run the backtest of `payload`, reporting through `progress`, and index its run; the run's
    row and run key, or the error the job ends with."""
    output = executed(executor, BacktestSpec, payload, progress).output
    if not isinstance(output, BacktestOutput):
        raise ValueError(f"Expected the output of a backtest, got that of a {output.kind}.")
    run = _saved(runs, output.run_key, progress.job_id)
    return {"run_id": run.id, "run_key": run.run_key}


def _saved(runs: RunRecords, run_key: str, job_id: str) -> IndexedRun:
    """The run of `run_key`, indexed into the row of the job `job_id`; the last try's refusal by
    a busy database comes through."""
    for _ in range(SAVE_TRIES - 1):
        try:
            return runs.saved(run_key, job_id=job_id)
        except OperationalError:
            continue
    return runs.saved(run_key, job_id=job_id)
