"""`POST /v1/uploads` (step 5.12, D-101, the plan's Security section): the file the wizard chose,
sent as the request's body, kept in a folder of its own with its name, size, and SHA-256, once
the login and the CSRF token have passed and before which no byte of the body is read; a body of
another media type, a name the server does not keep, an empty file, and a file past the
configured limit are refused, nothing kept, while every other route keeps its limit of 1 MiB."""

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fefat.config import Settings, resolve_paths
from fefat_app.container import Container
from local_server import logged_in

OCTETS = {"Content-Type": "application/octet-stream"}
EXPORT = b"20260304 230100;6810.25;6811;6809.75;6810.5;12\n"
MEBIBYTE = 1024 * 1024
LIMIT = 2 * MEBIBYTE
"""The upload limit of these tests, past every other route's mebibyte, so that the route's own
limit is what takes a file between the two."""


@pytest.fixture
def container(container: Container) -> Container:
    """The server's container with an upload limit of two mebibytes."""
    settings = Settings(upload_megabytes=LIMIT // MEBIBYTE)
    return replace(
        container, settings=settings, imports=replace(container.imports, settings=settings)
    )


def uploads_kept() -> list[Path]:
    folder = resolve_paths(os.environ).uploads_dir
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_a_file_is_kept_in_its_own_folder_with_its_name_size_and_hash(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/uploads",
        params={"name": "ES 03-26.Last.txt"},
        content=EXPORT,
        headers={**csrf, **OCTETS},
    )

    assert response.status_code == 201, response.text
    kept = response.json()
    (folder,) = uploads_kept()
    assert folder.name == kept["id"]
    assert sorted(path.name for path in folder.iterdir()) == ["ES 03-26.Last.txt", "upload.json"]
    assert (folder / "ES 03-26.Last.txt").read_bytes() == EXPORT
    assert (kept["name"], kept["size"], kept["sha256"]) == (
        "ES 03-26.Last.txt",
        len(EXPORT),
        hashlib.sha256(EXPORT).hexdigest(),
    )
    assert json.loads((folder / "upload.json").read_bytes()) == kept


def test_an_upload_without_a_login_is_refused_before_its_body_is_read(
    client: TestClient,
) -> None:
    read: list[int] = []

    def body() -> Iterator[bytes]:
        for _ in range(2):
            read.append(MEBIBYTE)
            yield bytes(MEBIBYTE)

    response = client.post(
        "/v1/uploads", params={"name": "big.csv"}, content=body(), headers=OCTETS
    )

    assert response.status_code == 401
    assert read == []
    assert uploads_kept() == []


def test_an_upload_by_cookie_without_the_csrf_token_is_refused(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    response = client.post("/v1/uploads", params={"name": "x.csv"}, content=EXPORT, headers=OCTETS)

    assert response.status_code == 403
    assert uploads_kept() == []


def test_a_body_of_another_media_type_is_refused(client: TestClient, container: Container) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/uploads",
        params={"name": "x.csv"},
        content=EXPORT,
        headers={**csrf, "Content-Type": "text/csv"},
    )

    assert response.status_code == 415
    assert uploads_kept() == []


@pytest.mark.parametrize("name", ["D:x.csv", "a.txt:b.csv", "NUL .csv", "a\\b.csv", "x.exe"])
def test_a_name_the_server_does_not_keep_is_refused_and_nothing_is_kept(
    name: str, client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/uploads", params={"name": name}, content=EXPORT, headers={**csrf, **OCTETS}
    )

    assert response.status_code == 400
    assert "rename the file" in response.json()["detail"]
    assert uploads_kept() == []


def test_an_empty_file_is_refused_and_nothing_is_kept(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/uploads", params={"name": "x.csv"}, content=b"", headers={**csrf, **OCTETS}
    )

    assert response.status_code == 400
    assert "at least one byte" in response.json()["detail"]
    assert uploads_kept() == []


@pytest.mark.parametrize("chunked", [False, True])
def test_a_file_past_the_limit_is_refused_and_nothing_is_kept(
    chunked: bool, client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    past = bytes(LIMIT + 1)

    def chunks() -> Iterator[bytes]:
        yield past[:LIMIT]
        yield past[LIMIT:]

    response = client.post(
        "/v1/uploads",
        params={"name": "x.csv"},
        content=chunks() if chunked else past,
        headers={**csrf, **OCTETS},
    )

    assert response.status_code == 413
    assert uploads_kept() == []


def test_a_file_within_the_limit_is_kept(client: TestClient, container: Container) -> None:
    # Past every other route's mebibyte: the route's own limit takes it (from the reviews).
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/uploads", params={"name": "x.csv"}, content=bytes(LIMIT), headers={**csrf, **OCTETS}
    )

    assert response.status_code == 201


def test_every_other_route_keeps_its_limit_of_a_mebibyte(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/imports/preview",
        content=b'{"kind": "table", "source": {"kind": "path", "path": "'
        + b"x" * MEBIBYTE
        + b'"}}',
        headers={**csrf, "Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_an_upload_id_is_read_as_one_before_any_folder_is(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    response = client.post(
        "/v1/imports/preview",
        json={"kind": "table", "source": {"kind": "upload", "upload_id": "../../config"}},
        headers=csrf,
    )

    assert response.status_code == 422
