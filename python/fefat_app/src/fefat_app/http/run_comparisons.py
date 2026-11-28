"""`POST /v1/runs/compare` (step 5.10, D-126), behind the login, a session's or an API token's,
over `fefat_app.services.run_comparisons`: two to four saved runs side by side, the first the
reference."""

from collections.abc import Generator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fefat.backtest import RunComparison
from fefat.backtest.compare import FEWEST_RUNS, MOST_RUNS
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.runs import NoSuchRunError, ResultsRefusedError
from fefat_app.services.run_comparisons import compared

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])


class RunComparisonRequest(BaseModel):
    """Two to four saved runs to set side by side, each by its id or its run key, the first the
    reference whose figures each delta is taken from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: tuple[str, ...] = Field(
        min_length=FEWEST_RUNS,
        max_length=MOST_RUNS,
        description="The runs, each by its id or its run key, the first the reference.",
    )


@contextmanager
def _refusals() -> Generator[None]:
    """What the comparison refuses, as the API answers it."""
    try:
        yield
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except ResultsRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.post("/runs/compare", responses=problem_responses(401, 403, 404, 409, 422))
def compare_runs(request: RunComparisonRequest, container: ContainerDependency) -> RunComparison:
    """Two to four saved runs side by side (step 5.10): each run's figures as its KPI cards show
    them and the settings it ran under, and but for the first, the reference, what each figure
    differs by from the reference's, each a difference of the runs' stored metrics; each run's
    trades by exit reason over every reason any of them closed a trade by, with their deltas; and
    each run's equity at each trade date's end over its own capital. Money as decimal text; 404
    where no run has an id, 409 for a run not saved, a folder gone or damaged, one run twice, or
    runs in two currencies."""
    with _refusals():
        return compared(container.runs, request.runs)
