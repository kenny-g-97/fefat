"""The runs over the API (step 5.3, D-93, ADR-0020): a backtest of a saved strategy version asked
for, answered with the run its request finds saved, or queued as a `backtest` job; the newest
runs; a run with its metrics; and a run's job cancelled. A submission indexes the library first,
so that a version a notebook saved is found and a library the index cannot follow refuses it
before anything runs, checks the version's file as indexed, and looks the run up in the executor
(`fefat_app.services.code_runs`), which builds the strategy from the version's code there, never
in the server; the run's row and its queued job are made in one transaction by the runs'
records, which the dispatcher then runs."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import JsonValue

from fefat.backtest import RunConfig
from fefat_app.execution import BacktestSpec
from fefat_app.library import (
    IndexedStrategy,
    IndexedStrategyVersion,
)
from fefat_app.ports import Clock, Executor, LibraryIndex, RunRecords
from fefat_app.runs import (
    IndexedRun,
    NewRun,
    NoSuchRunError,
    RequestedRun,
    RunWithMetrics,
    SavedRunFound,
)
from fefat_app.services.code_runs import BACKTEST_LIMITS, looked_up_run
from fefat_app.services.jobs import MAX_ATTEMPTS, Jobs
from fefat_app.services.strategies import NoSuchStrategyError, read_as_indexed

NEWEST_RUNS = 100
"""How many of the newest runs the list holds; filters and paging come with the runs' page
(step 5.6)."""


@dataclass(frozen=True)
class RunAsked:
    """A backtest asked for: the id of a saved strategy version's row, its parameters, the trade
    dates from `start` to `end`, and its settings, each left out taking the SDK's default."""

    strategy_version_id: str
    parameters: dict[str, JsonValue]
    start: date
    end: date
    settings: RunConfig


@dataclass(frozen=True)
class Runs:
    """The runs in `records`, the versions of the library in `index` with their files in
    `strategies_dir`, the trader's code run by `executor`, and the backtests' jobs given to the
    dispatcher through `jobs` (module docstring)."""

    records: RunRecords
    index: LibraryIndex
    executor: Executor
    jobs: Jobs
    strategies_dir: Path
    clock: Clock

    def submit(self, asked: RunAsked) -> IndexedRun:
        """The run `asked` names: the run its request finds saved, indexed where it was not, or
        the run of the same request waiting on its job, or a new run with its queued job;
        refused with `NoSuchStrategyError`, `LibraryRefusedError`, or `CodeRefusedError`."""
        self.index.refresh()
        strategy, version = self._version(asked.strategy_version_id)
        read_as_indexed(self.strategies_dir, strategy.name, version)
        requested = RequestedRun(
            strategy=strategy.name,
            version=version.version,
            hash=version.hash,
            parameters=asked.parameters,
            start=asked.start,
            end=asked.end,
            settings=asked.settings,
        )
        answer = looked_up_run(self.executor, requested)
        if isinstance(answer, SavedRunFound):
            return self.records.saved(answer.run_key, request_key=answer.request_key)
        new = NewRun(
            strategy_version_id=version.id,
            payload=BacktestSpec(run=requested, limits=BACKTEST_LIMITS).model_dump(mode="json"),
            parameters=answer.parameters,
            start=asked.start,
            end=asked.end,
            settings=answer.settings,
            request_key=answer.request_key,
        )
        submitted = self.records.submitted(new, MAX_ATTEMPTS, self.clock())
        if submitted.queued_job_id is not None:
            self.jobs.submit(submitted.queued_job_id)
        return submitted.run

    def newest(self) -> tuple[IndexedRun, ...]:
        """The newest runs, newest first, without their metrics."""
        return self.records.newest(NEWEST_RUNS)

    def by_id(self, run_id: str) -> RunWithMetrics:
        """The run `run_id` with its metrics once saved; `NoSuchRunError` where there is none."""
        run = self.records.by_id(run_id)
        if run is None:
            raise NoSuchRunError(run_id)
        return run

    def cancel(self, run_id: str) -> RunWithMetrics:
        """Cancel the job of the run `run_id`, at once while queued, asked while it runs
        (`Jobs.cancel`); a saved run, or one whose job has ended, is given as it is."""
        run = self.by_id(run_id)
        if run.run_key is None and run.job_id is not None:
            self.jobs.cancel(run.job_id)
        return self.by_id(run_id)

    def _version(self, version_id: str) -> tuple[IndexedStrategy, IndexedStrategyVersion]:
        for strategy in self.index.strategies():
            for version in strategy.versions:
                if version.id == version_id:
                    return strategy, version
        raise NoSuchStrategyError(
            f"Expected the id of a saved strategy version, got {version_id!r}, which names none."
        )
