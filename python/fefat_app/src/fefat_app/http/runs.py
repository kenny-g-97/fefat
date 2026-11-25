"""The runs' routes (step 5.3, `01-architecture.md` section 7, D-93), behind the login, a session's
or an API token's, over `fefat_app.services.runs`: `POST /v1/runs`, which answers 200 with the run
its request finds saved and 202 with a run whose `backtest` job is queued or running, whose
progress the job's stream gives (`GET /v1/streams/job:<job id>`); `POST /v1/runs/estimate`, what a
run would read, before anything runs, and `POST /v1/runs/stress`, a run and the same at more ticks
of slippage (step 5.6); `GET /v1/runs`, a page of the runs; `GET /v1/runs/{run}`, a run by its id
or its run key; `GET /v1/runs/{run}/stats`, `/equity`, and `/distribution`, a saved run's results,
read from its folder (step 5.7), and `/monte-carlo`, its trades drawn again (step 5.20); and
`POST /v1/runs/{run}/cancel`. A run's status is
`succeeded` once its folder is saved, its job's before; a job whose run proved saved under another
run's row names that row in its result, which a client then follows."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Self

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from fefat.backtest import RunConfig, TradeDistributions
from fefat.backtest.equity_curves import EQUITY_POINTS, FEWEST_POINTS
from fefat.backtest.resampling import MONTE_CARLO_PATHS, MONTE_CARLO_SEED, MonteCarloAnswer
from fefat.market.contracts import parse_contract_name
from fefat.market.fidelity import FidelityText
from fefat.strategy.spec import InstrumentRoot
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import CodeRefused, code_refusal_responses, problem_responses
from fefat_app.job_models import JobStatus
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import (
    EquityCurve,
    EstimateRefusedError,
    IndexedRun,
    NoSuchRunError,
    ResultsRefusedError,
    RunCursorError,
    RunEstimate,
    RunPage,
    RunStatistics,
    SavedRun,
    StressedRuns,
)
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.runs import RUNS_PER_PAGE, RunAsked, RunsAsked
from fefat_app.services.strategies import NoSuchStrategyError

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])

MOST_RUNS_PER_PAGE = 100
"""The most runs a page of the list holds."""
MOST_EQUITY_POINTS = 10_000
"""The most points of a run's equity a client can ask for."""
FEWEST_PATHS = 100
"""The fewest paths a client can ask a run's Monte Carlo to draw (step 5.20)."""
MOST_PATHS = 10_000
"""The most paths a client can ask a run's Monte Carlo to draw."""
MOST_SEED = 2**53 - 1
"""The largest seed a client can ask for: the largest whole number a browser's number holds
exactly, so that the seed an answer names reads back as the one drawn from."""
RunAddress = Annotated[
    str, Path(description="A run's id in the index, a UUIDv7, or its run key, 64 hex digits.")
]
FOUND_SAVED = {
    200: {
        "model": SavedRun,
        "description": "The run its request found saved, indexed where it was not: no job runs.",
    }
}


class RunSubmission(BaseModel):
    """A backtest of a saved strategy version: the id of the version's row, which
    `GET /v1/strategies` gives; its parameters, its defaults filling those left out; the trade
    dates from `start` to `end`; and its settings, each left out taking its default, which the
    run's answer gives with every default applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version_id: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    start: date
    end: date
    settings: RunConfig = Field(default_factory=RunConfig)

    @model_validator(mode="after")
    def _start_on_or_before_its_end(self) -> Self:
        if self.end < self.start:
            raise ValueError(
                f"Expected the start {self.start} on or before the end, got the end {self.end}."
            )
        return self

    def asked(self) -> RunAsked:
        """The run this submission asks for."""
        return RunAsked(
            strategy_version_id=self.strategy_version_id,
            parameters=self.parameters,
            start=self.start,
            end=self.end,
            settings=self.settings,
        )


class EstimateSettings(BaseModel):
    """The settings that change what a run reads, each left out taking the run's default: the
    finest data it fills on, the provider whose data it reads, the one contract it reads in
    place of the roll calendar's fronts, and the instrument it trades in place of the one its
    strategy names (D-114)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fidelity: FidelityText | None = None
    provider: str | None = None
    contract: str | None = None
    instrument: InstrumentRoot | None = None

    @field_validator("contract")
    @classmethod
    def _a_contract_name(cls, contract: str | None) -> str | None:
        if contract is not None:
            parse_contract_name(contract)
        return contract


class RunEstimateRequest(BaseModel):
    """What to estimate of a run of a saved strategy version: the id of the version's row; the
    trade dates, each left out meaning where the data starts or ends; and what the run reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version_id: str
    start: date | None = None
    end: date | None = None
    settings: EstimateSettings = Field(default_factory=EstimateSettings)

    @model_validator(mode="after")
    def _start_on_or_before_its_end(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(
                f"Expected the start {self.start} on or before the end, got the end {self.end}."
            )
        return self


@contextmanager
def _refusals() -> Generator[None]:
    """What the runs' service refuses, as the API answers it."""
    try:
        yield
    except CodeRefusedError as refused:
        raise CodeRefused(refused.line, str(refused)) from refused
    except EstimateRefusedError as refused:
        raise HTTPException(400, str(refused)) from refused
    except (NoSuchStrategyError, NoSuchRunError) as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except (LibraryRefusedError, ResultsRefusedError) as refused:
        raise HTTPException(409, str(refused)) from refused


@router.post(
    "/runs",
    status_code=202,
    responses={**FOUND_SAVED, **code_refusal_responses(401, 403, 404, 409, 422)},
)
def submit_run(
    request: RunSubmission, response: Response, container: ContainerDependency
) -> IndexedRun:
    """Backtest the version, the strategy built from its code in the executor: 200 with the run
    its request finds saved, else 202 with the run whose `backtest` job is queued, the run of
    the same request waiting already being that run; refused with 400 and the line of the code
    where the code gives no strategy, 404 where no version has the id, and 409 where the library
    holds files the index cannot follow."""
    with _refusals():
        run = container.runs.submit(request.asked())
    if isinstance(run, SavedRun):
        response.status_code = 200
    return run


@router.post("/runs/estimate", responses=problem_responses(400, 401, 403, 404, 409, 422))
def estimate_run(request: RunEstimateRequest, container: ContainerDependency) -> RunEstimate:
    """What a run of the version would read, before anything runs and without its code: what it
    can choose among, the settings it would apply, the trade dates held, and the sessions, bars,
    and ticks of the window; refused with 400 in the SDK's words, 404 where no version has the
    id, and 409 where the library holds files the index cannot follow."""
    with _refusals():
        return container.runs.estimate(
            request.strategy_version_id,
            request.start,
            request.end,
            RunConfig(
                fidelity=request.settings.fidelity,
                provider=request.settings.provider,
                contract=request.settings.contract,
                instrument=request.settings.instrument,
            ),
        )


@router.post(
    "/runs/stress",
    status_code=202,
    responses=code_refusal_responses(401, 403, 404, 409, 422),
)
def stress_run(request: RunSubmission, container: ContainerDependency) -> StressedRuns:
    """The run, then the same at one and at two more ticks of slippage on market and stop orders,
    each a run of its own, answered as `POST /v1/runs` answers it, and refused as it is."""
    with _refusals():
        return container.runs.stressed(request.asked())


@router.get("/runs", responses=problem_responses(400, 401, 409, 422))
def listed_runs(
    container: ContainerDependency,
    strategy: Annotated[str | None, Query(description="A strategy's name.")] = None,
    versioned: Annotated[
        bool | None, Query(description="False for the runs that name no saved version.")
    ] = None,
    status: Annotated[JobStatus | None, Query(description="A run's status.")] = None,
    cursor: Annotated[
        str | None, Query(description="The `next_cursor` of the page before.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MOST_RUNS_PER_PAGE)] = RUNS_PER_PAGE,
) -> RunPage:
    """A page of the runs, newest first, the run folders no row holds indexed first, unless a
    backtest is queued or running; refused with 400 for a cursor the list did not give and 409
    where the library holds files the index cannot follow."""
    asked = RunsAsked(
        strategy=strategy, versioned=versioned, status=status, cursor=cursor, limit=limit
    )
    try:
        return container.runs.page(asked)
    except RunCursorError as unreadable:
        raise HTTPException(400, str(unreadable)) from unreadable
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.get("/runs/{run}", responses=problem_responses(401, 404, 422))
def run_by_id(run: RunAddress, container: ContainerDependency) -> IndexedRun:
    """The run, by its id or its run key, with its four key figures once saved."""
    try:
        return container.runs.by_id(run)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown


@router.get("/runs/{run}/stats", responses=problem_responses(401, 404, 409, 422))
def run_statistics(run: RunAddress, container: ContainerDependency) -> RunStatistics:
    """A saved run's metrics with their breakdowns, its currency, its net P&L as a share of its
    capital, its fidelity eras, and its warnings, from the record in its folder;
    409 for a run not saved yet, a folder that is gone, or one this engine does not read."""
    with _refusals():
        return container.runs.statistics(run)


@router.get("/runs/{run}/equity", responses=problem_responses(401, 404, 409, 422))
def run_equity(
    run: RunAddress,
    container: ContainerDependency,
    max_points: Annotated[
        int,
        Query(
            ge=FEWEST_POINTS,
            le=MOST_EQUITY_POINTS,
            description="The most points to answer: each bucket of a longer curve keeps its "
            "lowest equity, its highest, and its deepest drawdown.",
        ),
    ] = EQUITY_POINTS,
) -> EquityCurve:
    """A saved run's equity and its drawdown after each decision, in at most `max_points` points
    that keep its true maximum drawdown; 409 as `/stats` answers it."""
    with _refusals():
        return container.runs.equity_curve(run, max_points)


@router.get("/runs/{run}/distribution", responses=problem_responses(401, 404, 409, 422))
def run_distribution(run: RunAddress, container: ContainerDependency) -> TradeDistributions:
    """A saved run's trades as histograms of net P&L, R multiple, MAE and MFE in ticks, and
    minutes held; 409 as `/stats` answers it."""
    with _refusals():
        return container.runs.distributions(run)


@router.get("/runs/{run}/monte-carlo", responses=problem_responses(401, 404, 409, 422))
def run_monte_carlo(
    run: RunAddress,
    container: ContainerDependency,
    paths: Annotated[
        int,
        Query(
            ge=FEWEST_PATHS,
            le=MOST_PATHS,
            description="The paths to draw, each as many of the run's trades as it made.",
        ),
    ] = MONTE_CARLO_PATHS,
    seed: Annotated[
        int,
        Query(
            ge=0,
            le=MOST_SEED,
            description="The seed of the draws: the same seed and paths answer the same.",
        ),
    ] = MONTE_CARLO_SEED,
    max_points: Annotated[
        int,
        Query(
            ge=FEWEST_POINTS,
            le=MOST_EQUITY_POINTS,
            description="The most counts of trades the fan holds, spread evenly from none to the "
            "run's trades.",
        ),
    ] = EQUITY_POINTS,
) -> MonteCarloAnswer:
    """A saved run's Monte Carlo (step 5.20): `paths` walks of its trades drawn with replacement
    from `seed`, their net P&L and closed-trade maximum drawdown at five percentiles beside the
    run's own walk, the shares of paths that end below the capital and fall deeper than the run,
    and the equity fan; `too_few_trades`, with why, for a run of fewer than two trades; 409 as
    `/stats` answers it."""
    with _refusals():
        return container.runs.monte_carlo(run, paths, seed, max_points)


@router.post("/runs/{run}/cancel", responses=problem_responses(401, 403, 404, 422))
def cancel_run(run: RunAddress, container: ContainerDependency) -> IndexedRun:
    """Cancel the run's job, at once while it is queued, asked while it runs; a saved run, or
    one whose job has ended, is answered as it is."""
    try:
        return container.runs.cancel(run)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
