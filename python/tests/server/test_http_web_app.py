"""The built web app served by the local server of step 4.2 (D-86): its files at `/`, every other
page path a GET or HEAD asks for answered with its `index.html`, so that a reload on a page of
the app works, and nothing under `/v1/` or outside its folder."""

import errno
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

from fefat_app.container import Container
from fefat_app.http.app import create_app
from fefat_app.http.web_app import WEB_APP_DIR
from local_server import LOOPBACK

INDEX = "<!doctype html><title>FEFAT</title>"
SCRIPT = "console.log('FEFAT');"
PROBLEM = "application/problem+json"


@pytest.fixture
def built_web_app(tmp_path: Path) -> Path:
    """A web app as `pnpm --dir web build` would leave it, beside a file outside it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside the web app", encoding="utf-8")
    return dist


@pytest.fixture
def web_client(container: Container, built_web_app: Path) -> Iterator[TestClient]:
    with TestClient(create_app(container, built_web_app), base_url=LOOPBACK) as opened:
        yield opened


def test_the_web_app_is_served_with_its_files(web_client: TestClient) -> None:
    assert web_client.get("/").text == INDEX
    assert web_client.get("/assets/app.js").text == SCRIPT


@pytest.mark.parametrize("path", ["/runs/0193f0a2", "/settings"])
def test_a_reload_on_a_page_of_the_web_app_answers_its_index(
    web_client: TestClient, path: str
) -> None:
    page = web_client.get(path)

    assert (page.status_code, page.text) == (200, INDEX)
    assert web_client.head(path).status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("path", ["/v1", "/v1/nothing"])
def test_a_path_under_v1_that_the_api_does_not_own_is_a_problem(
    web_client: TestClient, method: str, path: str
) -> None:
    response = web_client.request(method, path)

    assert (response.status_code, response.headers["content-type"]) == (404, PROBLEM)


def test_a_wrong_method_on_an_api_route_is_405_as_without_a_web_app(
    web_client: TestClient,
) -> None:
    response = web_client.delete("/v1/healthz")

    assert (response.status_code, response.headers["allow"]) == (405, "GET")


@pytest.mark.parametrize("path", ["/assets/index-0ld.js", "/favicon.ico"])
def test_a_missing_file_is_a_404_rather_than_the_index(web_client: TestClient, path: str) -> None:
    response = web_client.get(path)

    assert (response.status_code, response.headers["content-type"]) == (404, PROBLEM)


def test_the_index_is_checked_again_at_each_load_and_the_files_are_not(
    web_client: TestClient,
) -> None:
    # A rebuild renames the scripts the index names, so a browser must not reuse an old index.
    assert web_client.get("/").headers["cache-control"] == "no-cache"
    assert web_client.get("/runs/0193f0a2").headers["cache-control"] == "no-cache"
    assert "cache-control" not in web_client.get("/assets/app.js").headers


@pytest.mark.parametrize("path", ["/x%22y", "/a|b"])
def test_a_page_path_windows_cannot_name_as_a_file_answers_the_index(
    web_client: TestClient, path: str
) -> None:
    response = web_client.get(path)

    assert (response.status_code, response.text) == (200, INDEX)


def test_a_failing_disk_stays_a_failure_rather_than_the_index(
    container: Container, built_web_app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = StaticFiles.lookup_path

    def failing(directory: StaticFiles, path: str) -> tuple[str, os.stat_result | None]:
        if path == "index.html":
            return found(directory, path)
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(StaticFiles, "lookup_path", failing)
    app = create_app(container, built_web_app)
    with TestClient(app, base_url=LOOPBACK, raise_server_exceptions=False) as client:
        response = client.get("/runs/0193f0a2")

    assert response.status_code == 500


def test_a_file_outside_the_web_app_is_never_served(web_client: TestClient) -> None:
    response = web_client.get("/%2e%2e/outside.txt")

    assert "outside the web app" not in response.text


def test_without_a_built_web_app_the_root_is_a_problem(client: TestClient) -> None:
    response = client.get("/")

    assert (response.status_code, response.headers["content-type"]) == (404, PROBLEM)


def test_the_server_looks_for_the_web_app_in_the_repositorys_web_dist() -> None:
    repository = Path(__file__).resolve().parents[3]

    assert repository / "web" / "dist" == WEB_APP_DIR
