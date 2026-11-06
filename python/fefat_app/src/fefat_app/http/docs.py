"""The API's own docs, FastAPI's interactive `/docs` page and the `/openapi.json` it reads (step
4.2, D-86), behind the login and left out of the document they serve.

A live session's cookie lets a request in as it is. Without one, the answer is 401 with a Basic
challenge, which opens the browser's own password prompt until step 4.3's login page exists;
the password typed there, with any user name, logs in through the same counted login and sets
the session's cookie. A browser resends what it typed to every path of the server, which the
API ignores and the cookie, checked first, makes cheap; it forgets it when it closes. Since it
would resend it for an image of another site's page too, logging in each time, a request that
another site started is refused unless it opens a page, as a link does (its `Sec-Fetch-*`
headers tell).

The page loads one release of Swagger UI from jsdelivr, whose files never change once
published, and runs inline script, which the app's own content security policy forbids, so it
answers under a policy of its own and needs the internet. What is typed under its Authorize
dialog, a CSRF token or an API token, lasts as long as the page, never kept in the browser's
storage."""

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response

from fefat_app.http.dependencies import ContainerDependency
from fefat_app.http.session_cookie import SESSION_COOKIE, opened_login_session, set_session_cookie
from fefat_app.services.logins import OpenedLoginSession

router = APIRouter(include_in_schema=False)

BASIC_CHALLENGE = 'Basic realm="FEFAT"'
SWAGGER_UI = "https://cdn.jsdelivr.net"
SWAGGER_UI_RELEASE = f"{SWAGGER_UI}/npm/swagger-ui-dist@5.34.0"
DOCS_CONTENT_SECURITY_POLICY = (
    f"default-src 'self'; script-src 'self' {SWAGGER_UI} 'unsafe-inline'; "
    f"style-src 'self' {SWAGGER_UI} 'unsafe-inline'; img-src 'self' data:"
)


def docs_access(request: Request, container: ContainerDependency) -> OpenedLoginSession | None:
    """None for a live session's request; the session the password at the prompt opened,
    whose cookie the answer sets; refused with 403 for a request another site started, and
    with 401 and the Basic challenge otherwise."""
    if _started_by_another_site(request):
        raise HTTPException(
            403, "Expected a request of this server's pages or a link opened, got another site's."
        )
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is not None and container.logins.identity_of_session(cookie) is not None:
        return None
    password = basic_password(request.headers.get("authorization"))
    if password is None:
        raise HTTPException(
            401,
            "Expected a login session or the password at the browser's prompt, got neither.",
            headers={"WWW-Authenticate": BASIC_CHALLENGE},
        )
    return opened_login_session(container, password, challenge=BASIC_CHALLENGE)


DocsAccess = Annotated[OpenedLoginSession | None, Depends(docs_access)]


@router.get("/docs")
def docs_page(request: Request, opened: DocsAccess) -> HTMLResponse:
    page = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="FEFAT API",
        swagger_js_url=f"{SWAGGER_UI_RELEASE}/swagger-ui-bundle.js",
        swagger_css_url=f"{SWAGGER_UI_RELEASE}/swagger-ui.css",
        swagger_favicon_url="/favicon.ico",
    )
    page.headers["Content-Security-Policy"] = DOCS_CONTENT_SECURITY_POLICY
    _for_this_browser_alone(page, opened, request)
    return page


@router.get("/openapi.json")
def openapi_json(request: Request, opened: DocsAccess) -> JSONResponse:
    document = JSONResponse(request.app.openapi())
    _for_this_browser_alone(document, opened, request)
    return document


def basic_password(authorization: str | None) -> str | None:
    """The password of a Basic `Authorization` header, which a browser encodes in UTF-8; None
    for any other header."""
    if authorization is None:
        return None
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _, separator, password = decoded.partition(":")
    return password if separator else None


def _started_by_another_site(request: Request) -> bool:
    """Whether a browser says another site started the request, other than to open a page."""
    site = request.headers.get("sec-fetch-site")
    opens_a_page = (
        request.headers.get("sec-fetch-mode") == "navigate"
        and request.headers.get("sec-fetch-dest") == "document"
    )
    return site in ("cross-site", "same-site") and not opens_a_page


def _for_this_browser_alone(
    response: Response, opened: OpenedLoginSession | None, request: Request
) -> None:
    response.headers["Cache-Control"] = "no-store"
    if opened is not None:
        set_session_cookie(response, opened, request)
