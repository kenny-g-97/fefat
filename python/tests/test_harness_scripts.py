"""The scripts of step 4.3's harness: `scripts/e2e_server.py`, the seeded server of `just e2e`,
and `scripts/dev.py`, which `just dev` runs, on a home seeded alike unless one is named, and
which starts its server again when the source changes (step 5.1)."""

import http.server
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

import dev
import e2e_server
from fefat.backtest import saved_runs_in
from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.database.schema import opened_database


def test_the_seeded_home_is_made_afresh_with_its_port_and_the_fixtures(tmp_path: Path) -> None:
    home = tmp_path / "fefat-e2e"
    (home / "left-over").mkdir(parents=True)

    e2e_server.seeded_home(home, 8766)

    assert (home / "config.toml").read_text(encoding="utf-8") == "port = 8766\n"
    assert (home / "data" / "synthetic" / "MANIFEST.json").is_file()
    assert not (home / "left-over").exists()


def test_the_seeded_server_stops_before_it_starts_without_its_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as environment:
        environment.delenv("FEFAT_E2E_PORT", raising=False)

        with pytest.raises(SystemExit, match="Expected FEFAT_E2E_PORT in the environment"):
            e2e_server.main()


def test_dev_gives_up_on_a_server_that_ends_before_it_answers() -> None:
    server = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])

    assert dev.answered(server, "http://127.0.0.1:9/v1/healthz") is False
    assert server.returncode == 3


def test_a_home_that_cannot_be_wiped_stops_the_seeded_server_with_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "fefat-e2e"
    home.mkdir()

    def held(path: Path) -> None:
        raise PermissionError(f"[WinError 32] The process cannot access the file: {path}")

    with monkeypatch.context() as patched:
        patched.setattr(e2e_server.shutil, "rmtree", held)

        with pytest.raises(SystemExit, match="is the server of an earlier `just e2e`"):
            e2e_server.seeded_home(home, 8766)


def test_dev_seeds_a_throwaway_home_unless_a_home_is_named(tmp_path: Path) -> None:
    # Step 5.1, `01-architecture.md` section 9: the synthetic fixtures by default, a data folder
    # you name when you choose, and a home you name as it is.
    throwaway = Path(tempfile.gettempdir()) / "fefat-dev"

    assert dev.dev_home({}) == dev.DevHome(home=throwaway, data_dir=None)
    assert dev.dev_home({"FEFAT_DATA_DIR": str(tmp_path)}) == dev.DevHome(
        home=throwaway, data_dir=tmp_path
    )
    assert dev.dev_home({"FEFAT_HOME": str(tmp_path)}) is None


def test_the_source_stamp_changes_with_a_saved_added_or_renamed_file_and_not_a_cached_one(
    tmp_path: Path,
) -> None:
    # Step 5.1: `just dev` starts its server again when the stamp of the source changes.
    package = tmp_path / "src" / "fefat"
    (package / "__pycache__").mkdir(parents=True)
    module = package / "api.py"
    module.write_text("load = 1\n", encoding="utf-8")
    sources = (tmp_path / "src",)
    first = dev.source_stamp(sources)

    (package / "__pycache__" / "api.cpython-312.pyc").write_bytes(b"compiled")
    cached = dev.source_stamp(sources)
    later = module.stat().st_mtime_ns + 1_000_000_000
    os.utime(module, ns=(later, later))
    saved = dev.source_stamp(sources)
    (package / "status.py").write_text("datasets = 1\n", encoding="utf-8")
    added = dev.source_stamp(sources)
    module.rename(package / "loads.py")
    renamed = dev.source_stamp(sources)

    assert cached == first
    assert len({first, saved, added, renamed}) == 4


def test_the_source_stamp_of_a_folder_gone_mid_scan_is_empty(tmp_path: Path) -> None:
    # Step 5.1's review: a checkout that removes a package's folder must not end `just dev`.
    assert dev.source_stamp((tmp_path / "gone",)) == frozenset()


def test_dev_names_a_home_with_a_port_of_its_own_where_the_throwaway_ones_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 5.1's review: the throwaway home has no `config.toml` to set another port in.
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as other:
        port = other.server_address[1]
        threading.Thread(target=other.serve_forever, daemon=True).start()
        monkeypatch.delenv("FEFAT_HOME")
        monkeypatch.setattr(dev, "DEV_PORT", port)

        with pytest.raises(SystemExit, match="or name a FEFAT_HOME whose config"):
            dev.main()
        other.shutdown()


def test_dev_refuses_a_port_another_server_answers_on_before_starting_anything(
    tmp_path: Path,
) -> None:
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as other:
        port = other.server_address[1]
        threading.Thread(target=other.serve_forever, daemon=True).start()
        paths = resolve_paths(os.environ)
        paths.home.mkdir(parents=True, exist_ok=True)
        paths.config_file.write_text(f"port = {port}\n", encoding="utf-8")

        with pytest.raises(SystemExit, match=f"Expected port {port} free for fefat up"):
            dev.main()
        other.shutdown()


def test_the_seed_saves_the_demo_strategy_and_its_first_run_indexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.3 (D-93): the specs' `demo-run-01` is the first run of the strategy `demo` that
    # `GET /v1/runs` lists; the seed makes it through the SDK on the fixtures and indexes both as
    # `fefat db import-workspace` does, leaving no job. The seed sets the variables itself.
    for name in ("FEFAT_HOME", "FEFAT_DATA_DIR", "PYTHON_KEYRING_BACKEND"):
        monkeypatch.setenv(name, os.environ[name])

    e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")

    paths = resolve_paths(os.environ)
    with opened_database(paths.database_file) as engine:
        strategies = LibraryTables(engine, paths).strategies()
        runs = RunTables(engine, paths).newest(10)
        jobs = JobTables(engine).recent(10)
    (run,) = runs
    (saved,) = saved_runs_in(paths.runs_dir)
    assert [strategy.name for strategy in strategies] == ["demo"]
    assert run.strategy is not None
    assert (run.strategy.name, run.status, run.run_key) == ("demo", "succeeded", saved.hash)
    assert saved.record.summary.trades >= 3
    assert jobs == ()
