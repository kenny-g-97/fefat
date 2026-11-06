"""The local server's app of step 4.2 (D-86, `01-architecture.md` sections 7 and 8): health and
versions without a login, section 8's security headers on every response, a request id on
every response and in the server's log, every error as problem+json, and a host other than the
loopback refused."""

import re
from pathlib import Path

import fefat_engine
import pytest
from fastapi.testclient import TestClient

import fefat
import fefat_app
from fefat_app.container import Container
from fefat_app.http.app import create_app
from local_server import LOOPBACK, logged_in
from memory_keyring import MemoryKeyring

CONTENT_SECURITY_POLICY = "default-src 'self'; img-src 'self' data: blob:"
PROBLEM = "application/problem+json"


def test_health_and_versions_answer_without_a_login(client: TestClient) -> None:
    # Done means 1: `/v1/healthz` answers.
    health = client.get("/v1/healthz")
    versions = client.get("/v1/version")

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert versions.json() == {
        "fefat_app": fefat_app.__version__,
        "fefat": fefat.__version__,
        "engine": fefat_engine.ENGINE_VERSION,
        "fill_model": fefat_engine.FILL_MODEL_VERSION,
        "artifact_schema": fefat_engine.ARTIFACT_SCHEMA_VERSION,
    }


@pytest.mark.parametrize("path", ["/v1/healthz", "/v1/me", "/v1/nothing", "/nothing"])
def test_every_response_carries_the_security_headers(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "DENY"


def test_no_answer_of_the_api_is_cached(client: TestClient) -> None:
    assert client.get("/v1/healthz").headers["cache-control"] == "no-store"
    assert client.get("/v1/me").headers["cache-control"] == "no-store"


def test_each_request_has_an_id_that_its_line_in_the_servers_log_carries(
    client: TestClient, server_log: Path
) -> None:
    response = client.get("/v1/healthz")

    request_id = response.headers["x-request-id"]
    logged = server_log.read_text(encoding="utf-8")
    assert re.fullmatch("[0-9a-f]{16}", request_id)
    assert f"request_id={request_id} method=GET path=/v1/healthz status=200" in logged


def test_an_unknown_path_and_a_wrong_method_answer_problems_with_the_request_id(
    client: TestClient,
) -> None:
    missing = client.get("/v1/nothing")
    not_allowed = client.delete("/v1/healthz")

    for response, status in ((missing, 404), (not_allowed, 405)):
        problem = response.json()
        assert response.status_code == status
        assert response.headers["content-type"] == PROBLEM
        assert (problem["status"], problem["instance"]) == (status, response.url.path)
        assert problem["request_id"] == response.headers["x-request-id"]


def test_a_validation_error_names_where_and_why_but_never_what_was_sent(
    client: TestClient,
) -> None:
    sent = "kept-out-" * 200

    response = client.post("/v1/auth/login", json={"password": sent, "remember": True})

    problem = response.json()
    locations = {tuple(error["location"]) for error in problem["errors"]}
    assert (response.status_code, response.headers["content-type"]) == (422, PROBLEM)
    assert locations == {("body", "password"), ("body", "remember")}
    assert "kept-out-" not in response.text


def test_a_failure_answers_a_problem_with_its_request_id_and_nothing_of_the_error(
    container: Container, keyring_backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(service: str, username: str) -> str | None:
        raise RuntimeError("the keyring broke while reading a-secret-value")

    monkeypatch.setattr(keyring_backend, "get_password", broken)
    app = create_app(container, built_web_app=None)
    with TestClient(app, base_url=LOOPBACK, raise_server_exceptions=False) as client:
        logged_in(client, container)
        response = client.get("/v1/settings")

    problem = response.json()
    assert (response.status_code, response.headers["content-type"]) == (500, PROBLEM)
    assert problem["request_id"] == response.headers["x-request-id"]
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "a-secret-value" not in response.text


def test_a_host_other_than_the_loopback_is_refused(container: Container) -> None:
    app = create_app(container, built_web_app=None)
    with TestClient(app, base_url="http://fefat.example") as foreign:
        refused = foreign.get("/v1/healthz")
    with TestClient(app, base_url="http://localhost:8765") as local:
        answered = local.get("/v1/healthz")

    assert (refused.status_code, answered.status_code) == (400, 200)
