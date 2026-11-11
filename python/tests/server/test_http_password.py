"""`POST /v1/auth/password` of step 4.3 (from `BACKLOG.md`, D-86): the settings page changes the
password with the current one, counted with the logins' attempts; every login session ends, and
the browser that asked gets the cookie of a new one; an API token manages nothing; and from step
5.2 every API token is revoked."""

from fastapi.testclient import TestClient

from fefat_app.container import Container
from local_server import PASSWORD, logged_in

NEW_PASSWORD = "quiet desk lamp"
CHANGE = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}


def test_a_change_keeps_this_browser_logged_in_and_ends_every_other_session(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    old_cookie = client.cookies["fefat_session"]

    changed = client.post("/v1/auth/password", json=CHANGE, headers=csrf)

    new_cookie = client.cookies["fefat_session"]
    assert changed.status_code == 200
    assert changed.json()["kind"] == "session"
    assert new_cookie != old_cookie
    assert client.get("/v1/me").json()["csrf_token"] == changed.json()["csrf_token"]
    old_session = client.get("/v1/me", headers={"Cookie": f"fefat_session={old_cookie}"})
    assert old_session.status_code == 401
    assert client.post("/v1/auth/login", json={"password": PASSWORD}).status_code == 401
    assert client.post("/v1/auth/login", json={"password": NEW_PASSWORD}).status_code == 200


def test_a_change_revokes_every_api_token(client: TestClient, container: Container) -> None:
    # Step 5.2 (from `BACKLOG.md`, the Phase 4 exit's security review): a token outlived the
    # password it was made under.
    csrf = logged_in(client, container)
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}
    before = client.get("/v1/me", headers=bearer).status_code

    changed = client.post("/v1/auth/password", json=CHANGE, headers=csrf)

    assert (before, changed.status_code) == (200, 200)
    assert client.get("/v1/me", headers=bearer).status_code == 401
    assert client.get("/v1/api-tokens").json() == []


def test_a_wrong_current_password_is_refused_and_changes_nothing(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    wrong = {"current_password": "not the password", "new_password": NEW_PASSWORD}

    refused = client.post("/v1/auth/password", json=wrong, headers=csrf)

    assert refused.status_code == 403
    assert refused.json()["detail"] == "Expected the password that was set, got another."
    assert client.get("/v1/me").status_code == 200
    assert client.post("/v1/auth/login", json={"password": PASSWORD}).status_code == 200


def test_the_current_password_is_counted_with_the_logins_attempts(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    wrong = {"current_password": "not the password", "new_password": NEW_PASSWORD}

    statuses = [
        client.post("/v1/auth/password", json=wrong, headers=csrf).status_code for _ in range(5)
    ]
    sixth = client.post("/v1/auth/password", json=CHANGE, headers=csrf)

    assert statuses == [403] * 5
    assert (sixth.status_code, "retry-after" in sixth.headers) == (429, True)


def test_a_new_password_under_eight_characters_is_refused(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    short = {"current_password": PASSWORD, "new_password": "short"}

    assert client.post("/v1/auth/password", json=short, headers=csrf).status_code == 422


def test_a_change_needs_the_sessions_csrf_token_and_never_takes_an_api_token(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    without_csrf = client.post("/v1/auth/password", json=CHANGE)
    by_token = client.post("/v1/auth/password", json=CHANGE, headers=bearer)

    assert without_csrf.status_code == 403
    assert by_token.status_code == 403
    assert by_token.json()["detail"].startswith("Expected a login session, got an API token")
    assert client.post("/v1/auth/login", json={"password": PASSWORD}).status_code == 200
