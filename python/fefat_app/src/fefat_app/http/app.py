"""The local server's app (step 4.2, D-86, `01-architecture.md` sections 7 and 8): the API under
`/v1`, its docs behind the login, and the built web app at `/`, for a host of the loopback
alone. Every error is a problem (`fefat_app.http.problems`), and every response carries its
request's id and the security headers, which wrap the whole app with the host check."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp

import fefat_app
from fefat_app.container import Container
from fefat_app.http import app_settings, docs, health, login
from fefat_app.http.loopback_hosts import LoopbackHosts
from fefat_app.http.problems import install_problem_handlers, problems_as_problem_json
from fefat_app.http.request_ids import RequestIds
from fefat_app.http.security_headers import SecurityHeaders
from fefat_app.http.web_app import WebAppMount


class FefatApi(FastAPI):
    """FastAPI, whose OpenAPI document files each error under `application/problem+json`."""

    def openapi(self) -> dict[str, Any]:
        return problems_as_problem_json(super().openapi())


def build_api() -> FastAPI:
    """The API's routes and error handlers, without a container: enough for its OpenAPI
    document."""
    api = FefatApi(
        title="FEFAT",
        version=fefat_app.__version__,
        description="FEFAT's local server: its API, for the web app, notebooks, and scripts.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        strict_content_type=True,
    )
    install_problem_handlers(api)
    for router in (health.router, login.router, app_settings.router, docs.router):
        api.include_router(router)
    return api


def create_app(container: Container, built_web_app: Path | None) -> ASGIApp:
    """The app `fefat up` serves: the API over `container`, and the web app built in
    `built_web_app` where there is one."""
    api = build_api()
    api.state.container = container
    if built_web_app is not None:
        api.router.routes.append(WebAppMount(built_web_app))
    return RequestIds(SecurityHeaders(LoopbackHosts(api)))
