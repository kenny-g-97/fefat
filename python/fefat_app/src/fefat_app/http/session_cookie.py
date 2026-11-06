"""The login session's cookie (step 4.2, D-86, `01-architecture.md` section 8): `HttpOnly`, so
that no script reads it; `SameSite=Strict`, so that no other site's page sends it; for every
path of the app, as long as the session lasts; and `Secure` only when the server answers over
HTTPS, since a browser drops a secure cookie that plain `http://127.0.0.1` sets.

A login's refusals become problems here, for the API's login and the docs' prompt alike."""

from fastapi import HTTPException, Request, Response

from fefat_app.container import Container
from fefat_app.services.logins import (
    SESSION_LIFETIME,
    OpenedLoginSession,
    TooManyLoginAttemptsError,
    WrongPasswordError,
)

SESSION_COOKIE = "fefat_session"


def opened_login_session(container: Container, password: str, challenge: str) -> OpenedLoginSession:
    """A login with `password`; refused with 401 and `challenge`, which names how to log in,
    for a wrong password, and with 429 and `Retry-After` once the attempts ran out."""
    try:
        return container.logins.login(password)
    except WrongPasswordError as refused:
        raise HTTPException(401, str(refused), headers={"WWW-Authenticate": challenge}) from refused
    except TooManyLoginAttemptsError as refused:
        retry_after = {"Retry-After": str(refused.retry_after_seconds)}
        raise HTTPException(429, str(refused), headers=retry_after) from refused


def set_session_cookie(response: Response, opened: OpenedLoginSession, request: Request) -> None:
    """Set the cookie of the session `opened` on `response`."""
    response.set_cookie(
        SESSION_COOKIE,
        opened.token.get_secret_value(),
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    """Have the browser drop the session's cookie."""
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
