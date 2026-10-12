"""What every test shares: FEFAT's own folders inside the test's temporary folder."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fefat_folders_in_tmp_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point `FEFAT_HOME` and `FEFAT_DATA_DIR` into the test's temporary folder: without them,
    `resolve_paths` would name the default folder, where the trader's real data lives."""
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path / "fefat-home"))
    monkeypatch.setenv("FEFAT_DATA_DIR", str(tmp_path / "fefat-data"))
