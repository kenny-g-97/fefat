"""A backtest as a job (step 5.3, `01-architecture.md` section 6): its payload a `BacktestSpec`, run
by the worker's executor as the other executions of the trader's code are
(`fefat_app.jobs.executions`), each stage the runner reports a `progress` event of the job's
stream, a request to stop read each second; then the run folder the runner saved is indexed into
the run's row (`fefat_app.ports.RunRecords.saved`), tried again while a writer holds the database
past its busy timeout, as the job's end is, and the job's result names the run.

The runner's last report, at 100, says its run is saved: a request to stop from then on no longer
stops the job, which indexes the run and succeeds, rather than ending `cancelled` with its folder
unindexed (the step review). The job reports nothing after the save."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from fefat_app.execution import BacktestOutput, BacktestSpec, ExecutionProgress
from fefat_app.jobs.executions import advancing, executed
from fefat_app.jobs.progress import JobCancelledError, JobProgress, tried_while_busy
from fefat_app.ports import Executor, RunRecords

SAVED_PERCENT = 100.0
"""The percent of the runner's report once its run is saved, written or opened."""


def run_backtest(
    executor: Executor, runs: RunRecords, payload: Mapping[str, Any], progress: JobProgress
) -> dict[str, Any]:
    """Run the backtest of `payload`, reporting through `progress`, and index its run; the run's
    row and run key, or the error the job ends with."""
    spec = BacktestSpec.model_validate(payload)
    following = _UntilSaved(progress)
    output = executed(executor, spec, following.report, following.check).output
    if not isinstance(output, BacktestOutput):
        raise ValueError(f"Expected the output of a backtest, got that of a {output.kind}.")
    run = tried_while_busy(partial(runs.saved, output.run_key, job_id=progress.job_id))
    return {"run_id": run.id, "run_key": run.run_key}


@dataclass
class _UntilSaved:
    """A backtest's reports and checks, which stop it where its job was asked to stop until the
    runner reports its run saved, and never after (module docstring)."""

    progress: JobProgress
    saved: bool = False

    def report(self, reported: ExecutionProgress) -> None:
        try:
            advancing(self.progress)(reported)
        except JobCancelledError:
            if reported.percent < SAVED_PERCENT:
                raise
        if reported.percent >= SAVED_PERCENT:
            self.saved = True

    def check(self) -> None:
        if not self.saved:
            self.progress.check()
