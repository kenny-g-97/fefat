"""A saved run's reproduction over the API (step 5.10, D-93, D-126): a `reproduce` job, its
payload a `BacktestSpec` that names the run it makes again, built from the version, the window,
and the settings the run's record pins, which the executor's `backtest` kind runs, since the
strategy is built from its version's code there (D-91); the run of the same reproduction queued or
running is that job."""

from fefat.backtest import RunConfig
from fefat_app.execution import BacktestSpec
from fefat_app.job_models import Job, JobKind
from fefat_app.runs import RequestedRun, ResultsRefusedError
from fefat_app.services.code_runs import BACKTEST_LIMITS
from fefat_app.services.jobs import Jobs
from fefat_app.services.runs import Runs


def reproduction_of(runs: Runs, jobs: Jobs, run: str) -> Job:
    """The `reproduce` job of the saved run `run`, queued, or the one queued or running and not
    asked to stop: refused as `Runs.reading` refuses it, and with `ResultsRefusedError` for a run
    of a strategy built in a notebook, whose strategy FEAT cannot build again."""
    with runs.reading(run) as opened:
        record = opened.record
    pin = record.strategy.saved_version
    if pin is None:
        raise ResultsRefusedError(
            f"Expected a run of a saved strategy version, got run {opened.hash[:12]} of a "
            "strategy built in a notebook, which FEAT cannot build again: reproduce it in the "
            "notebook with ff.backtest.reproduce."
        )
    requested = RequestedRun(
        strategy=pin.name,
        version=pin.version,
        hash=pin.hash,
        parameters=pin.parameters,
        start=record.window.start,
        end=record.window.end,
        settings=RunConfig.model_validate(record.config.model_dump()),
    )
    spec = BacktestSpec(run=requested, limits=BACKTEST_LIMITS, reproduces=opened.hash)
    return jobs.start_unless_under_way(JobKind.REPRODUCE, spec.model_dump(mode="json"))
