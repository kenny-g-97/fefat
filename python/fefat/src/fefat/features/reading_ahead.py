"""The leak detector's rules on calls (step 3.4, `02-engine-and-data.md` §6, D-12), apart from the
lint's reading of a feature's names (`fefat.features.source_lint`), so that a strategy's lint
(`fefat.strategy.source_lint`, step 5.2) reads a module's calls by the same rules: a negative
shift or difference, a backward fill or an interpolation, a centred window or a peak, an aggregate
over the whole frame (a normalisation, a scaling, a rank, quantile bins, the last value, a fill of
nulls with the mean) or over a partition such as `.over("trade_date")`, an as-of join forward, to
the nearest row, or on `ts_open`, and a reversed column; and, by the name a call calls, data read
by a reader, which the cuts never cut, and the labels of `fefat.analytics`, which read the future
by design. A method of a namespace of each row's own values, such as `.str`, and an aggregate of a
group-by, a rolling window, a `rolling_map`, or a list's `eval` are left to the cuts."""

import ast
from collections.abc import Iterable, Iterator, Sequence
from enum import StrEnum


class LintRule(StrEnum):
    """What a finding of the lint is: a way of reading ahead (`looks_ahead`), a read of data the
    detector cannot cut (`fails_validation`), or a warning of what the content hash leaves out."""

    NEGATIVE_SHIFT = "negative_shift"
    BACKWARD_FILL = "backward_fill"
    CENTRED_WINDOW = "centred_window"
    FULL_SAMPLE = "full_sample"
    PARTITION_AGGREGATE = "partition_aggregate"
    REVERSED = "reversed"
    FORWARD_JOIN = "forward_join"
    JOIN_ON_OPEN = "join_on_open"
    READS_DATA = "reads_data"
    READS_LABELS = "reads_labels"
    NAME_READ_OUTSIDE = "name_read_outside"
    NON_LITERAL_DEFAULT = "non_literal_default"

    @property
    def looks_ahead(self) -> bool:
        """Whether the rule warns of a way of reading ahead."""
        return self not in _NOT_AHEAD

    @property
    def fails_validation(self) -> bool:
        """Whether a finding of the rule fails a validation: data the feature reads itself, which
        the cuts never cut, so that they cannot vouch for its values, and the labels of
        `fefat.analytics`, which read the future by design."""
        return self in {LintRule.READS_DATA, LintRule.READS_LABELS}


_NOT_AHEAD = frozenset(
    {LintRule.READS_DATA, LintRule.NAME_READ_OUTSIDE, LintRule.NON_LITERAL_DEFAULT}
)
EXPLANATIONS = {
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
    "form, such as cum_max().over(...), or read it once the partition has ended.",
    LintRule.REVERSED: "a reversed column, or a cumulative function run in reverse, reads each "
    "row's later bars; run it forward.",
    LintRule.FORWARD_JOIN: "an as-of join forward or to the nearest row reads the first row at or "
    "after each row's close; join backward, the default, which reads the last row at or before it.",
    LintRule.JOIN_ON_OPEN: "an as-of join on ts_open sees a bar from its open, while it is in "
    "progress; join on ts_close, when a bar is available (D-43).",
}
"""Why each way of reading ahead reads ahead, and what to write instead."""
_AGGREGATES = frozenset(
    [
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
    ]
)
"""Methods that reduce a column to one value, or rank, sort, bin, or count it, over the rows
they are given."""
_SHIFTS = frozenset({"diff", "pct_change", "shift"})
_BACKWARD_FILLS = frozenset({"backward_fill", "interpolate", "interpolate_by"})
_SAMPLE_FILLS = frozenset({"max", "mean", "min"})
"""The strategies of `fill_null` that fill with a statistic of the rows given."""
_PEAKS = frozenset({"peak_max", "peak_min"})
"""Methods that compare each row with the rows on both sides of it."""
_PER_ROW = frozenset({"arr", "bin", "cat", "dt", "list", "meta", "name", "str", "struct"})
"""Namespaces whose methods work on each row's own values, such as `.list.max()`."""
_GROUPINGS = frozenset({"group_by", "group_by_dynamic", "rolling"})
"""Frame methods whose aggregates reduce each group, as `agg` does: `group_by("trade_date").max()`."""
_PER_WINDOW = frozenset({"agg", "eval", "map_elements", "rolling_map"})
"""Methods whose arguments' aggregates reduce a group, a window, a list, or an element."""
_OF_NUMBERS = frozenset({"math", "statistics"})
"""Modules of the standard library whose aggregates reduce Python's own numbers."""
READERS = frozenset(
    {
        "compute",
        "connect",
        "load",
        "open",
        "read",
        "roll_calendar",
        "scan",
        "series_source",
        "series_source_in",
        "side_volumes",
        "signal_bars",
        "urlopen",
    }
)
"""Methods that read data, such as `ff.market.load`, `ff.features.compute`, and a store's `scan`."""
_NAMED_READERS = frozenset(
    {
        "compute",
        "connect",
        "load",
        "open",
        "roll_calendar",
        "series_source",
        "series_source_in",
        "urlopen",
    }
)
"""Functions called by their name that read data, such as Python's `open`."""
READER_PREFIXES = ("read_", "scan_")
LABEL_MAKERS = frozenset({"excursions", "exit_open", "forward_returns"})
"""The functions of `fefat.analytics.labels` that compute columns reading the future."""


def calls_in(statements: Iterable[ast.AST]) -> list[ast.Call]:
    """Every call of `statements`, the calls inside each call included."""
    return [node for each in statements for node in ast.walk(each) if isinstance(node, ast.Call)]


def ways_of_reading_ahead(calls: Sequence[ast.Call]) -> Iterator[tuple[ast.Call, LintRule]]:
    """Each call of `calls`, every call of one text, that reads ahead, with the rule it breaks: an
    aggregate is judged by the calls around it, a partition's `.over(...)`, a rolling window, or a
    group's `agg`, which `calls` hold too."""
    over = _inside(_receiver(call) for call in calls if _method(call) == "over")
    windowed = _inside(_receiver(call) for call in calls if _method(call) == "rolling")
    within = _inside(
        argument
        for call in calls
        if _method(call) in _PER_WINDOW
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]
    )
    for call in calls:
        for rule in _rules_of(call, over, windowed | within):
            yield call, rule


def ways_of_reading_data(calls: Iterable[ast.Call]) -> Iterator[tuple[ast.Call, LintRule]]:
    """Each call of `calls` that reads data, by a reader's name, or computes the labels of
    `fefat.analytics`, with the rule it breaks."""
    for call in calls:
        called = call.func.id if isinstance(call.func, ast.Name) else _method(call)
        readers = READERS if isinstance(call.func, ast.Attribute) else _NAMED_READERS
        if called in readers or called.startswith(READER_PREFIXES):
            yield call, LintRule.READS_DATA
        if called in LABEL_MAKERS:
            yield call, LintRule.READS_LABELS


def _rules_of(call: ast.Call, over: set[int], left_to_the_cuts: set[int]) -> Iterator[LintRule]:
    if not isinstance(call.func, ast.Attribute) or _on_each_row(call):
        return
    method = call.func.attr
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    strategy = written_text(keywords.get("strategy", _second(call)))
    if method in _SHIFTS and _negative(call.args[0] if call.args else keywords.get("n")):
        yield LintRule.NEGATIVE_SHIFT
    if method in _BACKWARD_FILLS or (method == "fill_null" and strategy == "backward"):
        yield LintRule.BACKWARD_FILL
    if _true(keywords.get("center")) or method in _PEAKS:
        yield LintRule.CENTRED_WINDOW
    if method == "reverse" or _true(keywords.get("reverse")):
        yield LintRule.REVERSED
    if method == "join_asof":
        yield from _join_rules(keywords)
    aggregates = method in _AGGREGATES or (method == "fill_null" and strategy in _SAMPLE_FILLS)
    if aggregates and _of_a_column(call) and id(call) not in left_to_the_cuts:
        yield LintRule.PARTITION_AGGREGATE if id(call) in over else LintRule.FULL_SAMPLE


def _join_rules(keywords: dict[str | None, ast.expr]) -> Iterator[LintRule]:
    if written_text(keywords.get("strategy")) in ("forward", "nearest"):
        yield LintRule.FORWARD_JOIN
    if any(written_text(keywords.get(key)) == "ts_open" for key in ("on", "left_on", "right_on")):
        yield LintRule.JOIN_ON_OPEN


def _inside(roots: Iterable[ast.AST]) -> set[int]:
    """The nodes under `roots`, by identity."""
    return {id(node) for root in roots for node in ast.walk(root)}


def _method(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else ""


def _receiver(call: ast.Call) -> ast.expr:
    """What a method is called on: `close` in `close.max()`."""
    return call.func.value if isinstance(call.func, ast.Attribute) else call.func


def _on_each_row(call: ast.Call) -> bool:
    """Whether a method belongs to a namespace of each row's own values, such as `.str.tail(4)`."""
    receiver = _receiver(call)
    return isinstance(receiver, ast.Attribute) and receiver.attr in _PER_ROW


def _of_a_column(call: ast.Call) -> bool:
    """Whether an aggregate's receiver is a column or a frame, not a frame's groups, which the
    cuts judge as `agg`'s, nor a module of Python's numbers, such as `statistics`."""
    receiver = _receiver(call)
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


def written_text(node: ast.expr | None) -> str | None:
    """The text `node` writes as a literal string, or None where it writes none."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def line_of(call: ast.Call) -> int:
    """The line of a call's name, where a chain over several lines writes it."""
    end = call.func.end_lineno
    return call.lineno if end is None else end
