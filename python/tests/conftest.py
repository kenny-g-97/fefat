"""What every test shares: FEFAT's own folders inside a temporary folder."""

import shutil
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Point `FEFAT_HOME` and `FEFAT_DATA_DIR` into a temporary folder before collection, so
    that module-level code and wide-scoped fixtures, which run before any per-test fixture,
    never see the default folder, where the trader's real data lives."""
    folder = Path(tempfile.mkdtemp(prefix="fefat-tests-"))
    environment = pytest.MonkeyPatch()
    environment.setenv("FEFAT_HOME", str(folder / "fefat-home"))
    environment.setenv("FEFAT_DATA_DIR", str(folder / "fefat-data"))
    config.add_cleanup(environment.undo)
    config.add_cleanup(lambda: shutil.rmtree(folder, ignore_errors=True))


@pytest.fixture(autouse=True)
def fefat_folders_in_tmp_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point `FEFAT_HOME` and `FEFAT_DATA_DIR` into each test's own temporary folder."""
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path / "fefat-home"))
    monkeypatch.setenv("FEFAT_DATA_DIR", str(tmp_path / "fefat-data"))
