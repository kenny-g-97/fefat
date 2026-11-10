"""What every test shares: FEFAT's own folders inside a temporary folder, and no credential store
of the machine; for the server's tests, the process's log put back; and for the seeded
differential tests, draws that depend on their seed alone."""

import logging
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Point `FEFAT_HOME` and `FEFAT_DATA_DIR` into a temporary folder before collection, so
    that module-level code and wide-scoped fixtures, which run before any per-test fixture,
    never see the default folder, where the trader's real data lives; and keyring at its `fail`
    backend, so that a test that gives keyring no backend of its own is refused rather than
    reaching the machine's credential store (step 4.1)."""
    folder = Path(tempfile.mkdtemp(prefix="fefat-tests-"))
    environment = pytest.MonkeyPatch()
    environment.setenv("FEFAT_HOME", str(folder / "fefat-home"))
    environment.setenv("FEFAT_DATA_DIR", str(folder / "fefat-data"))
    environment.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    config.add_cleanup(environment.undo)
    config.add_cleanup(lambda: shutil.rmtree(folder, ignore_errors=True))


@pytest.fixture(autouse=True)
def fefat_folders_in_tmp_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point `FEFAT_HOME` and `FEFAT_DATA_DIR` into each test's own temporary folder."""
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path / "fefat-home"))
    monkeypatch.setenv("FEFAT_DATA_DIR", str(tmp_path / "fefat-data"))


@pytest.fixture
def root_log_put_back() -> Iterator[None]:
    """The process's log as it was before the test, for a test that configures the server's
    (`fefat_app.http.server_log`), whose open log file Windows would keep locked."""
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    yield
    for added in [destination for destination in root.handlers if destination not in before]:
        root.removeHandler(added)
        added.close()
    root.setLevel(level)


CHECKED_HYPOTHESIS = "6.170.14"
"""The Hypothesis whose reading of local constants `draws_of_the_seed_alone` was checked against."""


@pytest.fixture
def draws_of_the_seed_alone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hypothesis now and then draws a constant it read from the local modules imported so far,
    which differ with the tests run before, so that a seeded test draws other cases in the whole
    suite than alone; drawing from Hypothesis's own constants alone keeps a seed's cases the same
    wherever the test runs, as the differential tests' recorded seeds promise. It patches
    Hypothesis's internals, so another version is refused until it is checked again."""
    import hypothesis
    from hypothesis.internal.conjecture import providers
    from hypothesis.internal.constants_ast import Constants

    if hypothesis.__version__ != CHECKED_HYPOTHESIS:
        raise RuntimeError(
            f"Expected Hypothesis {CHECKED_HYPOTHESIS}, which draws_of_the_seed_alone was checked "
            f"against, got {hypothesis.__version__}: check that it still leaves out the local "
            "constants (hypothesis.internal.conjecture.providers), then update CHECKED_HYPOTHESIS."
        )
    monkeypatch.setattr(providers, "_get_local_constants", Constants)
    providers.CONSTANTS_CACHE.cache.clear()
    yield
    providers.CONSTANTS_CACHE.cache.clear()
