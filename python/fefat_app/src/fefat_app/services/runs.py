"""The runs over the API (step 5.3, D-93, ADR-0020): a backtest of a saved strategy version asked
for, answered with the run its request finds saved, or queued as a `backtest` job; a page of the
runs (step 5.6); a run with its metrics; a run's job cancelled; what a run would read before
anything runs; and a stress, the same run at more ticks of slippage. A submission indexes the
library first, so that a version a notebook saved is found and a library the index cannot follow
refuses it before anything runs, checks the version's file as indexed, and looks the run up in
the executor (`fefat_app.services.code_runs`), which builds the strategy from the version's code
there, never in the server; the run's row and its queued job are made in one transaction by the
runs' records, which the dispatcher then runs."""

from dataclasses import dataclass
from datetime import date

from pydantic import JsonValue

from fefat.backtest import RunConfig
from fefat.backtest.estimates import estimated
from fefat.config import FefatPaths
from fefat.market.schema import Timeframe
from fefat.reference.settings import SlippageTicks
from fefat_app.execution import BacktestSpec
from fefat_app.job_models import JobStatus
from fefat_app.library import (
    IndexedStrategy,
    IndexedStrategyVersion,
)
from fefat_app.ports import Clock, Executor, LibraryIndex, RunRecords
from fefat_app.runs import (
    EstimateRefusedError,
    IndexedRun,
    NewRun,
    NoDataToEstimate,
    NoSuchRunError,
    RequestedRun,
    RunEstimate,
    RunEstimated,
    RunPage,
    RunWithMetrics,
    SavedRunFound,
    StressedRuns,
    SubmittedRun,
)
from fefat_app.services.code_runs import BACKTEST_LIMITS, looked_up_run
from fefat_app.services.jobs import MAX_ATTEMPTS, Jobs
from fefat_app.services.strategies import NoSuchStrategyError, read_as_indexed

RUNS_PER_PAGE = 50
"""How many runs a page of the list holds unless it asks for fewer."""


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
class RunsAsked:
    """A page of the runs: a strategy's name, whether a run names a saved version at all, a
    status, where the page starts, and how many runs it holds."""

    strategy: str | None = None
    versioned: bool | None = None
    status: JobStatus | None = None
    cursor: str | None = None
    limit: int = RUNS_PER_PAGE


@dataclass(frozen=True)
class Runs:
    """The runs in `records`, the versions of the library in `index` with their files under
    `paths`, the trader's code run by `executor`, and the backtests' jobs given to the dispatcher
    through `jobs` (module docstring)."""

    records: RunRecords
    index: LibraryIndex
    executor: Executor
    jobs: Jobs
    paths: FefatPaths
    clock: Clock

    def submit(self, asked: RunAsked) -> IndexedRun:
        """The run `asked` names: the run its request finds saved, indexed where it was not, or
        the run of the same request waiting on its job, or a new run with its queued job;
        refused with `NoSuchStrategyError`, `LibraryRefusedError`, or `CodeRefusedError`."""
        self.index.refresh()
        strategy, version = self._version(asked.strategy_version_id)
        read_as_indexed(self.paths.strategies_dir, strategy.name, version)
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
        submitted = self.jobs.queued_by(
            lambda: self.records.submitted(new, MAX_ATTEMPTS, self.clock())
        )
        if submitted.queued_job_id is not None:
            self.jobs.submit(submitted.queued_job_id)
        return submitted.run

    def stressed(self, asked: RunAsked) -> StressedRuns:
        """The run `asked` names, then the same at one and at two more ticks of slippage on
        market and stop orders, each a run of its own (D-29), each answered as `submit` answers;
        the base's applied slippage is what they add to. Refused as `submit` is."""
        base = self.submit(asked)
        once = base.settings.at_one_more_tick()
        twice = once.at_one_more_tick()
        return StressedRuns(
            runs=(
                base,
                self.submit(_at_slippage(asked, once.slippage_ticks)),
                self.submit(_at_slippage(asked, twice.slippage_ticks)),
            )
        )

    def page(self, asked: RunsAsked) -> RunPage:
        """A page of the runs, newest first, a list's first page finding the saved folders no
        row holds (step 5.6)."""
        if asked.cursor is None:
            self.index.index_saved_runs()
        return self.records.page(
            strategy=asked.strategy,
            versioned=asked.versioned,
            status=asked.status,
            cursor=asked.cursor,
            limit=asked.limit,
        )

    def by_id(self, run: str) -> RunWithMetrics:
        """The run of the id or the run key `run` with its metrics once saved;
        `NoSuchRunError` where there is none."""
        found = self.records.by_id(run)
        if found is None:
            raise NoSuchRunError(run)
        return found

    def cancel(self, run: str) -> RunWithMetrics:
        """Cancel the job of the run `run`, at once while queued, asked while it runs
        (`Jobs.cancel`); a saved run, or one whose job has ended, is given as it is."""
        found = self.by_id(run)
        if isinstance(found, SubmittedRun):
            self.jobs.cancel(found.job_id)
        return self.by_id(run)

    def estimate(
        self, version_id: str, start: date | None, end: date | None, settings: RunConfig
    ) -> RunEstimate:
        """What a run of the version `version_id` would read from `start` to `end` under
        `settings`, before anything runs and without its code (`fefat.backtest.estimates`);
        refused with `NoSuchStrategyError`, `LibraryRefusedError`, or `EstimateRefusedError`."""
        self.index.refresh()
        _, version = self._version(version_id)
        try:
            found = estimated(
                version.instrument,
                Timeframe.parse(version.timeframe),
                start,
                end,
                settings,
                self.paths,
            )
        except ValueError as refused:
            raise EstimateRefusedError(str(refused)) from refused
        if found is None:
            return NoDataToEstimate(instrument=version.instrument, timeframe=version.timeframe)
        return RunEstimated(
            **dict(found), instrument=version.instrument, timeframe=version.timeframe
        )

    def _version(self, version_id: str) -> tuple[IndexedStrategy, IndexedStrategyVersion]:
        for strategy in self.index.strategies():
            for version in strategy.versions:
                if version.id == version_id:
                    return strategy, version
        raise NoSuchStrategyError(
            f"Expected the id of a saved strategy version, got {version_id!r}, which names none."
        )


def _at_slippage(asked: RunAsked, ticks: SlippageTicks) -> RunAsked:
    settings = asked.settings.model_copy(update={"slippage_ticks": ticks})
    return RunAsked(
        strategy_version_id=asked.strategy_version_id,
        parameters=asked.parameters,
        start=asked.start,
        end=asked.end,
        settings=settings,
    )
