"""The leak detector's lint (step 3.4, `02-engine-and-data.md` §6, D-12): a reading of a feature's
source, its decorator included, that warns of the usual ways of reading ahead, each finding with
the feature's name, its line, counted from the decorator's, the line's text, and why.

    for finding in ff.features.lint(next_close):
        print(finding)  # line 3 of next_close: return pl.col("close").shift(-1): a negative ...

It warns of a negative shift or difference, a backward fill or an interpolation, a centred window
or a peak, an aggregate over the whole frame (a normalisation, a scaling, a rank, quantile bins,
the last value, a fill of nulls with the mean) or over a partition such as `.over("trade_date")`,
an as-of join forward, to the nearest row, or on `ts_open`, and a reversed column, by the rules on
calls of `fefat.features.reading_ahead`, which a strategy's lint shares. A method of a
namespace of each row's own values, such as `.str`, and an aggregate of a group-by, a rolling
window, a `rolling_map`, or a list's `eval` are left to the cuts. These are warnings: the cuts and
the start check of `fefat.features.validation` judge the values. Two findings fail a validation:
data the feature reads itself, with `load`, `compute`, `open`, `roll_calendar`, a store's `read`
or `scan`, a reader such as `pl.scan_parquet`, or the standard library's `connect` and `urlopen`,
or holds from outside it, a frame a notebook cell loaded or a reader bound to another name, which
the cuts never cut and the cache's key never pins; and the labels of `ff.analytics` it computes,
under any name, which read the future by design. The lint also warns of what the hash leaves out
(`BACKLOG.md`): a name read from outside the feature, the SDK, Polars, and the standard library,
and a default not written as a literal, which may have been chosen on the full sample. It reads
the feature's own text alone: a shift by a negative parameter, a leak in a helper, and an
aggregate under another name pass it."""

import ast
import inspect
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from types import FunctionType

import polars as pl

from fefat.features.declarations import feature_call
from fefat.features.definition import FeatureDef
from fefat.features.reading_ahead import (
    EXPLANATIONS,
    LABEL_MAKERS,
    READER_PREFIXES,
    READERS,
    LintRule,
    calls_in,
    line_of,
    ways_of_reading_ahead,
    ways_of_reading_data,
    written_text,
)
from fefat.features.source_names import names_read_outside
from fefat.market.schema import FrozenModel

__all__ = ["LintFinding", "LintRule", "lint"]

_WHY = {
    LintRule.READS_LABELS: "the feature computes the labels of ff.analytics, the forward "
    "returns, which read the future by design: judge a feature against them, never build one "
    "from them.",
    LintRule.READS_DATA: "the feature reads data itself, which the leak detector never cuts and "
    "the feature cache's key never pins, so neither can vouch for its values; declare what it "
    "reads as an input: another feature, instrument, or timeframe.",
}
_PLATFORM = frozenset({"builtins", "fefat", "polars"})


class LintFinding(FrozenModel):
    """A finding of the lint: its rule, the feature whose source it reads, the line it is on,
    counted from the feature's decorator's, 1, the line's text, and why it reads ahead, reads
    data, or what the hash leaves out."""

    rule: LintRule
    feature: str
    line: int
    source: str
    explanation: str

    def __str__(self) -> str:
        return f"line {self.line} of {self.feature}: {self.source}: {self.explanation}"


@dataclass(frozen=True)
class _Source:
    """A feature's name and the lines of its normalised source, which findings quote."""

    name: str
    lines: list[str]

    def finding(self, rule: LintRule, line: int, explanation: str) -> LintFinding:
        text = self.lines[line - 1].strip()
        return LintFinding(
            rule=rule, feature=self.name, line=line, source=text, explanation=explanation
        )


def lint(definition: FeatureDef) -> tuple[LintFinding, ...]:
    """The findings of the lint in `definition`'s source, by line (module docstring)."""
    statement = ast.parse(definition.code).body[0]
    source = _Source(definition.name, definition.code.splitlines())
    found = {
        (each.line, each.rule, each.explanation): each
        for each in (
            *_reading_ahead(statement, source),
            *_names_read_outside(definition, statement, source),
            *_written_defaults(statement, source),
        )
    }
    return tuple(found[key] for key in sorted(found))


def _reading_ahead(statement: ast.stmt, source: _Source) -> Iterator[LintFinding]:
    """The findings of reading ahead, and of reading data, in the function's body, its decorator
    left to `_written_defaults`."""
    body = statement.body if isinstance(statement, ast.FunctionDef) else []
    calls = calls_in(body)
    for call, rule in ways_of_reading_ahead(calls):
        yield source.finding(rule, line_of(call), EXPLANATIONS[rule])
    for call, rule in ways_of_reading_data(calls):
        yield source.finding(rule, line_of(call), _WHY[rule])


def _names_read_outside(
    definition: FeatureDef, statement: ast.stmt, source: _Source
) -> Iterator[LintFinding]:
    """A finding for each name the function's body reads, lambdas included, that it does not bind
    itself: data, or a reader of data, which fails a validation, and a helper or a constant that
    is neither the SDK's, Polars', nor the standard library's, whose code or value the hash leaves
    out (`BACKLOG.md`)."""
    function = definition.function
    if not isinstance(function, FunctionType) or not isinstance(statement, ast.FunctionDef):
        return
    for name, line, value in names_read_outside(function, statement):
        if isinstance(value, pl.DataFrame | pl.LazyFrame | pl.Series) or _a_reader(value):
            yield source.finding(LintRule.READS_DATA, line, f"{name}: {_WHY[LintRule.READS_DATA]}")
        elif _a_label_maker(value):
            why = _WHY[LintRule.READS_LABELS]
            yield source.finding(LintRule.READS_LABELS, line, f"{name}: {why}")
        elif not _of_the_platform(value):
            explanation = (
                f"{name} is defined outside the feature, its SDK, Polars, and Python's standard "
                "library, so its code or value is not in the feature's hash: a change to it "
                "changes no version, and the feature cache reads back the values it gave before; "
                "write it in the feature, or make it a parameter."
            )
            yield source.finding(LintRule.NAME_READ_OUTSIDE, line, explanation)


def _a_reader(value: object) -> bool:
    """Whether `value` is a function of the SDK, Polars, or the standard library that reads data,
    whatever name it is bound to, such as `fetch` for `fefat.market.load`."""
    name = getattr(value, "__name__", None)
    if not inspect.isroutine(value) or not isinstance(name, str):
        return False
    reads = name in READERS or name.startswith(READER_PREFIXES)
    return reads and _of_the_platform(value)


def _a_label_maker(value: object) -> bool:
    """Whether `value` is a function of `fefat.analytics.labels` that computes columns reading
    the future, whatever name it is bound to."""
    module, name = getattr(value, "__module__", None), getattr(value, "__name__", None)
    return module == "fefat.analytics.labels" and name in LABEL_MAKERS


def _of_the_platform(value: object) -> bool:
    """Whether `value` is a module, a function, or a class of the SDK, Polars, or the standard
    library, whose code the feature may read."""
    if inspect.ismodule(value):
        module = value.__name__
    elif inspect.isroutine(value) or inspect.isclass(value):
        module = getattr(value, "__module__", None)
    else:
        return False
    if not isinstance(module, str):
        return False
    root = module.split(".")[0]
    return root in _PLATFORM or root in sys.stdlib_module_names


def _written_defaults(statement: ast.stmt, source: _Source) -> Iterator[LintFinding]:
    """A warning for each default the decorator's `params` does not write as a literal, and for
    `params` bound to a name: a default worked out when the feature is defined, such as a
    quantile of the closes, is a parameter chosen on the full sample (`BACKLOG.md`)."""
    call = feature_call(statement)
    written = None if call is None else _keyword(call, "params")
    if written is None:
        return
    if not isinstance(written, ast.Dict):
        yield _default_finding("params", written, source)
        return
    for key, value in zip(written.keys, written.values, strict=True):
        if not _literal(value):
            name = written_text(key)
            default = f"**{ast.unparse(value)}" if name is None else name
            yield _default_finding(default, value, source)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except ValueError:
        return False
    return True


def _default_finding(name: str, node: ast.expr, source: _Source) -> LintFinding:
    explanation = (
        f"the default of {name} is not written as a literal, so the hash holds its name but not "
        "its value, and a default worked out from data when the feature is defined, such as a "
        "quantile of the closes, is a parameter chosen on the full sample; write the value."
    )
    return source.finding(LintRule.NON_LITERAL_DEFAULT, node.lineno, explanation)
