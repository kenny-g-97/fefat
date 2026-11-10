"""The API's own docs, FastAPI's interactive `/docs` page and the `/openapi.json` it reads (step
4.2, D-86), behind the login and left out of the document they serve.

A live session's cookie gets the interactive page. Without one, `/docs` answers a small page with
a password box, which logs in through `POST /v1/auth/login`, keeps the cookie that sets, and
reloads; it stays beside the web app's login of step 4.3, since it needs no built web app (D-87).
Nothing keeps the password: the browser's
own prompt, which a password manager answered by itself with a password not FEFAT's until the
login's limit tripped, is never asked for. `/openapi.json` answers a session or an API token.

The interactive page loads Swagger UI 5.34.0, whose script, style, and licence the package
carries under `swagger_ui/` (the Phase 4 exit, D-92), from the app itself, so that it needs no
internet and trusts no CDN, and runs inline script, which the app's own content security policy
forbids, so it answers under a policy of its own. What is typed under its Authorize dialog, a
CSRF token or an API token, lasts as long as the page, never kept in the browser's storage. Both
pages are framed by no site and cached by no browser."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response

from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.session_cookie import SESSION_COOKIE

router = APIRouter(include_in_schema=False)

SWAGGER_UI_FILES = Path(__file__).parent / "swagger_ui"
"""Swagger UI 5.34.0 from npm's `swagger-ui-dist`, under its Apache 2.0 licence."""
SWAGGER_UI_PATH = "/docs/swagger-ui"
"""Where the app serves `SWAGGER_UI_FILES`."""
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
)
LOGIN_PAGE_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; form-action 'none'; base-uri 'none'"
)
"""Nothing but its own script and style, and a request to its own server; a form that the
script did not take is refused rather than sent with the password in it."""
LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Log in - FEAT API</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 22rem; margin: 6rem auto; padding: 0 1rem; }
  label, input, button { display: block; width: 100%; box-sizing: border-box; }
  input, button { margin-top: 0.5rem; padding: 0.5rem; font-size: 1rem; }
  #message { min-height: 1.5rem; }
</style>
</head>
<body>
<h1>FEAT API</h1>
<form id="login" method="post">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
  <button type="submit">Log in</button>
</form>
<p id="message" role="alert"></p>
<script>
  const form = document.getElementById("login");
  const message = document.getElementById("message");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.textContent = "";
    try {
      const response = await fetch("/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: form.password.value }),
      });
      if (response.ok) {
        location.reload();
        return;
      }
      message.textContent = (await response.json()).detail;
    } catch {
      message.textContent = "The server did not answer: is fefat up still running?";
    }
  });
</script>
</body>
</html>
"""


@router.get("/docs")
def docs_page(request: Request, container: ContainerDependency) -> HTMLResponse:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is None or container.logins.identity_of_session(cookie) is None:
        return _for_this_browser_alone(HTMLResponse(LOGIN_PAGE), LOGIN_PAGE_CONTENT_SECURITY_POLICY)
    page = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="FEAT API",
        swagger_js_url=f"{SWAGGER_UI_PATH}/swagger-ui-bundle.js",
        swagger_css_url=f"{SWAGGER_UI_PATH}/swagger-ui.css",
        swagger_favicon_url="/favicon.svg",
    )
    return _for_this_browser_alone(page, DOCS_CONTENT_SECURITY_POLICY)


@router.get("/openapi.json", dependencies=[Depends(the_identity)])
def openapi_json(request: Request) -> JSONResponse:
    document = JSONResponse(request.app.openapi())
    document.headers["Cache-Control"] = "no-store"
    return document


def _for_this_browser_alone[Page: Response](page: Page, policy: str) -> Page:
    page.headers["Content-Security-Policy"] = policy
    page.headers["Cache-Control"] = "no-store"
    return page
