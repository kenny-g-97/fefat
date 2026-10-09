import os
import re
import sys
from pathlib import Path

import platformdirs
import pytest

from fefat.config import FefatPaths, resolve_paths


def test_without_variables_home_is_the_user_data_folder_with_the_data_inside_it() -> None:
    paths = resolve_paths({})

    expected_home = platformdirs.user_data_path("FEFAT", appauthor=False)
    assert paths == FefatPaths(home=expected_home, data_dir=expected_home / "data")
    if sys.platform == "win32":
        assert expected_home == Path(os.environ["LOCALAPPDATA"]) / "FEFAT"


def test_fefat_home_moves_the_default_data_folder_with_it(tmp_path: Path) -> None:
    paths = resolve_paths({"FEFAT_HOME": str(tmp_path)})

    assert paths == FefatPaths(home=tmp_path, data_dir=tmp_path / "data")


def test_fefat_data_dir_points_the_market_data_at_another_folder(tmp_path: Path) -> None:
    market_data = tmp_path / "market-data"

    paths = resolve_paths(
        {"FEFAT_HOME": str(tmp_path / "home"), "FEFAT_DATA_DIR": str(market_data)}
    )

    assert paths == FefatPaths(home=tmp_path / "home", data_dir=market_data)


@pytest.mark.parametrize("variable", ["FEFAT_HOME", "FEFAT_DATA_DIR"])
@pytest.mark.parametrize("value", ["", "data", "./FEFAT"])
def test_an_empty_or_relative_folder_is_refused(variable: str, value: str) -> None:
    expected = f"Expected {variable} to be an absolute path, got '{value}'"

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolve_paths({variable: value})


def test_resolving_creates_nothing(tmp_path: Path) -> None:
    resolve_paths({"FEFAT_HOME": str(tmp_path / "home")})

    assert list(tmp_path.iterdir()) == []
