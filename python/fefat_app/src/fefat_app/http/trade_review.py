"""A saved run's trades in context over the API (step 5.9, D-93), behind the login, a session's or
an API token's, over `fefat_app.services.trade_review`: `GET /v1/runs/{run}/chart`, a page of the
run's chart, its bars a page at a time as `GET /v1/market/bars` gives them, with the trades it
shows and the strategy's features; and `POST /v1/runs/{run}/explain/{trade_id}`, the trade
replayed through the reference engine as an `explain` job, whose result `GET /v1/jobs/{id}`
gives. Each answers 404 for an unknown run, 409 as the run's results do, the chart 400 for a
window the SDK refuses, and the explanation 404 for an id that is no trade's."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.http.runs import RunAddress
from fefat_app.job_models import Job
from fefat_app.runs import NoSuchRunError, ResultsRefusedError
from fefat_app.services.market_bars import WINDOW_START, BarsRefusedError
from fefat_app.trade_review import ChartPage, NoSuchTradeError

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])


@contextmanager
def _refusals() -> Generator[None]:
    """What the trade review refuses, as the API answers it."""
    try:
        yield
    except BarsRefusedError as refused:
        raise HTTPException(400, str(refused)) from refused
    except (NoSuchRunError, NoSuchTradeError) as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except ResultsRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.get("/runs/{run}/chart", responses=problem_responses(400, 401, 404, 409, 422))
def run_chart(
    run: RunAddress,
    container: ContainerDependency,
    start: Annotated[
        str,
        Query(
            alias="from",
            pattern=WINDOW_START,
            description="The trade date the window starts on, such as `2026-03-06`, or the "
            "instant a page opens at, a page's `next_from`, such as `2026-03-06T03:20:00Z`.",
        ),
    ],
    end: Annotated[date, Query(alias="to", description="The trade date the window ends on.")],
) -> ChartPage:
    """A page of at most 20,000 of the saved run's bars on the trade dates from `from` to `to`, in
    the strategy's timeframe, at the prices each contract traded at, which its fills hold, as
    `GET /v1/market/bars` pages them; the instrument's tick; the strategy's features at each
    bar's close, those its exit rules read as a distance in the instrument's units; and the
    trades with a fill on the page or held across it, each with every fill, the bar each lies
    on by F-BAR-06, its stop's first and last level, and its targets."""
    with _refusals():
        return container.trade_review.chart(run, start, end)


@router.post(
    "/runs/{run}/explain/{trade_id}",
    status_code=202,
    responses=problem_responses(401, 403, 404, 409, 422),
)
def explain_trade(
    run: RunAddress,
    trade_id: Annotated[int, Path(ge=0, description="The trade's id, its entry order.")],
    container: ContainerDependency,
) -> Job:
    """Start the explanation of the trade `trade_id` of the saved run: an `explain` job that
    replays it through the reference engine on the run's saved spec, signals, and pinned data,
    whose result is its events and its fills, or why the replay refused it; the job of the same
    trade already queued or running where there is one. Refused with 404 for an id that is no
    trade's of the run."""
    with _refusals():
        return container.trade_review.explain(run, trade_id)
