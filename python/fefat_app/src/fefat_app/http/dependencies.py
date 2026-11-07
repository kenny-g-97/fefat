"""What the routes get through FastAPI's dependencies (step 4.2, D-86): the container the app was
built with, and the identity a request proves. A bearer token in `Authorization` decides alone,
so that a wrong token never falls back to the cookie; otherwise the session's cookie, whose
requests that change state must carry the session's CSRF token in `X-CSRF-Token`, which no
other site's page can read or send. The three are declared through `fastapi.security`, so that
the docs' Authorize dialog offers them."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyCookie, APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from fefat_app.container import Container
from fefat_app.http.session_cookie import SESSION_COOKIE
from fefat_app.services.identity import ApiTokenIdentity, SessionIdentity

CSRF_HEADER = "X-CSRF-Token"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BEARER_CHALLENGE = "Bearer"
"""The API's challenge, which opens no prompt in a browser, unlike Basic's."""

api_token = HTTPBearer(
    auto_error=False,
    scheme_name="ApiToken",
    description="An API token of `fefat token create`, for notebooks and scripts.",
)
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    scheme_name="Session",
    description="The login session's cookie, which `POST /v1/auth/login` sets.",
)
csrf_header = APIKeyHeader(
    name=CSRF_HEADER,
    auto_error=False,
    scheme_name="CsrfToken",
    description=(
        "The `csrf_token` of `POST /v1/auth/login` or `GET /v1/me`, which every request that "
        "changes state must carry when the session's cookie authenticates it."
    ),
)


def the_container(request: Request) -> Container:
    """The container `fefat_app.http.app.create_app` built the app with."""
    container: Container = request.app.state.container
    return container


ContainerDependency = Annotated[Container, Depends(the_container)]


def the_identity(
    request: Request,
    container: ContainerDependency,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(api_token)],
    cookie: Annotated[str | None, Depends(session_cookie)],
    presented_csrf_token: Annotated[str | None, Depends(csrf_header)],
) -> SessionIdentity | ApiTokenIdentity:
    """The identity the request proves (module docstring); refused with 401, or with 403 for a
    change of state by cookie without the session's CSRF token."""
    if bearer is not None:
        return _identity_of_token(container, bearer.credentials)
    if cookie is None:
        raise _unauthorised("Expected a login session's cookie or an API token, got neither.")
    identity = container.logins.identity_of_session(cookie)
    if identity is None:
        raise _unauthorised("Expected a live login session, got one that ended: log in again.")
    if request.method in STATE_CHANGING_METHODS and not _is_the_csrf_token(
        identity, presented_csrf_token
    ):
        presented = "none" if presented_csrf_token is None else "another"
        raise HTTPException(
            403, f"Expected the session's CSRF token in {CSRF_HEADER}, got {presented}."
        )
    return identity


IdentityDependency = Annotated[SessionIdentity | ApiTokenIdentity, Depends(the_identity)]


def _identity_of_token(container: Container, token: str) -> ApiTokenIdentity:
    identity = container.api_tokens.identity_of_token(token)
    if identity is None:
        raise _unauthorised("Expected an API token that is kept and not revoked, got another.")
    return identity


def _is_the_csrf_token(identity: SessionIdentity, presented: str | None) -> bool:
    if presented is None:
        return False
    return secrets.compare_digest(identity.csrf_token.encode(), presented.encode())


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": BEARER_CHALLENGE})
