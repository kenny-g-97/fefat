"""Where FEFAT keeps its files on this machine: `FEFAT_HOME` and `FEFAT_DATA_DIR`.

`FEFAT_HOME` holds the app's state, logs, caches, and workspaces. `FEFAT_DATA_DIR`
holds the market data, which code reaches through this path only: real data never
enters the repository (docs/masterplan/01-architecture.md section 4, decision D-21).
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
DATA_FOLDER_NAME = "data"


@dataclass(frozen=True)
class FefatPaths:
    """The two folders FEFAT reads and writes outside the repository."""

    home: Path
    data_dir: Path


def resolve_paths(environment: Mapping[str, str]) -> FefatPaths:
    """Resolve `FEFAT_HOME` and `FEFAT_DATA_DIR` from the environment, with the platform defaults.

    `FEFAT_HOME` defaults to the user data folder (`%LOCALAPPDATA%\\FEFAT` on Windows,
    `~/Library/Application Support/FEFAT` on macOS) and `FEFAT_DATA_DIR` to
    `<FEFAT_HOME>/data`. A variable that is set must hold an absolute path. Pass
    `os.environ` in the app and a plain dict in tests. Nothing is created on disk.
    """
    home = _configured_folder(environment, HOME_VARIABLE, _default_home())
    data_dir = _configured_folder(environment, DATA_DIR_VARIABLE, home / DATA_FOLDER_NAME)
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
