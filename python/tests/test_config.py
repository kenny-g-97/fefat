import os
import re
import sys
import tempfile
from pathlib import Path

import platformdirs
import pytest

from fefat.config import FefatPaths, resolve_paths

PATHS_WHEN_COLLECTED = resolve_paths(os.environ)


def test_without_variables_home_is_the_user_data_folder_with_the_data_inside_it() -> None:
    paths = resolve_paths({})

    expected_home = platformdirs.user_data_path("FEFAT", appauthor=False)
    assert paths == FefatPaths(home=expected_home, data_dir=expected_home / "data")
    assert paths.cache_dir == expected_home / "cache"
    if sys.platform == "win32":
        assert expected_home == Path(os.environ["LOCALAPPDATA"]) / "FEFAT"


def test_fefat_home_moves_the_default_data_folder_with_it(tmp_path: Path) -> None:
    paths = resolve_paths({"FEFAT_HOME": str(tmp_path)})

    assert paths == FefatPaths(home=tmp_path, data_dir=tmp_path / "data")


def test_runs_are_kept_in_the_default_workspace_under_fefat_home(tmp_path: Path) -> None:
    # Step 2.10 (`01-architecture.md` section 4): runs live with the workspace, not the data.
    paths = resolve_paths({"FEFAT_HOME": str(tmp_path), "FEFAT_DATA_DIR": str(tmp_path / "d")})

    assert paths.workspace_dir == tmp_path / "workspaces" / "default"
    assert paths.runs_dir == tmp_path / "workspaces" / "default" / "artifacts" / "runs"


def test_feature_versions_are_kept_in_the_default_workspace(tmp_path: Path) -> None:
    # Step 3.1 (`01-architecture.md` section 4): versions are files until the database of 4.1.
    paths = resolve_paths({"FEFAT_HOME": str(tmp_path)})

    assert paths.features_dir == tmp_path / "workspaces" / "default" / "features"


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


def test_tests_run_with_the_fefat_folders_inside_their_temporary_folder(tmp_path: Path) -> None:
    paths = resolve_paths(os.environ)

    assert paths == FefatPaths(home=tmp_path / "fefat-home", data_dir=tmp_path / "fefat-data")


def test_code_that_runs_before_any_fixture_sees_temporary_fefat_folders_too() -> None:
    temporary_folder = Path(tempfile.gettempdir())

    assert temporary_folder in PATHS_WHEN_COLLECTED.home.parents
    assert temporary_folder in PATHS_WHEN_COLLECTED.data_dir.parents


def test_the_quality_reports_live_in_the_data_folder(tmp_path: Path) -> None:
    paths = resolve_paths({"FEFAT_DATA_DIR": str(tmp_path / "market-data")})

    assert paths.reports_dir == tmp_path / "market-data" / "reports"


def test_the_apps_own_files_live_under_fefat_home_and_resolving_makes_none(
    tmp_path: Path,
) -> None:
    # Step 4.1 (`01-architecture.md` section 4): the settings, the app's database, the logs, and
    # the saved import profiles, each named by `FefatPaths` alone.
    paths = resolve_paths({"FEFAT_HOME": str(tmp_path)})

    assert paths.config_file == tmp_path / "config.toml"
    assert paths.database_file == tmp_path / "fefat.sqlite"
    assert paths.logs_dir == tmp_path / "logs"
    assert paths.profiles_dir == tmp_path / "profiles"
    assert list(tmp_path.iterdir()) == []


def a_checkout(folder: Path, entry: str) -> Path:
    """A git working tree at `folder`: its `.git` a folder, as in a clone, or a file, as in a
    worktree or a submodule."""
    folder.mkdir(parents=True)
    if entry == "folder":
        (folder / ".git").mkdir()
    else:
        (folder / ".git").write_text("gitdir: ../elsewhere\n", encoding="utf-8")
    return folder


@pytest.mark.parametrize("entry", ["folder", "file"])
def test_a_data_folder_inside_a_git_working_tree_is_refused(tmp_path: Path, entry: str) -> None:
    # Step 4.1 (from `BACKLOG.md`): an import would write licensed data beside tracked files.
    checkout = a_checkout(tmp_path / "checkout", entry)
    data_dir = checkout / "fixtures" / "not-made-yet"
    expected = (
        f"Expected the data folder outside a git working tree, got {data_dir} inside the "
        f"repository at {checkout}"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolve_paths({"FEFAT_HOME": str(tmp_path / "home"), "FEFAT_DATA_DIR": str(data_dir)})


def test_a_fefat_home_inside_a_git_working_tree_is_refused_with_its_data_folder_elsewhere(
    tmp_path: Path,
) -> None:
    # The caches under FEFAT_HOME hold copies of the licensed data (`01-architecture.md`
    # section 4), which the variable for the tests' data folder does not allow.
    checkout = a_checkout(tmp_path / "checkout", "folder")
    home = checkout / "home"
    environment = {
        "FEFAT_HOME": str(home),
        "FEFAT_DATA_DIR": str(tmp_path / "data"),
        "FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE": "1",
    }
    expected = (
        f"Expected FEFAT_HOME outside a git working tree, got {home} inside the repository at "
        f"{checkout}: its caches would hold copies of licensed data"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolve_paths(environment)


def test_a_data_folder_inside_a_git_working_tree_is_allowed_by_the_variable_at_1(
    tmp_path: Path,
) -> None:
    # The tests that read the repository's `fixtures/` as their data folder set it.
    checkout = a_checkout(tmp_path / "checkout", "folder")
    environment = {
        "FEFAT_HOME": str(tmp_path / "home"),
        "FEFAT_DATA_DIR": str(checkout / "fixtures"),
        "FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE": "1",
    }

    assert resolve_paths(environment).data_dir == checkout / "fixtures"


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_the_variable_that_allows_it_takes_1_alone(tmp_path: Path, value: str) -> None:
    expected = f"Expected FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE to be 1 or unset, got {value!r}."

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolve_paths({"FEFAT_HOME": str(tmp_path), "FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE": value})
