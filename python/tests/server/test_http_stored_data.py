"""A provider's data of a root deleted over the API (step 5.18, ADR-0023, Done means 7): `GET
/v1/stored-data/{provider}/{root}/deletion` says what a delete removes and how many saved runs
read the data, writing nothing; `DELETE /v1/stored-data/{provider}/{root}` deletes, refused with
404 where the store holds no such data, with 409 while a job is queued or running, an import
writes, or a file is held open, and with 403 without the session's CSRF header."""

import hashlib
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import fefat as ff
import fefat.market.stored_deletion
from fefat.config import resolve_paths
from fefat.market.store import IMPORT_LOCK_FILE_NAME, Store
from fefat.market.store_files import held_alone
from fefat_app.container import Container
from fefat_app.job_models import JobKind
from local_server import logged_in
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")
DELETION = "/v1/stored-data/synthetic/ES/deletion"
STORED_DATA = "/v1/stored-data/synthetic/ES"


def tree(folder: Path) -> dict[str, str]:
    """Every file under `folder`, by its path relative to it, with the SHA-256 of its bytes."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob("*")
        if path.is_file()
    }


def stored_pairs() -> set[tuple[str, str]]:
    store = Store(resolve_paths(os.environ).data_dir)
    return {(dataset.provider, dataset.root) for dataset in store.list_datasets()}


def test_the_deletion_says_what_goes_and_the_runs_that_read_it_and_writes_nothing(
    client: TestClient, container: Container
) -> None:
    store_with("ohlcv-1m")
    ff.backtest.run(breakout(), *WINDOW)
    logged_in(client, container)
    data_dir = resolve_paths(os.environ).data_dir
    before = tree(data_dir)

    answer = client.get(DELETION)
    of_bitcoin = client.get("/v1/stored-data/synthetic/BTCUSDT-PERP/deletion")
    unknown = client.get("/v1/stored-data/synthetic/MES/deletion")

    assert answer.status_code == 200
    assert answer.json() == {
        "provider": "synthetic",
        "root": "ES",
        "imported_files": 0,
        "kept_files": [],
        "quality_report": False,
        "saved_runs": 1,
    }
    assert of_bitcoin.json()["saved_runs"] == 0
    assert unknown.status_code == 404
    assert unknown.json()["detail"].startswith("Expected stored data of MES from synthetic")
    assert tree(data_dir) == before


def test_a_delete_with_the_csrf_header_deletes_and_the_catalog_no_longer_lists_it(
    client: TestClient, container: Container
) -> None:
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)

    without_the_csrf_header = client.delete(STORED_DATA)
    kept = stored_pairs()
    deleted = client.delete(STORED_DATA, headers=csrf)
    again = client.delete(STORED_DATA, headers=csrf)

    listed = {(each["provider"], each["root"]) for each in client.get("/v1/datasets").json()}
    assert without_the_csrf_header.status_code == 403
    assert ("synthetic", "ES") in kept
    assert deleted.status_code == 204
    assert stored_pairs() == {("synthetic", "BTCUSDT-PERP")}
    assert listed == {("synthetic", "BTCUSDT-PERP")}
    assert again.status_code == 404
    assert client.get(DELETION).status_code == 404


def test_a_delete_while_a_job_is_queued_is_refused_with_409(
    client: TestClient, container: Container
) -> None:
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)
    container.jobs.records.add(JobKind.DEMO, {"seconds": 1}, 3, container.jobs.clock())

    refused = client.delete(STORED_DATA, headers=csrf)

    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Expected no job queued or running, got 1 job")
    assert ("synthetic", "ES") in stored_pairs()


def test_a_delete_while_an_import_writes_is_refused_with_409(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)
    monkeypatch.setattr(fefat.market.stored_deletion, "DELETE_WAIT", timedelta(milliseconds=100))
    lock = resolve_paths(os.environ).data_dir / IMPORT_LOCK_FILE_NAME

    with held_alone(lock, timedelta(seconds=1)):
        refused = client.delete(STORED_DATA, headers=csrf)

    assert refused.status_code == 409
    assert "an import writing to the store" in refused.json()["detail"]
    assert ("synthetic", "ES") in stored_pairs()


def test_a_delete_held_up_by_a_file_held_open_is_refused_with_409_and_finished_when_asked_again(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)

    def held_open(path: Any, *arguments: Any, **named: Any) -> None:
        raise PermissionError(13, "The process cannot access the file", str(path))

    with monkeypatch.context() as patched:
        patched.setattr(shutil, "rmtree", held_open)
        refused = client.delete(STORED_DATA, headers=csrf)
    finished = client.delete(STORED_DATA, headers=csrf)

    assert refused.status_code == 409
    assert "close the programs that read it" in refused.json()["detail"]
    assert finished.status_code == 204
    assert stored_pairs() == {("synthetic", "BTCUSDT-PERP")}
