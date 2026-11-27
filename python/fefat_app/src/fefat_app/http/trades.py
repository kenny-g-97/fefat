"""A saved run's trades over the API (step 5.8, D-124), behind the login, a session's or an API
token's, over `fefat_app.services.trade_table`: `GET /v1/runs/{run}/trades`, a page of its trades
by a keyset, sorted and filtered; `GET /v1/runs/{run}/trades.csv`, every trade under the same
filter and order, and `GET /v1/runs/{run}/executions.csv`, its fills, each a file to download
(D-119); and `POST /v1/runs/{run}/query`, one SELECT over its artifacts, for the trader and for
the agent of Phase 8. Each answers 404 for an unknown run and 409 as the run's results do."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.http.runs import RunAddress
from fefat_app.runs import NoSuchRunError, ResultsRefusedError
from fefat_app.trades import (
    ExportedFile,
    QueryAnswer,
    QueryRefusedError,
    TradeCursorError,
    TradePage,
    TradesShown,
)

router = APIRouter(prefix=API_PREFIX, tags=["runs"], dependencies=[Depends(the_identity)])

TRADES_PER_PAGE = 200
"""How many trades a page holds unless it asks for another number."""
MOST_TRADES_PER_PAGE = 1_000
"""The most trades a page holds."""
MOST_SQL = 20_000
"""The longest query, in characters."""


class TradesPageAsked(TradesShown):
    """A page of a run's trades: those its filters keep, in its order, after the trade the
    cursor of the page before ends on, at most `limit` of them."""

    cursor: str | None = Field(
        default=None, max_length=1_000, description="The `next_cursor` of the page before."
    )
    limit: int = Field(default=TRADES_PER_PAGE, ge=1, le=MOST_TRADES_PER_PAGE)


class RunQuery(BaseModel):
    """One SELECT over a run's artifacts, each a view by its name: `trades`, `fills`, `orders`,
    `log`, `costs`, `trade_paths`, `equity`, `equity_daily`, and `signals`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sql: str = Field(min_length=1, max_length=MOST_SQL)


def _csv_answer(holds: str) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI entry of a route that answers a CSV file holding `holds`."""
    return {
        200: {
            "description": f"A CSV file of {holds}, to download.",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    }


@contextmanager
def _refusals() -> Generator[None]:
    """What the trade table refuses, as the API answers it."""
    try:
        yield
    except (TradeCursorError, QueryRefusedError) as refused:
        raise HTTPException(400, str(refused)) from refused
    except NoSuchRunError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except ResultsRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


def _attachment(exported: ExportedFile) -> Response:
    """The file as a download, under its own name."""
    return Response(
        exported.text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{exported.name}"'},
    )


@router.get("/runs/{run}/trades", responses=problem_responses(400, 401, 404, 409, 422))
def run_trades(
    run: RunAddress, asked: Annotated[TradesPageAsked, Query()], container: ContainerDependency
) -> TradePage:
    """A page of the saved run's trades that the filters keep, in the order asked, ties by their
    row, a trade without the sort's figure last, after the trade the cursor ends on, with how
    many trades the filters keep; 400 for a cursor no page of this order gave."""
    with _refusals():
        return container.trade_table.page(run, asked, asked.cursor, asked.limit)


@router.get(
    "/runs/{run}/trades.csv",
    response_class=Response,
    responses={**_csv_answer("the trades"), **problem_responses(401, 404, 409, 422)},
)
def run_trades_file(
    run: RunAddress, shown: Annotated[TradesShown, Query()], container: ContainerDependency
) -> Response:
    """Every trade of the saved run that the filters keep, in the order asked, a row each as a
    page gives it, as `<strategy>-<run key's first twelve digits>-trades.csv`."""
    with _refusals():
        return _attachment(container.trade_table.trades_file(run, shown))


@router.get(
    "/runs/{run}/executions.csv",
    response_class=Response,
    responses={**_csv_answer("the fills"), **problem_responses(401, 404, 409, 422)},
)
def run_executions_file(run: RunAddress, container: ContainerDependency) -> Response:
    """Every fill of the saved run, one row an execution, in the order the run made them, as
    `<strategy>-<run key's first twelve digits>-executions.csv`."""
    with _refusals():
        return _attachment(container.trade_table.executions_file(run))


@router.post("/runs/{run}/query", responses=problem_responses(400, 401, 403, 404, 409, 422))
def query_run(run: RunAddress, query: RunQuery, container: ContainerDependency) -> QueryAnswer:
    """The answer of one SELECT over the saved run's artifacts, each a view in the instrument's
    units, at most 10,000 rows of at most 4 MiB within 10 seconds; 400 in DuckDB's words or for
    any other statement or a larger answer."""
    with _refusals():
        return container.trade_table.query(run, query.sql)
