"""What the local server's tests share beside their fixtures (step 4.2): the password they set,
when their clock starts, a clock that stands still until a test moves it, the bytes the database
keeps on disk, and the steps of a login through the API."""

import base64
import os
from datetime import UTC, datetime, timedelta
from http.cookies import Morsel, SimpleCookie
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from fefat.config import resolve_paths
from fefat_app.container import Container

PASSWORD = "horse battery"
"""The password the tests set; short, so that the commit guard never reads it as a secret."""
STARTED_AT = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
"""When the tests' clock starts."""
LOOPBACK = "http://127.0.0.1"
"""The address the tests' client calls the app at, the server's own."""


class SettableClock:
    """A clock that stands still until the test moves it."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now = self.now + by


def database_bytes() -> bytes:
    """Every byte of the test's database on disk, its write-ahead log included."""
    database_file = resolve_paths(os.environ).database_file
    log_file = Path(f"{database_file}-wal")
    kept = [database_file.read_bytes()]
    if log_file.exists():
        kept.append(log_file.read_bytes())
    return b"".join(kept)


def logged_in(client: TestClient, container: Container) -> dict[str, str]:
    """Set the password and log in through the API, whose cookie the client keeps from then on;
    the header with the session's CSRF token, which a change of state must carry."""
    container.logins.set_password(PASSWORD)
    response = client.post("/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def basic(password: str) -> dict[str, str]:
    """The `Authorization` header a browser sends after its prompt, with no user name."""
    encoded = base64.b64encode(f":{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def session_cookie(response: httpx2.Response) -> Morsel[str]:
    """The session cookie a response sets, with its attributes."""
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies["fefat_session"]
