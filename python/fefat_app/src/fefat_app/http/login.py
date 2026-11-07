"""`POST /v1/auth/login`, `POST /v1/auth/logout`, and `GET /v1/me` (step 4.2, D-86,
`01-architecture.md` sections 7 and 8): the login takes the password as JSON, which no other
site's page can send without the browser asking this server first, since FastAPI's strict
content type refuses a body sent untyped or as text, and it sets the session's cookie."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from fefat_app.container import Container
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import (
    BEARER_CHALLENGE,
    ContainerDependency,
    IdentityDependency,
    the_identity,
)
from fefat_app.http.problems import problem_responses
from fefat_app.http.session_cookie import SESSION_COOKIE, clear_session_cookie, set_session_cookie
from fefat_app.services.identity import Identity, SessionIdentity
from fefat_app.services.logins import (
    MAXIMUM_PASSWORD_LENGTH,
    OpenedLoginSession,
    TooManyLoginAttemptsError,
    WrongPasswordError,
)

router = APIRouter(prefix=API_PREFIX, tags=["login"])


class LoginRequest(BaseModel):
    """The password, set at `fefat up`'s first run or by `fefat password set`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=MAXIMUM_PASSWORD_LENGTH)


@router.post("/auth/login", responses=problem_responses(401, 422, 429))
def login(
    request: Request, response: Response, credentials: LoginRequest, container: ContainerDependency
) -> SessionIdentity:
    """Log in with the password: the response sets the cookie of a session of 30 days and
    returns its CSRF token; refused with 401 for a wrong password, and with 429 after five
    attempts in a minute."""
    opened = _opened_login_session(container, credentials.password.get_secret_value())
    set_session_cookie(response, opened, request)
    return opened.identity


@router.post(
    "/auth/logout",
    status_code=204,
    dependencies=[Depends(the_identity)],
    responses=problem_responses(401, 403),
)
def logout(request: Request, container: ContainerDependency) -> Response:
    """End the session the cookie names, whether the cookie or an API token authenticates the
    request, and clear the cookie."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is not None:
        container.logins.logout(cookie)
    ended = Response(status_code=204)
    clear_session_cookie(ended, request)
    return ended


@router.get("/me", responses=problem_responses(401))
def me(identity: IdentityDependency) -> Identity:
    """Who the request comes from: a login session, with its CSRF token and when it ends, or
    an API token, by its name."""
    return identity


def _opened_login_session(container: Container, password: str) -> OpenedLoginSession:
    try:
        return container.logins.login(password)
    except WrongPasswordError as refused:
        challenge = {"WWW-Authenticate": BEARER_CHALLENGE}
        raise HTTPException(401, str(refused), headers=challenge) from refused
    except TooManyLoginAttemptsError as refused:
        retry_after = {"Retry-After": str(refused.retry_after_seconds)}
        raise HTTPException(429, str(refused), headers=retry_after) from refused
