"""What the local server's tests share beside their fixtures (step 4.2): the password they set,
when their clock starts, a clock that stands still until a test moves it, and the bytes the
database keeps on disk."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fefat.config import resolve_paths

PASSWORD = "horse battery"
"""The password the tests set; short, so that the commit guard never reads it as a secret."""
STARTED_AT = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
"""When the tests' clock starts."""


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
