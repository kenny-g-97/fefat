"""Errors as RFC 9457 problem details, `application/problem+json` (`01-architecture.md` section
7, D-86): every error the API answers names its status, a title, a detail, the path it was asked
for, and the request's id, which its line in the server's log carries too. A validation error
lists each error's location, message, and type, never the value sent, which can be a password
or a key; a failure shows its request id alone, its traceback going to the log."""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    """An error the API answered (RFC 9457), with the id of the request it ended."""

    model_config = ConfigDict(frozen=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    request_id: str


class FieldError(BaseModel):
    """Where a request broke the API's schema and why, without the value it sent."""

    model_config = ConfigDict(frozen=True)

    location: tuple[str | int, ...]
    message: str
    type: str


class ValidationProblem(Problem):
    """A request the API's schema refused, with each of its errors."""

    errors: tuple[FieldError, ...]


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI entries of a route's error statuses, each a problem, 422 a validation one;
    `problems_as_problem_json` files them under `application/problem+json`."""
    return {
        status: {
            "model": ValidationProblem if status == HTTPStatus.UNPROCESSABLE_ENTITY else Problem
        }
        for status in statuses
    }


def problems_as_problem_json(document: dict[str, Any]) -> dict[str, Any]:
    """`document` with each error response's schema under the media type the API answers it
    with, where FastAPI files it under the route's own, `application/json`, or an event stream's
    `text/event-stream` (step 4.4)."""
    for path_item in document["paths"].values():
        for operation in path_item.values():
            for status, response in operation["responses"].items():
                content = response.get("content", {})
                if status[0] in "45" and content:
                    response["content"] = {PROBLEM_MEDIA_TYPE: next(iter(content.values()))}
    return document


def install_problem_handlers(api: FastAPI) -> None:
    """Answer every refusal, invalid request, and failure of `api` as a problem."""
    api.add_exception_handler(StarletteHTTPException, _refused)
    api.add_exception_handler(RequestValidationError, _invalid)
    api.add_exception_handler(Exception, _failed)


def problem_response(
    request: Request, status: int, detail: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """The problem of `status` for `request`, with `detail` and any `headers`, such as a
    challenge or a `Retry-After`."""
    problem = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        request_id=request_id_of(request),
    )
    return _response(problem, headers)


def request_id_of(request: Request) -> str:
    """The id `fefat_app.http.request_ids` gave `request`."""
    request_id: str = request.state.request_id
    return request_id


def _response(problem: Problem, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=problem.status,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _refused(request: Request, error: Exception) -> Response:
    if not isinstance(error, StarletteHTTPException):
        raise error
    return problem_response(request, error.status_code, str(error.detail), error.headers)


def _invalid(request: Request, error: Exception) -> Response:
    if not isinstance(error, RequestValidationError):
        raise error
    errors = tuple(
        FieldError(location=tuple(found["loc"]), message=found["msg"], type=found["type"])
        for found in error.errors()
    )
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    problem = ValidationProblem(
        title=status.phrase,
        status=status,
        detail=f"Expected a request the API's schema accepts, got one with {len(errors)} errors.",
        instance=request.url.path,
        request_id=request_id_of(request),
        errors=errors,
    )
    return _response(problem)


def _failed(request: Request, error: Exception) -> Response:
    request_id = request_id_of(request)
    detail = f"The server failed; its log under FEFAT_HOME/logs holds request {request_id}."
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, detail)
