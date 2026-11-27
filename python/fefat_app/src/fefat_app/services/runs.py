"""The runs over the API (step 5.3, D-93, ADR-0020): a backtest of a saved strategy version asked
for, answered with the run its request finds saved, or queued as a `backtest` job; a page of the
runs (step 5.6); a run with its metrics; a run's job cancelled; what a run would read before
anything runs; and a stress, the same run at more ticks of slippage. A submission indexes the
library first, so that a version a notebook saved is found and a library the index cannot follow
refuses it before anything runs, checks the version's file as indexed, and looks the run up in
the executor (`fefat_app.services.code_runs`), which builds the strategy from the version's code
there, never in the server; the run's row and its queued job are made in one transaction by the
runs' records, which the dispatcher then runs."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from polars.exceptions import PolarsError
from pydantic import JsonValue

from fefat.backtest import (
    MarketExposure,
    MonteCarlo,
    ResultsBySide,
    Run,
    RunConfig,
    TooFewTrades,
    TradeDistributions,
    equity_curve,
    market_exposure,
    monte_carlo,
    results_by_side,
    trade_distributions,
)
from fefat.backtest.estimates import estimated, held_instruments
from fefat.backtest.saved_runs import saved_run
from fefat.config import FefatPaths
from fefat.market.engine_units import money_in_units
from fefat.market.schema import Timeframe
from fefat.reference.settings import SlippageTicks
from fefat_app.execution import BacktestSpec
from fefat_app.job_models import ACTIVE, JobStatus
from fefat_app.library import (
    IndexedStrategy,
    IndexedStrategyVersion,
)
from fefat_app.ports import Clock, Executor, LibraryIndex, RunRecords
from fefat_app.runs import (
    EquityCurve,
    EstimateRefusedError,
    IndexedRun,
    NewRun,
    NoDataToEstimate,
    NoSuchRunError,
    RequestedRun,
    ResultsRefusedError,
    RunEstimate,
    RunEstimated,
    RunPage,
    RunStatistics,
    SavedRunFound,
    StressedRuns,
    SubmittedRun,
    UnreadableArtifactError,
)
from fefat_app.services.code_runs import BACKTEST_LIMITS, looked_up_run
from fefat_app.services.jobs import MAX_ATTEMPTS, Jobs
from fefat_app.services.strategies import NoSuchStrategyError, read_as_indexed

RUNS_PER_PAGE = 50
"""How many runs a page of the list holds unless it asks for fewer."""
_NANOSECONDS_A_SECOND = 1_000_000_000


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

    def submit_again(self, requested: RequestedRun) -> IndexedRun:
        """The run `requested`, as its job's payload holds it, asked for again as `submit` asks
        (step 5.19); `NoSuchStrategyError` where the library no longer holds that version as it
        ran."""
        return self.submit(
            RunAsked(
                strategy_version_id=self._version_as_it_ran(requested).id,
                parameters=dict(requested.parameters),
                start=requested.start,
                end=requested.end,
                settings=requested.settings,
            )
        )

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

    def by_id(self, run: str) -> IndexedRun:
        """The run of the id or the run key `run`; `NoSuchRunError` where there is none."""
        found = self.records.by_id(run)
        if found is None:
            raise NoSuchRunError(run)
        return found

    def cancel(self, run: str) -> IndexedRun:
        """Cancel the job of the run `run`, at once while queued, asked while it runs
        (`Jobs.cancel`); a saved run, or one whose job has ended, is given as it is."""
        found = self.by_id(run)
        if isinstance(found, SubmittedRun):
            self.jobs.cancel(found.job_id)
        return self.by_id(run)

    def statistics(self, run: str) -> RunStatistics:
        """What the record of the saved run `run` says of how it went (step 5.7), refused as
        `_opened` refuses."""
        opened = self._opened(run)
        record = opened.record
        return RunStatistics(
            currency=record.instrument.currency,
            pnl_share=opened.pnl_share,
            metrics=record.metrics,
            fidelity_eras=record.fidelity_eras,
            warnings=record.warnings,
            timeframe=str(record.strategy.spec["timeframe"]),
        )

    def equity_curve(self, run: str, max_points: int) -> EquityCurve:
        """The account of the saved run `run` in at most `max_points` points that keep its
        maximum drawdown (`ff.backtest.equity_curve`), refused as `_opened` refuses."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            curve = equity_curve(opened, max_points)
        return EquityCurve(
            capital=float(opened.config.capital),
            time=tuple((curve.get_column("ts") // _NANOSECONDS_A_SECOND).to_list()),
            equity=money_in_units(curve.get_column("equity")),
            drawdown=money_in_units(curve.get_column("drawdown")),
        )

    def distributions(self, run: str) -> TradeDistributions:
        """The trades of the saved run `run` as histograms (`ff.backtest.trade_distributions`),
        refused as `_opened` refuses."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            trades = opened.trades
        return trade_distributions(trades)

    def monte_carlo(
        self, run: str, paths: int, seed: int, max_points: int
    ) -> MonteCarlo | TooFewTrades:
        """`paths` walks of the trades of the saved run `run` drawn from `seed`, with a fan of at
        most `max_points` counts and each figure at every whole percent of the paths
        (`ff.backtest.monte_carlo`, steps 5.20 and 5.21), refused as `_opened` refuses."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            return monte_carlo(opened, paths, seed, max_points)

    def results_by_side(self, run: str) -> ResultsBySide:
        """The figures of the saved run `run` for all its trades, its long trades, and its short
        trades (`ff.backtest.results_by_side`, step 5.22), refused as `_opened` refuses."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            return results_by_side(opened)

    def market_exposure(self, run: str, max_points: int) -> MarketExposure:
        """How the days of the saved run `run` moved with one lot of its instrument held long,
        beside buy and hold, whose curve stands at the decisions an equity curve of `max_points`
        keeps (`ff.backtest.market_exposure`, step 5.23), refused as `_opened` refuses."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            return market_exposure(opened, max_points)

    @contextmanager
    def reading(self, run: str) -> Generator[Run]:
        """The folder of the saved run `run`, refused as `_opened` refuses, and what reading its
        files refuses in the block refused as `_results_read` refuses (step 5.8)."""
        opened = self._opened(run)
        with _results_read(opened.hash, self.paths):
            yield opened

    def _opened(self, run: str) -> Run:
        """The folder of the saved run `run`: `NoSuchRunError` where no run has that id or key,
        and `ResultsRefusedError` for a run not saved yet, a folder that is gone, and a folder
        this engine does not read."""
        found = self.by_id(run)
        if isinstance(found, SubmittedRun):
            what_next = (
                "its results come once it is saved"
                if found.status in ACTIVE
                else "it saved no results, so run the backtest again"
            )
            raise ResultsRefusedError(
                f"Expected a saved run, got run {found.id}, whose backtest job is {found.status}: "
                f"{what_next}."
            )
        with _results_read(found.run_key, self.paths):
            return saved_run(self.paths.runs_dir, found.run_key)

    def estimate(
        self, version_id: str, start: date | None, end: date | None, settings: RunConfig
    ) -> RunEstimate:
        """What a run of the version `version_id`, on the instrument `settings` names or else its
        own (D-114), would read from `start` to `end` under `settings`, before anything runs and
        without its code (`fefat.backtest.estimates`), with the instruments the store holds;
        refused with `NoSuchStrategyError`, `LibraryRefusedError`, or `EstimateRefusedError`."""
        self.index.refresh()
        _, version = self._version(version_id)
        traded = version.instrument if settings.instrument is None else settings.instrument
        try:
            instruments = held_instruments(self.paths)
            found = estimated(
                traded, Timeframe.parse(version.timeframe), start, end, settings, self.paths
            )
        except ValueError as refused:
            raise EstimateRefusedError(str(refused)) from refused
        if found is None:
            return NoDataToEstimate(
                instrument=traded, timeframe=version.timeframe, instruments=instruments
            )
        return RunEstimated(
            **dict(found), instrument=traded, timeframe=version.timeframe, instruments=instruments
        )

    def _version(self, version_id: str) -> tuple[IndexedStrategy, IndexedStrategyVersion]:
        for strategy in self.index.strategies():
            for version in strategy.versions:
                if version.id == version_id:
                    return strategy, version
        raise NoSuchStrategyError(
            f"Expected the id of a saved strategy version, got {version_id!r}, which names none."
        )

    def _version_as_it_ran(self, requested: RequestedRun) -> IndexedStrategyVersion:
        ran = (requested.strategy, requested.version, requested.hash)
        for strategy in self.index.strategies():
            for version in strategy.versions:
                if (strategy.name, version.version, version.hash) == ran:
                    return version
        raise NoSuchStrategyError(
            f"Version {requested.version} of the strategy {requested.strategy} is no longer held "
            "as it ran: its file was removed or changed. Run the strategy from its page."
        )


@contextmanager
def _results_read(run_key: str, paths: FefatPaths) -> Generator[None]:
    """What reading the saved run `run_key`'s files refuses, as `ResultsRefusedError`, in words
    that name no folder of this PC: a file gone or damaged (`_unreadable_folder`), or the SDK's
    words for a folder this engine does not read."""
    folder = paths.runs_dir / run_key
    run = f"run {run_key[:12]}"
    try:
        yield
    except (FileNotFoundError, PolarsError, UnreadableArtifactError) as unreadable:
        raise ResultsRefusedError(_unreadable_folder(folder, paths.home, run)) from unreadable
    except ValueError as refused:
        raise ResultsRefusedError(str(refused).replace(str(folder), run)) from refused


def _unreadable_folder(folder: Path, home: Path, run: str) -> str:
    """What to do about the folder of `run`: a new run writes a folder that is gone, while it
    opens one it finds saved, or cannot write over what is left of one, so that an incomplete or
    damaged folder must be deleted first."""
    if not folder.exists():
        return (
            f"The folder of {run} is gone from FEAT's workspace, so its results cannot be read. "
            "Run the backtest again."
        )
    return (
        f"The folder of {run} is incomplete or damaged, so its results cannot be read. Delete "
        f"{folder.relative_to(home).as_posix()} in FEAT's home folder, then run the backtest again."
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
