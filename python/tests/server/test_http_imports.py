"""The import wizard over the API (step 5.12, `01-architecture.md` section 7), through the app's
process pool of one worker: a file's table and what its import would do are read in the
executor's runners, and the import runs in the pool's worker and its runner, never in the server
(Done means 2); a profile given whole is kept once its import has written, and a second file of
its layout then imports by the profile's name alone, without any mapping (Done means 3); a file
read in the wrong time zone is answered with its offset, which the wizard's review names; and
an upload, a profile, or a path that is not the wizard's to read is refused."""

import gzip
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

import fefat_app.executor.imports as runner_imports
import fefat_app.services.imports as imports_service
from export_samples import PRESETS, SAMPLES, sample_lines, written_export
from fefat.config import Settings, resolve_paths
from fefat.market.importers import databento, file_import, tabular
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.execution import ExecutionLimits
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from local_server import logged_in
from test_executor import MIB, PEAK_MEMORY, printed, ran

DEADLINE_SECONDS = 240
NINJATRADER_SAMPLE = SAMPLES["ninjatrader"][0]
OCTETS = {"Content-Type": "application/octet-stream"}
ES_MINUTES = {"provider": "ninjatrader", "schema_name": "ohlcv-1m", "root": "ES"}


@pytest.fixture
def container(container: Container, tmp_path: Path) -> Container:
    """The server's container with an import root beside the test's home."""
    settings = Settings(import_roots=(tmp_path / "exports",))
    return replace(
        container, settings=settings, imports=replace(container.imports, settings=settings)
    )


def refused_in_this_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every importer and the table's reader, wherever this process could call them, raising."""

    def refused(*_: object, **__: object) -> object:
        raise AssertionError("Expected the import read in the executor, got it in the server.")

    for module, names in (
        (file_import, ("preview_file", "import_file", "read_table")),
        (databento, ("preview_databento", "import_databento")),
        (tabular, ("read_table",)),
        (
            runner_imports,
            ("preview_file", "import_file", "preview_databento", "import_databento", "read_table"),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, refused)


def uploaded(client: TestClient, csrf: dict[str, str], path: Path) -> str:
    """The id of `path` kept as an upload."""
    response = client.post(
        "/v1/uploads",
        params={"name": path.name},
        content=path.read_bytes(),
        headers={**csrf, **OCTETS},
    )
    assert response.status_code == 201, response.text
    upload_id: str = response.json()["id"]
    return upload_id


def ended(client: TestClient, job_id: str) -> dict[str, Any]:
    """The job once it has ended."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while True:
        job: dict[str, Any] = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        assert time.monotonic() < deadline, f"Expected the import to end, got {job['status']}."
        time.sleep(0.2)


def stored_bars() -> int:
    store = Store(resolve_paths(os.environ).data_dir)
    files = [store.folder / each.partition.relative_path() for each in store.list_partitions()]
    return sum(pl.read_parquet(file).height for file in files)


def test_a_preview_and_an_import_run_in_the_executor_never_in_the_server(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Done means 2: the server's process holds every importer refusing, and yet the table, the
    # preview, and the import all answer.
    refused_in_this_process(monkeypatch)
    csrf = logged_in(client, container)
    source = {"kind": "upload", "upload_id": uploaded(client, csrf, NINJATRADER_SAMPLE)}
    asked = {"kind": "file", "source": source, "profile": {"kind": "named", "name": "ninjatrader"}}

    table = client.post(
        "/v1/imports/preview", json={"kind": "table", "source": source}, headers=csrf
    )
    preview = client.post("/v1/imports/preview", json=asked, headers=csrf)
    started = client.post("/v1/imports", json=asked, headers=csrf)
    job = ended(client, started.json()["id"])

    assert table.status_code == 200, table.text
    assert (table.json()["kind"], table.json()["layout"]) == (
        "table",
        {"delimiter": ";", "header": False},
    )
    assert table.json()["rows_total"] == len(sample_lines("ninjatrader"))
    assert preview.status_code == 200, preview.text
    assert (preview.json()["kind"], preview.json()["verdict"]) == ("file", "imports")
    assert preview.json()["dataset"] == ES_MINUTES
    assert started.status_code == 202
    assert job["status"] == "succeeded", job["error"]
    (written,) = job["result"]["datasets"]
    assert written["dataset"] == ES_MINUTES
    assert written["records_added"] == stored_bars() == len(sample_lines("ninjatrader"))
    assert [report["root"] for report in job["result"]["reports"]] == ["ES"]
    assert not (resolve_paths(os.environ).uploads_dir / source["upload_id"]).exists()


def test_a_saved_profile_imports_a_second_file_of_its_layout_without_any_mapping(
    client: TestClient, container: Container, tmp_path: Path
) -> None:
    # Done means 3: the profile the wizard built is kept once its import has written, and a
    # later export in the same layout names it alone.
    lines = sample_lines("ninjatrader")
    first = written_export(tmp_path / "chosen", NINJATRADER_SAMPLE.name, lines[:2000])
    second = written_export(tmp_path / "exports" / "later", NINJATRADER_SAMPLE.name, lines[2000:])
    profile = {
        **PRESETS["ninjatrader"].model_dump(mode="json"),
        "name": "my-ninjatrader",
        "description": "My NinjaTrader 8 minute bars, semicolons, no header, UTC",
    }
    csrf = logged_in(client, container)
    given = {
        "kind": "file",
        "source": {"kind": "upload", "upload_id": uploaded(client, csrf, first)},
        "profile": {"kind": "given", "profile": profile},
    }
    named = {
        "kind": "file",
        "source": {"kind": "path", "path": str(second)},
        "profile": {"kind": "named", "name": "my-ninjatrader"},
    }

    first_job = ended(client, client.post("/v1/imports", json=given, headers=csrf).json()["id"])
    listed = client.get("/v1/import-profiles").json()
    preview = client.post("/v1/imports/preview", json=named, headers=csrf).json()
    second_job = ended(client, client.post("/v1/imports", json=named, headers=csrf).json()["id"])

    assert first_job["status"] == "succeeded", first_job["error"]
    assert first_job["result"]["profile_kept"] is True
    assert (resolve_paths(os.environ).profiles_dir / "my-ninjatrader.yaml").is_file()
    assert [(each["origin"], each["profile"]["name"]) for each in listed][-1] == (
        "saved",
        "my-ninjatrader",
    )
    assert (preview["verdict"], preview["profile"]) == ("imports", "my-ninjatrader")
    assert second_job["status"] == "succeeded", second_job["error"]
    assert second_job["result"]["profile_kept"] is False
    assert second_job["result"]["datasets"][0]["records_added"] == len(lines) - 2000
    assert stored_bars() == len(lines)


def test_several_files_import_in_one_job_with_one_quality_report(
    client: TestClient, container: Container, tmp_path: Path
) -> None:
    # D-102: NinjaTrader writes a file per contract, so the files go in one job, whose result is
    # the server's sum; a file left out keeps its upload, and says why.
    lines = sample_lines("ninjatrader")
    bars = len(lines)
    june = written_export(tmp_path / "chosen", "ES 06-26.Last.txt", lines)
    unnamed = written_export(tmp_path / "chosen", "bars.txt", lines)
    csrf = logged_in(client, container)
    ids = [uploaded(client, csrf, path) for path in (NINJATRADER_SAMPLE, june, unnamed)]
    asked = {
        "kind": "files",
        "sources": [{"kind": "upload", "upload_id": each} for each in ids],
        "profile": {"kind": "named", "name": "ninjatrader"},
    }

    started = client.post("/v1/imports", json=asked, headers=csrf)
    job = ended(client, started.json()["id"])

    assert started.status_code == 202, started.text
    assert job["status"] == "succeeded", job["error"]
    result = job["result"]
    (written,) = result["datasets"]
    assert written["dataset"] == ES_MINUTES
    assert written["records_added"] == stored_bars() == 2 * bars
    assert [report["root"] for report in result["reports"]] == ["ES"]
    assert (result["round"]["files_imported"], result["round"]["files_imported_before"]) == (2, 0)
    (left,) = result["round"]["not_imported"]
    assert (left["upload_id"], left["file_name"]) == (ids[2], "bars.txt")
    assert "Expected the contract of the records of bars.txt" in left["message"]
    uploads_dir = resolve_paths(os.environ).uploads_dir
    assert [(uploads_dir / each).exists() for each in ids] == [False, False, True]


def test_a_file_read_in_the_wrong_time_zone_is_answered_with_its_offset(
    client: TestClient, container: Container
) -> None:
    # The premise of the wizard's time-zone correction: UTC bars read as Chicago's run six hours
    # late, which points at the time zone, and the import would be refused.
    csrf = logged_in(client, container)
    asked = {
        "kind": "file",
        "source": {"kind": "upload", "upload_id": uploaded(client, csrf, NINJATRADER_SAMPLE)},
        "profile": {"kind": "named", "name": "ninjatrader"},
        "time_zone": "America/Chicago",
    }

    preview = client.post("/v1/imports/preview", json=asked, headers=csrf).json()

    assert preview["verdict"] == "refused"
    (offset,) = preview["offsets"]
    assert (offset["cause"], offset["direction"], offset["duration"]) == (
        "time-zone",
        "late",
        "6 hours",
    )
    assert preview["merge"] is None


def test_a_profile_given_under_a_presets_name_is_refused_before_anything_runs(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    profile = {**PRESETS["ninjatrader"].model_dump(mode="json"), "description": "Another"}
    asked = {
        "kind": "file",
        "source": {"kind": "upload", "upload_id": uploaded(client, csrf, NINJATRADER_SAMPLE)},
        "profile": {"kind": "given", "profile": profile},
    }

    response = client.post("/v1/imports", json=asked, headers=csrf)

    assert response.status_code == 409
    assert [job for job in client.get("/v1/jobs").json() if job["kind"] == "import"] == []


def test_a_profile_is_named_among_the_presets_and_the_saved_ones_never_as_a_path(
    client: TestClient, container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `load_profile` reads a name ending in .yaml as a path: a request's name never reaches it.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evil.yaml").write_text(PRESETS["ninjatrader"].model_dump_json(), encoding="utf-8")
    csrf = logged_in(client, container)
    asked = {
        "kind": "file",
        "source": {"kind": "upload", "upload_id": uploaded(client, csrf, NINJATRADER_SAMPLE)},
        "profile": {"kind": "named", "name": "evil.yaml"},
    }

    response = client.post("/v1/imports/preview", json=asked, headers=csrf)

    assert response.status_code == 404
    assert "Expected the name of a preset or a saved profile" in response.json()["detail"]


def test_a_saved_profile_broken_by_hand_refuses_only_what_names_it_with_409(
    client: TestClient, container: Container
) -> None:
    # A preset still reads, and a name only a saved profile could hold is refused in the file's
    # words, where both answered a bare 500 (from the reviews).
    profiles = resolve_paths(os.environ).profiles_dir
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "mine.yaml").write_text("name: [unclosed", encoding="utf-8")
    csrf = logged_in(client, container)
    source = {"kind": "upload", "upload_id": uploaded(client, csrf, NINJATRADER_SAMPLE)}

    def named(name: str) -> dict[str, Any]:
        return {"kind": "file", "source": source, "profile": {"kind": "named", "name": name}}

    preset = client.post("/v1/imports/preview", json=named("ninjatrader"), headers=csrf)
    saved = client.post("/v1/imports/preview", json=named("mine"), headers=csrf)

    assert preset.status_code == 200, preset.text
    assert saved.status_code == 409
    assert "mine.yaml" in saved.json()["detail"]


def test_an_upload_not_kept_is_refused_with_404_and_a_path_outside_the_roots_with_403(
    client: TestClient, container: Container, tmp_path: Path
) -> None:
    csrf = logged_in(client, container)
    outside = written_export(tmp_path / "elsewhere", "x.csv", ["a,b", "1,2"])
    unknown = {"kind": "upload", "upload_id": "0193a000-0000-7000-8000-000000000000"}

    missing = client.post(
        "/v1/imports/preview", json={"kind": "table", "source": unknown}, headers=csrf
    )
    refused = client.post(
        "/v1/imports/preview",
        json={"kind": "table", "source": {"kind": "path", "path": str(outside)}},
        headers=csrf,
    )

    assert missing.status_code == 404
    assert "choose the file again" in missing.json()["detail"]
    assert refused.status_code == 403
    assert str(tmp_path / "exports") in refused.json()["detail"]


def test_what_a_preview_quotes_of_a_file_stays_out_of_the_servers_log(
    client: TestClient, container: Container, server_log: Path
) -> None:
    csrf = logged_in(client, container)
    upload = uploaded(client, csrf, NINJATRADER_SAMPLE)

    table = client.post(
        "/v1/imports/preview",
        json={"kind": "table", "source": {"kind": "upload", "upload_id": upload}},
        headers=csrf,
    )

    first_row = table.json()["rows"][0]
    assert first_row[0] == "20260304 230100"
    logged = server_log.read_text(encoding="utf-8")
    assert "/v1/imports/preview" in logged
    assert all(cell not in logged for cell in first_row if cell is not None)
    assert NINJATRADER_SAMPLE.name not in logged


def test_an_archive_that_unpacks_past_the_previews_memory_is_refused_while_the_server_answers(
    client: TestClient,
    container: Container,
    executor: SubprocessExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A megabyte that unpacks to a gibibyte of zeros, read under a memory limit a quarter of a
    # GiB above what a runner took to start, measured first, as the executor's own test does, so
    # that the test holds where the limit counts the address space: on Linux a runner holds
    # most of 512 MiB before it reads a byte. The runner fails, the server does not.
    started_with = int(printed(ran(executor, PEAK_MEMORY)[0]))
    limited = ExecutionLimits(timeout_seconds=300, memory_bytes=started_with + 256 * MIB)
    monkeypatch.setattr(imports_service, "PREVIEW_LIMITS", limited)
    bomb = tmp_path / "bars.csv.gz"
    with gzip.open(bomb, "wb", compresslevel=9) as packed:
        for _ in range(1024):
            packed.write(bytes(1024 * 1024))
    csrf = logged_in(client, container)
    source = {"kind": "upload", "upload_id": uploaded(client, csrf, bomb)}

    preview = client.post(
        "/v1/imports/preview", json={"kind": "table", "source": source}, headers=csrf
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["kind"] == "refused"
    gibibytes = limited.memory_bytes / 1024**3
    assert f"within {gibibytes:g} GiB of memory" in preview.json()["message"]
    assert client.get("/v1/healthz").status_code == 200
