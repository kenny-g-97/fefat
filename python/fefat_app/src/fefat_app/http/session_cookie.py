"""The login session's cookie (step 4.2, D-86, `01-architecture.md` section 8): `HttpOnly`, so
that no script reads it; `SameSite=Strict`, so that no other site's page sends it; for every
path of the app, as long as the session lasts; and `Secure` only when the server answers over
HTTPS, since a browser drops a secure cookie that plain `http://127.0.0.1` sets."""

from fastapi import Request, Response

from fefat_app.services.logins import SESSION_LIFETIME, OpenedLoginSession

SESSION_COOKIE = "fefat_session"


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
