"""The runs' routes (step 5.3, `01-architecture.md` section 7, D-93), behind the login, a session's
or an API token's, over `fefat_app.services.runs`: `POST /v1/runs`, which answers 200 with the run
its request finds saved and 202 with a run whose `backtest` job is queued or running, whose
progress the job's stream gives (`GET /v1/streams/job:<job id>`); `POST /v1/runs/estimate`, what a
run would read, before anything runs, and `POST /v1/runs/stress`, a run and the same at more ticks
of slippage (step 5.6); `GET /v1/runs`, a page of the runs; `GET /v1/runs/{run}`, a run by its id
or its run key, with its metrics once saved; and `POST /v1/runs/{run}/cancel`. A run's status is
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

from fefat.backtest import RunConfig
from fefat.market.contracts import parse_contract_name
from fefat.market.fidelity import FidelityText
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import CodeRefused, code_refusal_responses, problem_responses
from fefat_app.job_models import JobStatus
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import (
    EstimateRefusedError,
    IndexedRun,
    NoSuchRunError,
    RunCursorError,
    RunEstimate,
    RunPage,
    RunWithMetrics,
    SavedRun,
    StressedRuns,
)
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.runs import RUNS_PER_PAGE, RunAsked, RunsAsked
from fefat_app.services.strategies import NoSuchStrategyError

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])

MOST_RUNS_PER_PAGE = 100
"""The most runs a page of the list holds."""
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
    finest data it fills on, the provider whose data it reads, and the one contract it reads in
    place of the roll calendar's fronts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fidelity: FidelityText | None = None
    provider: str | None = None
    contract: str | None = None

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
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
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
def run_by_id(run: RunAddress, container: ContainerDependency) -> RunWithMetrics:
    """The run, by its id or its run key, with its metrics, its fidelity eras, and its warnings
    once saved."""
    try:
        return container.runs.by_id(run)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown


@router.post("/runs/{run}/cancel", responses=problem_responses(401, 403, 404, 422))
def cancel_run(run: RunAddress, container: ContainerDependency) -> RunWithMetrics:
    """Cancel the run's job, at once while it is queued, asked while it runs; a saved run, or
    one whose job has ended, is answered as it is."""
    try:
        return container.runs.cancel(run)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
