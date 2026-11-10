"""`fefat up` of step 4.2 (D-86): it migrates the database, asks for a password on its first run,
configures the server's log, and runs uvicorn in its own process on the address and port of
`config.toml`, never trusting forwarded headers; a bind address other than the loopback is
refused before anything starts (Done means 1 and 2)."""

import getpass
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from fefat.config import FefatPaths, resolve_paths
from fefat_app.cli import main
from fefat_app.http import web_app

PASSWORD = "horse battery"


class ServerCall:
    """What `fefat up` gave `uvicorn.run`, which the tests make return at once."""

    def __init__(self) -> None:
        self.calls: list[tuple[Callable[..., Any], dict[str, Any]]] = []

    def __call__(self, app: Callable[..., Any], **options: Any) -> None:
        self.calls.append((app, options))


pytestmark = pytest.mark.usefixtures("root_log_put_back")
"""`fefat up` configures the process's log, which each test gets back as it was."""


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> ServerCall:
    call = ServerCall()
    monkeypatch.setattr(uvicorn, "run", call)
    return call


@pytest.fixture
def paths() -> FefatPaths:
    found = resolve_paths(os.environ)
    found.home.mkdir(parents=True)
    return found


def typed(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    """`answers` as what the trader types at each prompt that does not echo it; the prompts."""
    prompts: list[str] = []
    remaining = iter(answers)

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(remaining)

    monkeypatch.setattr(getpass, "getpass", answer)
    return prompts


def test_up_serves_the_app_on_the_loopback_at_the_port_of_config_toml(
    served: ServerCall,
    paths: FefatPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Done means 1: `fefat up` starts, and `/v1/healthz` answers.
    paths.config_file.write_text("port = 8790\n", encoding="utf-8")
    prompts = typed(monkeypatch, PASSWORD, PASSWORD)

    code = main(["up"])

    ((app, options),) = served.calls
    printed = capsys.readouterr().out
    assert code == 0
    assert len(prompts) == 2
    assert (options["host"], options["port"]) == ("127.0.0.1", 8790)
    assert (options["log_config"], options["proxy_headers"]) == (None, False)
    assert (options["access_log"], options["server_header"]) == (False, False)
    # Step 4.4: an open event stream holds Ctrl+C three seconds at most.
    assert options["timeout_graceful_shutdown"] == 3
    assert "http://127.0.0.1:8790" in printed
    assert str(paths.logs_dir / "server.log") in printed
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/v1/healthz").json() == {"status": "ok"}
        assert client.post("/v1/auth/login", json={"password": PASSWORD}).status_code == 200


def test_up_asks_for_no_password_once_one_is_set(
    served: ServerCall, paths: FefatPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    typed(monkeypatch, PASSWORD, PASSWORD)
    main(["up"])
    prompts = typed(monkeypatch)

    code = main(["up"])

    assert (code, prompts, len(served.calls)) == (0, [], 2)


def test_up_refuses_two_passwords_that_differ(
    served: ServerCall,
    paths: FefatPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typed(monkeypatch, PASSWORD, "another one")

    code = main(["up"])

    assert (code, served.calls) == (1, [])
    assert capsys.readouterr().err == (
        "fefat: Expected the same password twice, got two that differ.\n"
    )


def test_up_refuses_a_bind_address_other_than_the_loopback(
    served: ServerCall, paths: FefatPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    # Done means 2: a bind address other than localhost refused.
    paths.config_file.write_text("bind_address = '0.0.0.0'\n", encoding="utf-8")

    code = main(["up"])

    assert (code, served.calls) == (1, [])
    assert capsys.readouterr().err.startswith(
        f"fefat: Expected {paths.config_file} to hold FEAT's settings, got: "
    )
    assert not paths.database_file.exists()


def test_up_serves_the_built_web_app_where_there_is_one(
    served: ServerCall, paths: FefatPaths, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>FEFAT</title>", encoding="utf-8")
    monkeypatch.setattr(web_app, "WEB_APP_DIR", dist)
    typed(monkeypatch, PASSWORD, PASSWORD)

    main(["up"])

    ((app, _),) = served.calls
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/runs").text == "<title>FEFAT</title>"


def test_up_removes_what_executions_left_more_than_a_day_ago(
    served: ServerCall, paths: FefatPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Phase 4 exit (`BACKLOG.md`, what the executor leaves in `cache/`): a runner's log or an
    # execution's folder that Windows still held, or that a server stopped mid-execution left,
    # stayed under `cache/executions` for ever.
    typed(monkeypatch, PASSWORD, PASSWORD)
    paths.executions_dir.mkdir(parents=True)
    old_folder = paths.executions_dir / "execution-left"
    old_folder.mkdir()
    (old_folder / "result.json").write_text("{}", encoding="utf-8")
    old_log = paths.executions_dir / "runner-left.log"
    old_log.write_text("", encoding="utf-8")
    fresh = paths.executions_dir / "execution-running"
    fresh.mkdir()
    two_days_ago = time.time() - 2 * 24 * 3600
    for left in (old_folder, old_log):
        os.utime(left, (two_days_ago, two_days_ago))

    main(["up"])

    assert sorted(paths.executions_dir.iterdir()) == [fresh]


def test_up_refused_for_its_bind_address_removes_nothing(
    served: ServerCall, paths: FefatPaths
) -> None:
    # The Phase 4 exit's review of its own changes: the sweep of what executions left ran before
    # config.toml was read, so a start refused for its bind address had removed files already.
    paths.config_file.write_text("bind_address = '0.0.0.0'\n", encoding="utf-8")
    paths.executions_dir.mkdir(parents=True)
    left = paths.executions_dir / "runner-left.log"
    left.write_text("", encoding="utf-8")
    two_days_ago = time.time() - 2 * 24 * 3600
    os.utime(left, (two_days_ago, two_days_ago))

    code = main(["up"])

    assert (code, served.calls) == (1, [])
    assert left.exists()
