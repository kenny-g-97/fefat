"""Where FEFAT keeps its files on this machine: `FEFAT_HOME` and `FEFAT_DATA_DIR`.

`FEFAT_HOME` holds the app's state, logs, caches, and workspaces. `FEFAT_DATA_DIR`
holds the market data, which code reaches through this path only: real data never
enters the repository (docs/masterplan/01-architecture.md section 4, decision D-21).
A data folder that the environment places inside a git working tree is refused, where
an import would write licensed data beside tracked files, unless
`FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE` is 1, as the tests that read the repository's
`fixtures/` set it (step 4.1, D-85).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

__all__ = ["FefatPaths", "resolve_paths"]

APP_NAME = "FEFAT"
HOME_VARIABLE = "FEFAT_HOME"
DATA_DIR_VARIABLE = "FEFAT_DATA_DIR"
ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE = "FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE"
DATA_FOLDER_NAME = "data"
CACHE_FOLDER_NAME = "cache"
REPORTS_FOLDER_NAME = "reports"
WORKSPACE_FOLDER = Path("workspaces") / "default"
RUNS_FOLDER = Path("artifacts") / "runs"
FEATURES_FOLDER_NAME = "features"
CONFIG_FILE_NAME = "config.toml"
DATABASE_FILE_NAME = "fefat.sqlite"
LOGS_FOLDER_NAME = "logs"
PROFILES_FOLDER_NAME = "profiles"


@dataclass(frozen=True)
class FefatPaths:
    """The two folders FEFAT reads and writes outside the repository."""

    home: Path
    data_dir: Path

    @property
    def cache_dir(self) -> Path:
        """`<FEFAT_HOME>/cache`: what FEFAT can rebuild, such as the session tables, so the
        folder may be deleted at any time (`01-architecture.md` section 4)."""
        return self.home / CACHE_FOLDER_NAME

    @property
    def workspace_dir(self) -> Path:
        """`<FEFAT_HOME>/workspaces/default`: the one workspace of the first release, which holds
        the features, strategies, and runs (`01-architecture.md` section 4)."""
        return self.home / WORKSPACE_FOLDER

    @property
    def runs_dir(self) -> Path:
        """`<workspace>/artifacts/runs`: each saved run's artifacts in a folder of its own, named
        by its run key (`fefat.backtest`, step 2.10)."""
        return self.workspace_dir / RUNS_FOLDER

    @property
    def features_dir(self) -> Path:
        """`<workspace>/features`: each saved feature's versions in a folder of its own, named by
        the feature, as `v<n>.json` (`fefat.features`, step 3.1), the record the app's database
        indexes (D-84)."""
        return self.workspace_dir / FEATURES_FOLDER_NAME

    @property
    def config_file(self) -> Path:
        """`<FEFAT_HOME>/config.toml`: what the server needs before its database opens, read by
        `load_settings` (`01-architecture.md` section 4, D-83)."""
        return self.home / CONFIG_FILE_NAME

    @property
    def database_file(self) -> Path:
        """`<FEFAT_HOME>/fefat.sqlite`: the app's database, its own state and an index of the
        workspace's files (step 4.1, D-84)."""
        return self.home / DATABASE_FILE_NAME

    @property
    def logs_dir(self) -> Path:
        """`<FEFAT_HOME>/logs`: the app's logs."""
        return self.home / LOGS_FOLDER_NAME

    @property
    def profiles_dir(self) -> Path:
        """`<FEFAT_HOME>/profiles`: the import profiles a trader saved, one YAML file each
        (`fefat.market.importers.profiles`, step 1.10)."""
        return self.home / PROFILES_FOLDER_NAME

    @property
    def reports_dir(self) -> Path:
        """`<FEFAT_DATA_DIR>/reports`: the quality reports of the market data beside it
        (`fefat.market.quality`), which the store never reads as a provider."""
        return self.data_dir / REPORTS_FOLDER_NAME


def resolve_paths(environment: Mapping[str, str]) -> FefatPaths:
    """Resolve `FEFAT_HOME` and `FEFAT_DATA_DIR` from the environment, with the platform defaults.

    `FEFAT_HOME` defaults to the user data folder (`%LOCALAPPDATA%\\FEFAT` on Windows,
    `~/Library/Application Support/FEFAT` on macOS) and `FEFAT_DATA_DIR` to
    `<FEFAT_HOME>/data`. A variable that is set must hold an absolute path, and where either
    is set, the data folder must lie outside any git working tree unless
    `FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE` is 1 (module docstring); the platform's default is not
    checked, so that a repository around a user's home folder never stops the app. Pass
    `os.environ` in the app and a plain dict in tests. Nothing is created on disk.
    """
    home = _configured_folder(environment, HOME_VARIABLE, _default_home())
    data_dir = _configured_folder(environment, DATA_DIR_VARIABLE, home / DATA_FOLDER_NAME)
    configured = HOME_VARIABLE in environment or DATA_DIR_VARIABLE in environment
    if configured and not _allows_a_data_dir_in_a_git_tree(environment):
        _require_outside_a_git_working_tree(data_dir)
    return FefatPaths(home=home, data_dir=data_dir)


def _default_home() -> Path:
    return platformdirs.user_data_path(APP_NAME, appauthor=False)


def _configured_folder(environment: Mapping[str, str], variable: str, default: Path) -> Path:
    if variable not in environment:
        return default
    folder = Path(environment[variable])
    if not folder.is_absolute():
        raise ValueError(
            f"Expected {variable} to be an absolute path, got {environment[variable]!r}."
        )
    return folder


def _allows_a_data_dir_in_a_git_tree(environment: Mapping[str, str]) -> bool:
    """Whether `FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE` is 1; any other value is refused."""
    if ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE not in environment:
        return False
    value = environment[ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE]
    if value != "1":
        raise ValueError(
            f"Expected {ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE} to be 1 or unset, got {value!r}."
        )
    return True


def _require_outside_a_git_working_tree(data_dir: Path) -> None:
    """Refuse a data folder in a git working tree: one whose folder, or a folder above it, holds
    a `.git` folder, as a clone does, or a `.git` file, as a worktree or a submodule does.
    Neither the data folder nor its parents need exist."""
    for folder in (data_dir, *data_dir.parents):
        if (folder / ".git").exists():
            raise ValueError(
                f"Expected the data folder outside a git working tree, got {data_dir} inside "
                f"the repository at {folder}: an import would write licensed data beside "
                f"tracked files. Point {DATA_DIR_VARIABLE} elsewhere, or set "
                f"{ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE}=1 to allow it, as the tests do."
            )
