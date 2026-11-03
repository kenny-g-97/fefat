"""The leak detector's lint (step 3.4, `02-engine-and-data.md` §6, D-12): a reading of a feature's
source, its decorator included, that flags the usual ways of reading ahead before any data is
cut, each finding with its line, counted from the decorator's, the line's text, and why.

    for finding in ff.features.lint(next_close):
        print(finding)  # line 3: return pl.col("close").shift(-1): a negative shift reads ...

It flags a negative shift or difference; a backward fill or an interpolation; a centred rolling
window or a peak; an aggregate over the whole frame, such as the normalisation, scaling, rank,
quantile bins, or sort of a column over the full sample, or its last value; an aggregate over a partition, such as a
session's `.over("trade_date")`, read before the partition ends; an as-of join forward or to the
nearest row, or keyed on `ts_open`; and a reversed column. An aggregate inside a group-by's
`agg` and one over a rolling window are left to the cuts, which see whether the group or the
window has ended. It also warns of what the content hash leaves out (`BACKLOG.md`): a name the
feature reads that is neither its own, the SDK's, Polars', nor the standard library's, such as a
helper or a constant defined beside it, and a default its decorator does not write as a literal,
a parameter that may have been chosen on the full sample; a warning never fails a validation.

The lint reads the text alone: a shift by a parameter that is negative, a leak in a helper, and
an aggregate under another name pass it, and the cuts of `fefat.features.validation` find what
the values show."""

import ast
import inspect
import sys
from collections.abc import Iterable, Iterator
from enum import StrEnum
from types import FunctionType

from fefat.features.declarations import feature_call
from fefat.features.definition import FeatureDef
from fefat.market.schema import FrozenModel


class LintRule(StrEnum):
    """What a finding of the lint is: a way of reading ahead, or a warning of what the content
    hash leaves out (`looks_ahead`)."""

    NEGATIVE_SHIFT = "negative_shift"
    BACKWARD_FILL = "backward_fill"
    CENTRED_WINDOW = "centred_window"
    FULL_SAMPLE = "full_sample"
    PARTITION_AGGREGATE = "partition_aggregate"
    REVERSED = "reversed"
    FORWARD_JOIN = "forward_join"
    JOIN_ON_OPEN = "join_on_open"
    NAME_READ_OUTSIDE = "name_read_outside"
    NON_LITERAL_DEFAULT = "non_literal_default"

    @property
    def looks_ahead(self) -> bool:
        """Whether the rule finds a way of reading ahead, which fails a validation, rather than
        something the hash leaves out."""
        return self not in (LintRule.NAME_READ_OUTSIDE, LintRule.NON_LITERAL_DEFAULT)


_WHY = {
    LintRule.NEGATIVE_SHIFT: "a negative shift or difference reads the bars after each row; "
    "shift by a positive number of bars, such as shift(1), to read the bars before it (D-12).",
    LintRule.BACKWARD_FILL: "a backward fill or an interpolation gives a row a value from a bar "
    "after it; fill forward, such as forward_fill(), which reads the bars before it.",
    LintRule.CENTRED_WINDOW: "a centred window, or a peak, reads bars after each row as well as "
    "before it; leave center=True out, so that the window ends at the row, and compare a bar with "
    "the bars before it alone.",
    LintRule.FULL_SAMPLE: "an aggregate over the whole frame, such as a mean, a maximum, a rank, "
    "or the last value, reads every bar, the later ones too, as a normalisation or a scaling over "
    "the full sample does; use a rolling, a cumulative (cum_*), or an exponential (ewm_*) window.",
    LintRule.PARTITION_AGGREGATE: "an aggregate over a partition, such as a session's "
    '.over("trade_date"), reads the partition\'s later rows before it ends; use a cumulative '
    "form, such as cum_max().over(...), or the partition before, shifted by one.",
    LintRule.REVERSED: "a reversed column, or a cumulative function run in reverse, reads each "
    "row's later bars; run it forward.",
    LintRule.FORWARD_JOIN: "an as-of join forward or to the nearest row reads the first row at or "
    "after each row's close; join backward, the default, which reads the last row at or before it.",
    LintRule.JOIN_ON_OPEN: "an as-of join on ts_open sees a bar from its open, while it is in "
    "progress; join on ts_close, when a bar is available (D-43).",
}
_AGGREGATES = frozenset(
    {
        "arg_max",
        "arg_min",
        "arg_sort",
        "bottom_k",
        "entropy",
        "is_duplicated",
        "is_unique",
        "kurtosis",
        "last",
        "max",
        "mean",
        "median",
        "min",
        "mode",
        "n_unique",
        "product",
        "qcut",
        "quantile",
        "rank",
        "skew",
        "std",
        "sum",
        "tail",
        "top_k",
        "unique",
        "value_counts",
        "var",
    }
)
"""Methods that reduce a column to one value, or rank, sort, bin, or count it, over the rows
they are given."""
_SHIFTS = frozenset({"diff", "pct_change", "shift"})
_BACKWARD_FILLS = frozenset({"backward_fill", "interpolate", "interpolate_by"})
_PEAKS = frozenset({"peak_max", "peak_min"})
"""Methods that compare each row with the rows on both sides of it."""
_PER_ROW = frozenset({"arr", "list"})
_GROUPINGS = frozenset({"group_by", "group_by_dynamic", "rolling"})
"""Frame methods whose aggregates reduce each group, as `agg` does: `group_by("trade_date").max()`."""
"""Namespaces whose aggregates reduce each row's own values, such as `.list.max()`."""
_OF_NUMBERS = frozenset({"math", "statistics"})
"""Modules of the standard library whose aggregates reduce Python's own numbers."""
_PLATFORM = frozenset({"builtins", "fefat", "polars"})


class LintFinding(FrozenModel):
    """A finding of the lint: its rule, the line of the feature's source it is on, counted from
    its decorator's, 1, the line's text, and why it reads ahead or what the hash leaves out."""

    rule: LintRule
    line: int
    source: str
    explanation: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.source}: {self.explanation}"


def lint(definition: FeatureDef) -> tuple[LintFinding, ...]:
    """The findings of the lint in `definition`'s source, by line (module docstring)."""
    statement = ast.parse(definition.code).body[0]
    lines = definition.code.splitlines()
    found = {
        (each.line, each.rule, each.explanation): each
        for each in (
            *_reading_ahead(statement, lines),
            *_names_read_outside(definition, statement, lines),
            *_written_defaults(statement, lines),
        )
    }
    return tuple(found[key] for key in sorted(found))


def _reading_ahead(statement: ast.stmt, lines: list[str]) -> Iterator[LintFinding]:
    """The findings of reading ahead in the function's body, its decorator left to
    `_written_defaults`."""
    body = statement.body if isinstance(statement, ast.FunctionDef) else []
    calls = [
        node
        for each in body
        for node in ast.walk(each)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    over = _inside(_receiver(call) for call in calls if _method(call) == "over")
    windowed = _inside(_receiver(call) for call in calls if _method(call) == "rolling")
    grouped = _inside(
        argument
        for call in calls
        if _method(call) == "agg"
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]
    )
    for call in calls:
        for rule in _rules_of(call, over, windowed | grouped):
            yield _finding(rule, _line_of(call), lines, _WHY[rule])


def _rules_of(call: ast.Call, over: set[int], left_to_the_cuts: set[int]) -> Iterator[LintRule]:
    method = _method(call)
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if method in _SHIFTS and _negative(call.args[0] if call.args else keywords.get("n")):
        yield LintRule.NEGATIVE_SHIFT
    if method in _BACKWARD_FILLS or (
        method == "fill_null" and _text(keywords.get("strategy", _second(call))) == "backward"
    ):
        yield LintRule.BACKWARD_FILL
    if _true(keywords.get("center")) or method in _PEAKS:
        yield LintRule.CENTRED_WINDOW
    if method == "reverse" or _true(keywords.get("reverse")):
        yield LintRule.REVERSED
    if method == "join_asof":
        yield from _join_rules(keywords)
    if method in _AGGREGATES and _of_a_column(call) and id(call) not in left_to_the_cuts:
        yield LintRule.PARTITION_AGGREGATE if id(call) in over else LintRule.FULL_SAMPLE


def _join_rules(keywords: dict[str | None, ast.expr]) -> Iterator[LintRule]:
    if _text(keywords.get("strategy")) in ("forward", "nearest"):
        yield LintRule.FORWARD_JOIN
    if any(_text(keywords.get(key)) == "ts_open" for key in ("on", "left_on", "right_on")):
        yield LintRule.JOIN_ON_OPEN


def _inside(roots: Iterable[ast.AST]) -> set[int]:
    """The nodes under `roots`, by identity."""
    return {id(node) for root in roots for node in ast.walk(root)}


def _method(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else ""


def _receiver(call: ast.Call) -> ast.expr:
    """What a method is called on: `close` in `close.max()`."""
    return call.func.value if isinstance(call.func, ast.Attribute) else call.func


def _of_a_column(call: ast.Call) -> bool:
    """Whether an aggregate's receiver is a column or a frame, not a namespace of each row's own
    values, a frame's groups, which the cuts judge as `agg`'s, nor a module of Python's numbers,
    such as `statistics`."""
    if not isinstance(call.func, ast.Attribute):
        return False
    receiver = call.func.value
    if isinstance(receiver, ast.Attribute):
        return receiver.attr not in _PER_ROW
    if isinstance(receiver, ast.Call):
        return _method(receiver) not in _GROUPINGS
    return not (isinstance(receiver, ast.Name) and receiver.id in _OF_NUMBERS)


def _negative(node: ast.expr | None) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return True
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value < 0
    )


def _second(call: ast.Call) -> ast.expr | None:
    return call.args[1] if len(call.args) > 1 else None


def _text(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _line_of(call: ast.Call) -> int:
    """The line of a method call's name, where a chain over several lines writes it."""
    end = call.func.end_lineno
    return call.lineno if end is None else end


def _finding(rule: LintRule, line: int, lines: list[str], explanation: str) -> LintFinding:
    return LintFinding(
        rule=rule, line=line, source=lines[line - 1].strip(), explanation=explanation
    )


def _names_read_outside(
    definition: FeatureDef, statement: ast.stmt, lines: list[str]
) -> Iterator[LintFinding]:
    """A warning for each name the function's body reads, lambdas included, that it does not bind
    itself and that is neither the SDK's, Polars', nor the standard library's: a helper's code
    and a constant's value, which the hash leaves out (`BACKLOG.md`)."""
    function = definition.function
    if not isinstance(function, FunctionType) or not isinstance(statement, ast.FunctionDef):
        return
    outside = {**function.__globals__, **inspect.getclosurevars(function).nonlocals}
    for name, line in sorted(_names_read(statement).items()):
        if name not in outside or _of_the_platform(outside[name]):
            continue
        explanation = (
            f"{name} is defined outside the feature, its SDK, Polars, and Python's standard "
            "library, so its code or value is not in the feature's hash: a change to it changes "
            "no version, and the feature cache reads back the values it gave before; write it "
            "in the feature, or make it a parameter."
        )
        yield _finding(LintRule.NAME_READ_OUTSIDE, line, lines, explanation)


def _names_read(statement: ast.FunctionDef) -> dict[str, int]:
    """The names the body reads and does not bind, by the first line reading each: its own
    parameters, its lambdas', and what it assigns are its own."""
    nodes = [node for each in statement.body for node in ast.walk(each)]
    functions = [statement, *(node for node in nodes if isinstance(node, ast.Lambda))]
    bound = {argument.arg for each in functions for argument in _parameters(each.args)}
    bound |= {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)
    }
    read: dict[str, int] = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            read[node.id] = min(read.get(node.id, node.lineno), node.lineno)
    return read


def _parameters(arguments: ast.arguments) -> list[ast.arg]:
    starred = [each for each in (arguments.vararg, arguments.kwarg) if each is not None]
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *starred]


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


def _written_defaults(statement: ast.stmt, lines: list[str]) -> Iterator[LintFinding]:
    """A warning for each default the decorator's `params` does not write as a literal, and for
    `params` bound to a name: a default worked out when the feature is defined, such as a
    quantile of the closes, is a parameter chosen on the full sample (`BACKLOG.md`)."""
    call = feature_call(statement)
    written = None if call is None else _keyword(call, "params")
    if written is None:
        return
    if not isinstance(written, ast.Dict):
        yield _default_finding("params", written, lines)
        return
    for key, value in zip(written.keys, written.values, strict=True):
        if not _literal(value):
            yield _default_finding(_text(key) or ast.unparse(value), value, lines)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except ValueError:
        return False
    return True


def _default_finding(name: str, node: ast.expr, lines: list[str]) -> LintFinding:
    explanation = (
        f"the default of {name} is not written as a literal, so the hash holds its name but not "
        "its value, and a default worked out from data when the feature is defined, such as a "
        "quantile of the closes, is a parameter chosen on the full sample; write the value."
    )
    return _finding(LintRule.NON_LITERAL_DEFAULT, node.lineno, lines, explanation)
