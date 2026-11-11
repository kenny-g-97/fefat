"""A feature from a code string (step 3.7, `BACKLOG.md`): `from_source` builds the feature a text
of its code defines, its decorator included, as a version keeps it, so that a feature read from
the library by name and version (`ff.features.ref`), a combination (`fefat.features.combine`),
and later the agent's proposals have one way in that needs no file or notebook cell holding the
text, which `inspect.getsource` reads otherwise.

    built = ff.features.from_source(version.code)
    built.hash == version.hash

The text runs with the names a feature's code may read bound: `ff`, `features`, `pl`, `feature`,
the input kinds, `OutputKind`, and the parameter types, `BarCount`, `TwoOrMoreBars`,
`SessionCount`, `MinuteCount`, `Multiple`, `LocalTime`, `TimeZoneName`, `Annotated`, and `Field`,
with the features its decorator names given as `reads`, by the names it writes for them, such as
`{"base": base}`; its text is kept in `linecache` under a
name of its own, as ipykernel keeps a cell's. A body that reads any other name, such as a helper
the feature calls, which its version does not keep, is refused before it runs (`BACKLOG.md`), as
is a text that is not one function under its `@feature(...)` call."""

import ast
import builtins
import hashlib
import linecache
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any

import polars as pl
from pydantic import Field

from fefat.features.declarations import INPUT_KINDS, feature_call
from fefat.features.definition import BarCount, FeatureDef, SessionCount, TwoOrMoreBars, feature
from fefat.features.inputs import OutputKind
from fefat.features.source_names import names_read
from fefat.market.calendar import counted
from fefat.market.calendar_definition import LocalTime, TimeZoneName

NO_READS: Mapping[str, FeatureDef] = MappingProxyType({})
"""No features read by name."""
SOURCE_FILENAME_PREFIX = "<feature source "
"""How the file name of a text `from_source` runs begins, as a traceback names its lines."""


def from_source(code: str, reads: Mapping[str, FeatureDef] = NO_READS) -> FeatureDef:
    """The feature `code` defines, with the features its decorator names by name given in
    `reads` under those names (module docstring)."""
    statement = _one_feature(code)
    namespace = _namespace(reads)
    if statement.name in namespace:
        raise ValueError(
            f"Expected a feature named apart from the names its code reads, got {statement.name}, "
            "which its code would then read as the feature itself."
        )
    unbound = sorted(set(names_read(statement)) - set(namespace) - set(dir(builtins)))
    if unbound:
        raise ValueError(
            f"Expected the body of feature {statement.name} to read only its parameters and the "
            "names its code may read (ff, pl, the input kinds, and the parameter types), got "
            f"{', '.join(unbound)}: a helper a feature calls is not versioned with it "
            "(BACKLOG.md), so define the feature in a file or a cell that imports it."
        )
    filename = f"{SOURCE_FILENAME_PREFIX}{hashlib.sha256(code.encode()).hexdigest()[:12]}>"
    linecache.cache[filename] = (len(code), None, code.splitlines(keepends=True), filename)
    try:
        exec(compile(code, filename, "exec"), namespace)
    except NameError as error:
        raise ValueError(
            f"Expected the names the decorator of feature {statement.name} reads among those its "
            f"code may read and the features given, got: {error}: give the features it reads by "
            "name in reads, or define it again where the names its decorator reads are bound."
        ) from error
    built = namespace[statement.name]
    if not isinstance(built, FeatureDef):
        raise ValueError(
            f"Expected the code of feature {statement.name} to define a feature, got "
            f"{type(built).__name__}."
        )
    return built


def _one_feature(code: str) -> ast.FunctionDef:
    """The one function `code` defines under its `@feature(...)` call."""
    body = ast.parse(code).body
    if len(body) == 1 and isinstance(body[0], ast.FunctionDef):
        if feature_call(body[0]) is not None:
            return body[0]
        got = "a function without it"
    else:
        got = counted(len(body), "statement")
    raise ValueError(
        f"Expected the code of one feature, a function under its @ff.feature(...) call, got {got}."
    )


def _namespace(reads: Mapping[str, FeatureDef]) -> dict[str, Any]:
    """The names a feature's code may read (module docstring), and the features `reads`; the SDK,
    which a feature's code names `ff`, and the indicators' parameter types are imported when
    called, since both import this package first."""
    import fefat
    from fefat.indicators.bands import Multiple
    from fefat.indicators.sessions import MinuteCount

    return {
        "ff": fefat,
        "features": fefat.features,
        "pl": pl,
        "feature": feature,
        **{kind.__name__: kind for kind in INPUT_KINDS},
        "OutputKind": OutputKind,
        "BarCount": BarCount,
        "TwoOrMoreBars": TwoOrMoreBars,
        "SessionCount": SessionCount,
        "MinuteCount": MinuteCount,
        "Multiple": Multiple,
        "LocalTime": LocalTime,
        "TimeZoneName": TimeZoneName,
        "Annotated": Annotated,
        "Field": Field,
        **reads,
    }
