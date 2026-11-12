"""The runs' routes (step 5.3, `01-architecture.md` section 7, D-93), behind the login, a session's
or an API token's, over `fefat_app.services.runs`: `POST /v1/runs`, which answers 200 with the run
its request finds saved and 202 with a run whose `backtest` job is queued or running, whose
progress the job's stream gives (`GET /v1/streams/job:<job id>`); `GET /v1/runs`, the newest runs;
`GET /v1/runs/{run_id}`, a run with its metrics once saved; and `POST /v1/runs/{run_id}/cancel`.
A run's status is `succeeded` once its folder is saved, its job's before; a job whose run proved
saved under another run's row names that row in its result, which a client then follows."""

from datetime import date
from typing import Annotated, Self

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from fefat.backtest import RunConfig
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import CodeRefused, code_refusal_responses, problem_responses
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import IndexedRun, NoSuchRunError, RunWithMetrics
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.runs import RunAsked
from fefat_app.services.strategies import NoSuchStrategyError

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])

RunId = Annotated[str, Path(description="A run's id in the index, a UUIDv7.")]
FOUND_SAVED = {
    200: {
        "model": IndexedRun,
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
    asked = RunAsked(
        strategy_version_id=request.strategy_version_id,
        parameters=request.parameters,
        start=request.start,
        end=request.end,
        settings=request.settings,
    )
    try:
        run = container.runs.submit(asked)
    except CodeRefusedError as refused:
        raise CodeRefused(refused.line, str(refused)) from refused
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused
    if run.run_key is not None:
        response.status_code = 200
    return run


@router.get("/runs", responses=problem_responses(401))
def newest_runs(container: ContainerDependency) -> tuple[IndexedRun, ...]:
    """The hundred newest runs, newest first, without their metrics."""
    return container.runs.newest()


@router.get("/runs/{run_id}", responses=problem_responses(401, 404, 422))
def run_by_id(run_id: RunId, container: ContainerDependency) -> RunWithMetrics:
    """The run, with its metrics, its fidelity eras, and its warnings once saved."""
    try:
        return container.runs.by_id(run_id)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown


@router.post("/runs/{run_id}/cancel", responses=problem_responses(401, 403, 404, 422))
def cancel_run(run_id: RunId, container: ContainerDependency) -> RunWithMetrics:
    """Cancel the run's job, at once while it is queued, asked while it runs; a saved run, or
    one whose job has ended, is answered as it is."""
    try:
        return container.runs.cancel(run_id)
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
