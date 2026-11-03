"""Features (`02-engine-and-data.md` §6, Phase 3): `@ff.feature` defines one
(`fefat.features.definition`), a `FeatureSpec` binds its parameters and evaluates it over the
signal bars (`fefat.features.evaluation`), `compute` evaluates features with what they read on
the signal grid (`fefat.features.runtime`) and keeps their values in the feature cache, which
`cache_status` lists (`fefat.features.cache`), `save` and `load` keep their versions in the
workspace (`fefat.features.versions`), and `lint` reads a feature's source for the usual ways of
reading ahead (`fefat.features.lint`); `fefat.features.examples` holds RSI, ATR, and a flag of a
window of the trading day."""

from fefat.features.cache import compute
from fefat.features.cache_index import cache_status
from fefat.features.definition import FeatureDef, feature
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import (
    DatasetInput,
    FeatureInput,
    InstrumentInput,
    OutputKind,
    TimeframeInput,
    TradesInput,
)
from fefat.features.lint import lint
from fefat.features.versions import FeatureVersion, load, save

__all__ = [
    "DatasetInput",
    "FeatureDef",
    "FeatureInput",
    "FeatureSpec",
    "FeatureVersion",
    "InstrumentInput",
    "OutputKind",
    "TimeframeInput",
    "TradesInput",
    "cache_status",
    "compute",
    "feature",
    "lint",
    "load",
    "save",
]
