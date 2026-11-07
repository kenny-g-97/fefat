"""`GET`, `POST`, and `DELETE /v1/api-tokens` of step 4.3 (from `BACKLOG.md`, D-86): the settings
page lists, makes, and revokes the API tokens of notebooks and scripts; a token is shown once, a
list never carries one, a revoked token is refused, and an API token manages none."""

from fastapi.testclient import TestClient

from fefat_app.container import Container
from local_server import logged_in


def test_a_created_token_is_shown_once_and_authenticates_its_name(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    created = client.post("/v1/api-tokens", json={"name": "notebook"}, headers=csrf)

    token = created.json()["token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert created.status_code == 201
    assert created.json()["name"] == "notebook"
    assert token.startswith("fefat_")
    assert me.json() == {"kind": "api_token", "token_name": "notebook"}


def test_the_list_names_each_live_token_with_its_times_and_never_the_token(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    token = client.post("/v1/api-tokens", json={"name": "notebook"}, headers=csrf).json()["token"]

    listed = client.get("/v1/api-tokens")

    assert listed.json() == [
        {"name": "notebook", "created_at": "2026-11-06T09:00:00Z", "last_used_at": None}
    ]
    assert token not in listed.text


def test_a_revoked_token_is_refused_and_leaves_the_list(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    token = client.post("/v1/api-tokens", json={"name": "notebook"}, headers=csrf).json()["token"]

    revoked = client.delete("/v1/api-tokens/notebook", headers=csrf)
    again = client.delete("/v1/api-tokens/notebook", headers=csrf)

    assert revoked.status_code == 204
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/v1/api-tokens").json() == []
    assert again.status_code == 404
    assert again.json()["detail"] == "Expected the name of a live API token, got 'notebook'."


def test_a_name_in_use_or_outside_the_pattern_is_refused(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    client.post("/v1/api-tokens", json={"name": "notebook"}, headers=csrf)

    in_use = client.post("/v1/api-tokens", json={"name": "notebook"}, headers=csrf)
    spaced = client.post("/v1/api-tokens", json={"name": "two words"}, headers=csrf)

    assert in_use.status_code == 409
    assert in_use.json()["detail"] == (
        "Expected a new token name, got 'notebook', which a token has."
    )
    assert spaced.status_code == 422


def test_only_a_login_session_manages_the_tokens(client: TestClient, container: Container) -> None:
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    listing = client.get("/v1/api-tokens", headers=bearer)
    minting = client.post("/v1/api-tokens", json={"name": "another"}, headers=bearer)
    revoking = client.delete("/v1/api-tokens/notebook", headers=bearer)
    anonymous = client.get("/v1/api-tokens")

    assert (listing.status_code, minting.status_code, revoking.status_code) == (403, 403, 403)
    assert anonymous.status_code == 401
    assert container.api_tokens.identity_of_token(bearer["Authorization"][7:]) is not None
