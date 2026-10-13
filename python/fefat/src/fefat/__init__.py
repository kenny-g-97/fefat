"""FEFAT SDK: anything the app can do, a notebook can do with `import fefat as ff`."""

from dataclasses import dataclass
from enum import StrEnum

import fefat_engine

from fefat import stats
from fefat.market import fees, instruments

__all__ = ["BuildProfile", "EngineBuild", "engine_info", "fees", "instruments", "stats"]

__version__ = "0.0.1"


class BuildProfile(StrEnum):
    """How the engine was compiled: `release` is optimised, `debug` runs many times slower."""

    DEBUG = "debug"
    RELEASE = "release"


@dataclass(frozen=True)
class EngineBuild:
    """The compiled engine that the SDK calls: its version and how it was built."""

    version: str
    target_os: str
    target_arch: str
    profile: BuildProfile


def engine_info() -> EngineBuild:
    """The version and build of the `fefat_engine` module behind this SDK."""
    build = fefat_engine.build_details()
    return EngineBuild(
        version=build["version"],
        target_os=build["target_os"],
        target_arch=build["target_arch"],
        profile=BuildProfile(build["profile"]),
    )
