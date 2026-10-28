"""What every test shares: FEFAT's own folders inside a temporary folder; and for the seeded
differential tests, draws that depend on their seed alone."""

import shutil
import tempfile
from collections.abc import Iterator
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


@pytest.fixture
def draws_of_the_seed_alone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hypothesis now and then draws a constant it read from the local modules imported so far,
    which differ with the tests run before, so that a seeded test draws other cases in the whole
    suite than alone; drawing from Hypothesis's own constants alone keeps a seed's cases the same
    wherever the test runs, as the differential tests' recorded seeds promise."""
    from hypothesis.internal.conjecture import providers
    from hypothesis.internal.constants_ast import Constants

    monkeypatch.setattr(providers, "_get_local_constants", Constants)
    providers.CONSTANTS_CACHE.cache.clear()
    yield
    providers.CONSTANTS_CACHE.cache.clear()
