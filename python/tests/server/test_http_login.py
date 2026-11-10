"""Login, the session cookie, CSRF, API tokens, and the API's own docs of step 4.2 (D-86,
`01-architecture.md` section 8): Done means 1's `/docs` behind the login, and Done means 2's
login, CSRF, and bearer tests."""

from datetime import timedelta

from fastapi.testclient import TestClient

from fefat_app.container import Container
from fefat_app.http.app import create_app
from local_server import PASSWORD, SettableClock, basic, logged_in, session_cookie

PROBLEM = "application/problem+json"
A_SECRET_CHANGE = {"secrets": {"anthropic": "a key"}}
LOGIN_PAGE_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; form-action 'none'; base-uri 'none'"
)


def test_a_login_sets_a_strict_http_only_cookie_whose_session_me_shows(
    client: TestClient, container: Container
) -> None:
    # Done means 2: the login flow.
    container.logins.set_password(PASSWORD)

    response = client.post("/v1/auth/login", json={"password": PASSWORD})
    me = client.get("/v1/me")

    cookie = session_cookie(response)
    assert response.status_code == 200
    assert (cookie["httponly"], cookie["samesite"].lower(), cookie["path"]) == (True, "strict", "/")
    assert (cookie["max-age"], cookie["secure"]) == ("2592000", "")
    assert me.status_code == 200
    assert me.json() == response.json()
    assert me.json()["kind"] == "session"


def test_over_https_the_cookie_is_secure(container: Container) -> None:
    container.logins.set_password(PASSWORD)
    app = create_app(container, built_web_app=None)
    with TestClient(app, base_url="https://127.0.0.1") as client:
        response = client.post("/v1/auth/login", json={"password": PASSWORD})
        me = client.get("/v1/me")

    assert session_cookie(response)["secure"] is True
    assert me.status_code == 200


def test_without_a_login_the_api_answers_401_with_a_challenge_that_opens_no_prompt(
    client: TestClient,
) -> None:
    for response in (client.get("/v1/me"), client.get("/v1/settings")):
        assert (response.status_code, response.headers["content-type"]) == (401, PROBLEM)
        assert response.headers["www-authenticate"] == "Bearer"


def test_a_wrong_password_is_refused_and_the_sixth_attempt_must_wait(
    client: TestClient, container: Container
) -> None:
    container.logins.set_password(PASSWORD)

    wrong = [client.post("/v1/auth/login", json={"password": "another one"}) for _ in range(5)]
    waiting = client.post("/v1/auth/login", json={"password": PASSWORD})

    assert [response.status_code for response in wrong] == [401] * 5
    assert (waiting.status_code, waiting.headers["retry-after"]) == (429, "60")
    assert "set-cookie" not in waiting.headers
    assert client.get("/v1/me").status_code == 401


def test_a_login_without_a_json_body_is_refused_before_it_counts(
    client: TestClient, container: Container
) -> None:
    # A page of another site can send a body without a content type, or as text/plain, with no
    # preflight; FastAPI's strict content type refuses both before the login sees them.
    container.logins.set_password(PASSWORD)
    body = f'{{"password": "{PASSWORD}"}}'.encode()

    untyped = [client.post("/v1/auth/login", content=body) for _ in range(3)]
    plain = [
        client.post("/v1/auth/login", content=body, headers={"Content-Type": "text/plain"})
        for _ in range(3)
    ]
    login = client.post("/v1/auth/login", json={"password": PASSWORD})

    assert [response.status_code for response in untyped + plain] == [422] * 6
    assert "set-cookie" not in untyped[0].headers
    assert login.status_code == 200


def test_logout_ends_the_session_and_clears_its_cookie(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post("/v1/auth/logout", headers=csrf)

    cookie = session_cookie(response)
    assert response.status_code == 204
    assert (cookie.value, cookie["max-age"]) == ("", "0")
    assert client.get("/v1/me").status_code == 401


def test_a_session_past_its_thirty_days_is_refused(
    client: TestClient, container: Container, clock: SettableClock
) -> None:
    logged_in(client, container)
    clock.advance(timedelta(days=30))

    assert client.get("/v1/me").status_code == 401


def test_a_change_of_state_by_cookie_must_carry_the_sessions_csrf_token(
    client: TestClient, container: Container
) -> None:
    # Done means 2: CSRF rejection.
    csrf = logged_in(client, container)

    missing = client.put("/v1/settings", json=A_SECRET_CHANGE)
    wrong = client.put("/v1/settings", json=A_SECRET_CHANGE, headers={"X-CSRF-Token": "0" * 64})
    not_ascii = client.put(
        "/v1/settings", json=A_SECRET_CHANGE, headers={b"X-CSRF-Token": "é".encode("latin-1")}
    )
    right = client.put("/v1/settings", json=A_SECRET_CHANGE, headers=csrf)
    logout = client.post("/v1/auth/logout")

    refused = [missing, wrong, not_ascii, logout]
    assert [response.status_code for response in refused] == [403] * 4
    assert missing.headers["content-type"] == PROBLEM
    assert right.status_code == 200
    assert client.get("/v1/me").status_code == 200


def test_an_api_token_authenticates_without_a_csrf_token(
    client: TestClient, container: Container
) -> None:
    # Done means 2: a bearer token for the API.
    token = container.api_tokens.create("notebook")
    bearer = {"Authorization": f"Bearer {token}"}

    me = client.get("/v1/me", headers=bearer)
    change = client.put("/v1/settings", json=A_SECRET_CHANGE, headers=bearer)

    assert me.json() == {"kind": "api_token", "token_name": "notebook"}
    assert change.status_code == 200


def test_a_wrong_api_token_is_refused_even_beside_a_live_session(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    wrong = client.put(
        "/v1/settings", json=A_SECRET_CHANGE, headers={**csrf, "Authorization": "Bearer fefat_x"}
    )

    assert (wrong.status_code, wrong.headers["www-authenticate"]) == (401, "Bearer")


def test_the_browsers_basic_credentials_beside_a_session_change_nothing(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    response = client.get("/v1/me", headers=basic(PASSWORD))

    assert response.json()["kind"] == "session"


def test_without_a_session_the_docs_answer_a_password_page_never_the_browsers_prompt(
    client: TestClient, container: Container
) -> None:
    # Done means 1: `/docs` works only after login. A password manager answered the browser's
    # own prompt by itself at your check, five times in a second, which tripped the limit.
    container.logins.set_password(PASSWORD)
    token = container.api_tokens.create("notebook")

    page = client.get("/docs", headers=basic(PASSWORD))
    document = client.get("/openapi.json", headers=basic(PASSWORD))
    by_token = client.get("/openapi.json", headers={"Authorization": f"Bearer {token}"})

    assert page.status_code == 200
    assert ('type="password"' in page.text, 'fetch("/v1/auth/login"' in page.text) == (True, True)
    assert "swagger-ui" not in page.text
    assert ("www-authenticate" in page.headers, "set-cookie" in page.headers) == (False, False)
    assert page.headers["content-security-policy"] == LOGIN_PAGE_POLICY
    assert page.headers["cache-control"] == "no-store"
    assert (document.status_code, document.headers["www-authenticate"]) == (401, "Bearer")
    assert by_token.json()["info"]["title"] == "FEAT"


def test_a_login_as_the_page_makes_it_serves_the_docs_and_their_document(
    client: TestClient, container: Container
) -> None:
    container.logins.set_password(PASSWORD)

    login = client.post("/v1/auth/login", json={"password": PASSWORD})
    page = client.get("/docs")
    document = client.get("/openapi.json")

    assert login.status_code == 200
    assert "swagger-ui" in page.text
    assert document.json()["info"]["title"] == "FEAT"
    assert document.headers["cache-control"] == "no-store"


def test_a_live_session_gets_the_docs_under_their_own_policy(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    page = client.get("/docs")

    assert page.status_code == 200
    assert "set-cookie" not in page.headers
    assert "script-src 'self' 'unsafe-inline'" in page.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"


def test_the_docs_load_swagger_ui_from_the_app_itself_and_keep_no_token_in_the_browser(
    client: TestClient, container: Container
) -> None:
    # A floating release could change under the session, and a token typed under Authorize
    # would otherwise stay in the browser's storage after the page closes; the release from a
    # CDN needed the internet and trusted the CDN, so the app serves its own copy (the Phase 4
    # exit).
    logged_in(client, container)

    page = client.get("/docs")
    script = client.get("/docs/swagger-ui/swagger-ui-bundle.js")
    style = client.get("/docs/swagger-ui/swagger-ui.css")

    assert '"/docs/swagger-ui/swagger-ui-bundle.js"' in page.text
    assert '"/docs/swagger-ui/swagger-ui.css"' in page.text
    assert "cdn.jsdelivr.net" not in page.text
    assert "persistAuthorization" not in page.text
    assert script.status_code == style.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert style.headers["content-type"].startswith("text/css")


def test_logout_beside_an_api_token_ends_the_cookies_session_too(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)
    cookie = client.cookies["fefat_session"]
    token = container.api_tokens.create("notebook")

    logout = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    after = client.get("/v1/me", headers={"Cookie": f"fefat_session={cookie}"})

    assert (logout.status_code, after.status_code) == (204, 401)
