"""Features (`02-engine-and-data.md` §6, Phase 3): `@ff.feature` defines one
(`fefat.features.definition`), a `FeatureSpec` binds its parameters and evaluates it over the
signal bars (`fefat.features.evaluation`), `compute` evaluates features with what they read on
the signal grid (`fefat.features.runtime`) and keeps their values in the feature cache, which
`cache_status` lists (`fefat.features.cache`), `save` and `load` keep their versions in the
workspace, `ref` reads one back by name and version as a feature with its parameters, and
`library` lists them (`fefat.features.versions`), `from_source` builds a feature from its code
string (`fefat.features.source_code`), `combine` makes new features of existing ones without
code (`fefat.features.combine`, step 3.7), `validate` checks that a feature never reads ahead, its
values before each cut of the data unchanged by the data after it (`fefat.features.validation`),
and `lint` reads its source for the usual ways of reading ahead (`fefat.features.source_lint`);
`fefat.features.examples` holds RSI, ATR, and a flag of a window of the trading day."""

from fefat.features import combine
from fefat.features.cache import compute
from fefat.features.cache_index import cache_status
from fefat.features.combinations import Combination
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
from fefat.features.source_code import from_source
from fefat.features.source_lint import lint
from fefat.features.validation import validate
from fefat.features.validation_report import ValidationReport
from fefat.features.versions import FeatureVersion, library, load, ref, save

__all__ = [
    "Combination",
    "DatasetInput",
    "FeatureDef",
    "FeatureInput",
    "FeatureSpec",
    "FeatureVersion",
    "InstrumentInput",
    "OutputKind",
    "TimeframeInput",
    "TradesInput",
    "ValidationReport",
    "cache_status",
    "combine",
    "compute",
    "feature",
    "from_source",
    "library",
    "lint",
    "load",
    "ref",
    "save",
    "validate",
]
