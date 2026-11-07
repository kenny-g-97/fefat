"""The scripts of step 4.3's harness: `scripts/e2e_server.py`, the seeded server of `just e2e`,
and `scripts/dev.py`, which `just dev` runs."""

import http.server
import os
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import dev
import e2e_server
from fefat.config import resolve_paths


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
