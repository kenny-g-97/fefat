"""FEFAT SDK: anything the app can do, a notebook can do with `import fefat as ff`."""

from dataclasses import dataclass

import fefat_engine

from fefat import stats

__all__ = ["EngineInfo", "engine_info", "stats"]

__version__ = "0.0.1"


@dataclass(frozen=True)
class EngineInfo:
    """The compiled engine that the SDK calls: its version and how it was built."""

    version: str
    target_os: str
    target_arch: str
    profile: str


def engine_info() -> EngineInfo:
    """The version and build of the `fefat_engine` module behind this SDK."""
    return EngineInfo(**fefat_engine.build_info())
