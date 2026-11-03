"""The store the leak detector's suites run on (step 3.4): ES's and NQ's 1-minute bars of February
2026 with a share of their minutes empty, written once for each module of the suite in place of
the folders each test gets (`python/tests/conftest.py`), since fifty validations read it."""

from collections.abc import Iterator

import pytest

from generated_minutes import february_store


@pytest.fixture(scope="module", autouse=True)
def fefat_folders_in_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    with february_store(tmp_path_factory.mktemp("leaks")):
        yield
