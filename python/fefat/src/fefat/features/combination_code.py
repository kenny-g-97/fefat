"""The code of a combination (step 3.7, `fefat.features.combine`): the source of a feature, its
`@ff.feature(...)` call included, generated from a combination's description
(`fefat.features.combinations`), so that a combination is a feature as any other, hashed,
versioned, validated, and evaluated from that text alone.

    @ff.feature(
        inputs=[
            ff.features.FeatureInput(name="rsi", hash="…", parameters={"n": 14}),
        ],
        warmup=9,
        outputs={"rsi_stretch": "ratio"},
    )
    def rsi_stretch(bars: pl.LazyFrame) -> pl.Expr:
        return pl.col("rsi") - pl.col("rsi").rolling_mean(10)

The text depends on the description alone, so that a combination's version never changes
between runs: each feature it reads is declared once for each set of parameters, first seen
first, with its parameters' keys sorted, under an alias, `ema_1` and `ema_2`, where two features
read would give a column of one name; each other instrument once, as its `InstrumentInput`; and a
top `at_timeframe` as its `TimeframeInput`, while one inside the description is a feature of its
own that the combination reads (`fefat.features.combine`). Its warm-up is the most bars any path
of windows in it needs before its first value: `n - 1` for a window, `n` for a lag, and one for a
cross; and its output's kind is the one its operation gives (`output_kind`). A division is null
where its divisor is 0, as the indicators' are; a standard deviation is the population's, as
TA-Lib's is (D-75); the volume and the number of trades are read as signed integers, so that a
difference of them goes below zero; and a product is of floats, since two prices in the bars'
1e-9 units overflow 64-bit integers."""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from fefat.features.combinations import (
    AtTimeframe,
    BinaryOperation,
    Column,
    Constant,
    FeatureOutput,
    Negation,
    Term,
    Window,
    children_of,
    leaves,
    reads_bars,
)
from fefat.features.definition import FeatureDef
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import OutputKind
from fefat.features.runtime import slot_columns

_INTEGER_COLUMNS = frozenset({"volume", "trade_count"})
_PRICE_COLUMNS = frozenset({"open", "high", "low", "close", "close_raw", "vwap"})
_OPERATORS = {"add": "+", "subtract": "-", "greater_than": ">", "and": "&", "or": "|"}
_FLAGS = frozenset({"greater_than", "crosses_above", "crosses_below", "and", "or"})
_LEVELS = frozenset({OutputKind.PRICE, OutputKind.PRICE_DISTANCE})
FeatureKey = tuple[str, str]
"""A feature read with its parameters: its content hash and its parameters as sorted JSON."""


def feature_key(term: FeatureOutput) -> FeatureKey:
    """The feature `term` reads with its parameters (`FeatureKey`)."""
    return term.hash, json.dumps(term.parameters, sort_keys=True)


def combination_code(name: str, term: Term, definitions: Mapping[str, FeatureDef]) -> str:
    """The source of the feature `name` that `term` describes, each feature it reads defined in
    `definitions` by content hash, and each `at_timeframe` below its top already a feature it
    reads (module docstring)."""
    body, timeframe = (term.of, term.timeframe) if isinstance(term, AtTimeframe) else (term, None)
    _require_combinable(name, body, definitions)
    reads = _reads(body, definitions)
    inputs = [read.declared() for read in reads]
    instruments = [leaf.instrument for leaf in leaves(body) if isinstance(leaf, Column)]
    inputs += [
        f"ff.features.InstrumentInput(root={json.dumps(root)})"
        for root in dict.fromkeys(instruments)
        if root is not None
    ]
    if timeframe is not None:
        inputs.append(f"ff.features.TimeframeInput(timeframe={json.dumps(timeframe)})")
    lines = ["@ff.feature("]
    if inputs:
        lines += ["    inputs=[", *(f"        {each}," for each in inputs), "    ],"]
    warmup = warmup_of(body)
    if warmup:
        lines.append(f"    warmup={warmup},")
    kind = output_kind(body, definitions)
    expression = _Expressions({read.key: read for read in reads}).bare(body)
    return "\n".join(
        [
            *lines,
            f'    outputs={{"{name}": "{kind}"}},',
            ")",
            f"def {name}(bars: pl.LazyFrame) -> pl.Expr:",
            f"    return {expression}",
            "",
        ]
    )


def warmup_of(term: Term) -> int:
    """The most bars a path of windows in `term` needs before its first value (module
    docstring), the warm-ups of the features it reads left to the graph that reads them."""
    below = max((warmup_of(child) for child in children_of(term)), default=0)
    if isinstance(term, Window):
        return below + (term.n if term.kind == "lag" else term.n - 1)
    if isinstance(term, BinaryOperation) and term.kind.startswith("crosses"):
        return below + 1
    return below


def output_kind(term: Term, definitions: Mapping[str, FeatureDef]) -> OutputKind:
    """The kind of the values of `term`: a flag of a comparison or of logic; a ratio of
    `ratio_to`, a percent rank, a z-score, and a quotient of two levels or of one kind; a count
    of a rank; a price distance of two prices' difference, or of a level's standard deviation; a
    price of a price moved by a distance; a constant taking the kind of what it is added to,
    subtracted from, or multiplies, an integer one with a count; and else `other`."""
    if isinstance(term, Constant):
        return OutputKind.FLAG if isinstance(term.value, bool) else OutputKind.OTHER
    if isinstance(term, Column):
        return OutputKind.PRICE if term.column in _PRICE_COLUMNS else OutputKind.COUNT
    if isinstance(term, FeatureOutput):
        return definitions[term.hash].outputs[term.output]
    if isinstance(term, Negation):
        return OutputKind.FLAG
    if isinstance(term, AtTimeframe):
        return output_kind(term.of, definitions)
    if isinstance(term, Window):
        return _window_kind(term, output_kind(term.of, definitions))
    return _pair_kind(term, definitions)


def _window_kind(term: Window, of: OutputKind) -> OutputKind:
    if term.kind in ("percent_rank", "z_score"):
        return OutputKind.RATIO
    if term.kind == "rolling_rank":
        return OutputKind.COUNT
    if term.kind == "rolling_std":
        return OutputKind.PRICE_DISTANCE if of in _LEVELS else OutputKind.OTHER
    if term.kind == "rolling_mean":
        averaged = {OutputKind.FLAG: OutputKind.RATIO, OutputKind.COUNT: OutputKind.OTHER}
        return averaged.get(of, of)
    return of


def _pair_kind(term: BinaryOperation, definitions: Mapping[str, FeatureDef]) -> OutputKind:
    if term.kind in _FLAGS:
        return OutputKind.FLAG
    if term.kind == "ratio_to":
        return OutputKind.RATIO
    left, right = (output_kind(each, definitions) for each in (term.left, term.right))
    scaled = _scaled_kind(term, left, right)
    if scaled is not None:
        return scaled
    if term.kind == "divide":
        same = left == right and left in (*_LEVELS, OutputKind.RATIO, OutputKind.COUNT)
        return OutputKind.RATIO if same or {left, right} <= _LEVELS else OutputKind.OTHER
    if term.kind == "multiply":
        return OutputKind.OTHER
    return _sum_kind(term.kind == "subtract", left, right)


def _scaled_kind(term: BinaryOperation, left: OutputKind, right: OutputKind) -> OutputKind | None:
    """The kind of a term moved, multiplied, or divided by a number, `rsi - 50`, `2 * atr`, or
    `atr / 2`: the term's, an integer number's with a count, and None where neither side, or
    the dividend, is a number."""
    numbers = [
        each
        for each in (term.left, term.right)
        if isinstance(each, Constant) and not isinstance(each.value, bool)
    ]
    if len(numbers) != 1 or (term.kind == "divide" and numbers[0] is term.left):
        return None
    kept = right if numbers[0] is term.left else left
    if term.kind in ("multiply", "divide"):
        return kept if kept in (*_LEVELS, OutputKind.RATIO) else OutputKind.OTHER
    if kept is OutputKind.COUNT and isinstance(numbers[0].value, float):
        return OutputKind.OTHER
    return kept


def _sum_kind(difference: bool, left: OutputKind, right: OutputKind) -> OutputKind:
    """The kind of a sum, or of a difference where `difference`, of two kinds."""
    price, distance = OutputKind.PRICE, OutputKind.PRICE_DISTANCE
    if difference and left == right == price:
        return distance
    if {left, right} == {price, distance} and (not difference or left is price):
        return price
    if left == right and left in (distance, OutputKind.RATIO, OutputKind.COUNT):
        return left
    return OutputKind.OTHER


def _require_combinable(name: str, body: Term, definitions: Mapping[str, FeatureDef]) -> None:
    """Refuse a combination that reads constants alone, or a window or a higher timeframe of
    constants alone, whose values would not fill the bars, and logic of what is not a flag."""
    if not reads_bars(body):
        raise ValueError(
            f"Expected combination {name} to read a column of the bars or a feature, got "
            "constants alone."
        )
    pending = [body]
    while pending:
        term = pending.pop()
        pending.extend(children_of(term))
        if isinstance(term, Window | AtTimeframe) and not reads_bars(term.of):
            raise ValueError(
                f"Expected the {term.kind} of combination {name} over a column of the bars or a "
                "feature, got constants alone."
            )
        operands = _logic_operands(term)
        kinds = [output_kind(each, definitions) for each in operands]
        if any(kind is not OutputKind.FLAG for kind in kinds):
            raise ValueError(
                f"Expected flags as the terms of {term.kind} in combination {name}, got "
                f"{', '.join(kinds)}."
            )


def _logic_operands(term: Term) -> Sequence[Term]:
    if isinstance(term, Negation):
        return (term.of,)
    if isinstance(term, BinaryOperation) and term.kind in ("and", "or"):
        return (term.left, term.right)
    return ()


@dataclass(frozen=True)
class _Read:
    """A feature a combination reads with its parameters, and the alias of its columns, None
    where it reads them under its outputs' names."""

    key: FeatureKey
    spec: FeatureSpec
    alias: str | None

    def column(self, output: str) -> str:
        """The column the combination reads the output `output` under."""
        if self.alias is None:
            return output
        return slot_columns(self.alias, self.spec)[output]

    def declared(self) -> str:
        """The feature as the combination's decorator declares it, a `FeatureInput`."""
        definition = self.spec.definition
        parameters = python_literal(self.spec.parameters.model_dump(mode="json"))
        written = [
            f"name={json.dumps(definition.name)}",
            f"hash={json.dumps(definition.hash)}",
            f"parameters={parameters}",
        ]
        if self.alias is not None:
            written.append(f"alias={json.dumps(self.alias)}")
        return f"ff.features.FeatureInput({', '.join(written)})"


def _reads(body: Term, definitions: Mapping[str, FeatureDef]) -> list[_Read]:
    """Each feature `body` reads with its parameters, first seen first, with an alias, counted
    by its name, where its outputs' names meet another's."""
    found: dict[FeatureKey, FeatureSpec] = {}
    for leaf in leaves(body):
        if isinstance(leaf, FeatureOutput) and feature_key(leaf) not in found:
            found[feature_key(leaf)] = definitions[leaf.hash](**leaf.parameters)
    names = Counter(output for spec in found.values() for output in spec.definition.outputs)
    counted: Counter[str] = Counter()
    reads = []
    for key, spec in found.items():
        alias = None
        if any(names[output] > 1 for output in spec.definition.outputs):
            counted[spec.definition.name] += 1
            alias = f"{spec.definition.name}_{counted[spec.definition.name]}"
        reads.append(_Read(key, spec, alias))
    return reads


class _Expressions:
    """The Polars expression of each term of a combination, as text, each feature's output read
    under its column (`_Read.column`)."""

    def __init__(self, reads: Mapping[FeatureKey, _Read]) -> None:
        self._reads = reads

    def bare(self, term: Term) -> str:
        """The expression of `term`, without parentheses around it."""
        if isinstance(term, Constant):
            return f"pl.lit({python_literal(term.value)})"
        if isinstance(term, Column):
            return _column(term)
        if isinstance(term, FeatureOutput):
            return f"pl.col({json.dumps(self._reads[feature_key(term)].column(term.output))})"
        if isinstance(term, Negation):
            return f"~{self.operand(term.of)}"
        if isinstance(term, Window):
            return self._window(term)
        if isinstance(term, BinaryOperation):
            return self._pair(term)
        raise ValueError(
            "Expected each at_timeframe below a combination's top as a feature it reads, got "
            f"{term.model_dump_json()}."
        )

    def operand(self, term: Term) -> str:
        """The expression of `term`, in parentheses where an operator or a method applied to it
        would bind to a part of it."""
        text = self.bare(term)
        compound = isinstance(term, BinaryOperation | Negation) or (
            isinstance(term, Window) and term.kind in ("percent_rank", "z_score")
        )
        return f"({text})" if compound else text

    def _pair(self, term: BinaryOperation) -> str:
        left, right = self.operand(term.left), self.operand(term.right)
        if term.kind in _OPERATORS:
            return f"{left} {_OPERATORS[term.kind]} {right}"
        if term.kind == "multiply":
            return f"{left}.cast(pl.Float64) * {right}"
        if term.kind == "divide":
            return f"pl.when({right} != 0).then({left} / {right})"
        if term.kind == "ratio_to":
            return f"pl.when({right} != 0).then(({left} - {right}) / {right})"
        now, before = (">", "<=") if term.kind == "crosses_above" else ("<", ">=")
        earlier = f"{self._lagged(term.left)} {before} {self._lagged(term.right)}"
        return f"({left} {now} {right}) & ({earlier})"

    def _lagged(self, term: Term) -> str:
        """The expression of `term` one bar before: itself where it is constants alone."""
        text = self.operand(term)
        return f"{text}.shift(1)" if reads_bars(term) else text

    def _window(self, term: Window) -> str:
        of, n = self.operand(term.of), term.n
        if term.kind == "rolling_std":
            return f"{of}.rolling_std({n}, ddof=0)"
        if term.kind == "rolling_rank":
            return f'{of}.rolling_rank({n}, method="max")'
        if term.kind == "percent_rank":
            return f'({of}.rolling_rank({n}, method="max") - 1) / {n - 1}'
        if term.kind == "z_score":
            deviation = f"{of}.rolling_std({n}, ddof=0)"
            return f"pl.when({deviation} != 0).then(({of} - {of}.rolling_mean({n})) / {deviation})"
        if term.kind == "lag":
            return f"{of}.shift({n})"
        return f"{of}.{term.kind}({n})"


def _column(term: Column) -> str:
    """The expression of a column of the bars, another instrument's suffixed with its root, the
    volume and the number of trades as signed integers."""
    name = term.column if term.instrument is None else f"{term.column}_{term.instrument}"
    read = f"pl.col({json.dumps(name)})"
    return f"{read}.cast(pl.Int64)" if term.column in _INTEGER_COLUMNS else read


def python_literal(value: JsonValue) -> str:
    """`value`, a JSON value, as Python writes it, a mapping's keys sorted."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(python_literal(each) for each in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{json.dumps(key)}: {python_literal(value[key])}" for key in sorted(value))
        return "{" + ", ".join(pairs) + "}"
    return repr(value)
