"""The description of a combination (step 3.7, `fefat.features.combine`): a tree of terms, each a
frozen model tagged by its `kind`, from which the combination's code is generated
(`fefat.features.combination_code`) and which its version keeps, so that the builder of Phase 6
renders it and edits it (`docs/engine-guide.md`, "Combining features").

    rsi(14) - rolling_mean(rsi(14), 10)
    {"kind": "subtract",
     "left": {"kind": "feature", "name": "rsi", "hash": "…", "parameters": {"n": 14},
              "output": "rsi"},
     "right": {"kind": "rolling_mean", "of": {"kind": "feature", …}, "n": 10}}

Its leaves are a `constant`, a `column` of the signal bars or of another `instrument`'s, and a
`feature`'s output with its parameters, the feature found by its content hash. Its operations are
`add`, `subtract`, `multiply`, `divide`, `ratio_to`, `greater_than`, `crosses_above`,
`crosses_below`, `and`, and `or` of a `left` and a `right` term; `not` of a term; the windows
`rolling_mean`, `rolling_std`, `rolling_min`, `rolling_max`, `rolling_rank`, `percent_rank`,
`z_score`, and `lag` of a term over `n` bars; and `at_timeframe`, a term evaluated on the bars of
another `timeframe`. Terms also combine through Python's operators, `+`, `-`, `*`, `/`, `>`, `<`,
`&`, `|`, and `~`, beside a feature with its parameters, so that
`rsi(14) - rolling_mean(rsi(14), 10)` is a combination."""

import math
from collections.abc import Iterator
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from fefat.features.definition import FeatureDef
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import TimeframeText
from fefat.market.schema import FrozenModel

BarColumn = Literal["open", "high", "low", "close", "close_raw", "vwap", "volume", "trade_count"]
"""A column of the bars a combination reads: a price, the close of a continuous series moved by
its rolls' gaps (D-09) or `close_raw`, the contract's own, or the volume or number of trades."""
BinaryKind = Literal[
    "add",
    "subtract",
    "multiply",
    "divide",
    "ratio_to",
    "greater_than",
    "crosses_above",
    "crosses_below",
    "and",
    "or",
]
"""An operation on two terms."""
WindowKind = Literal[
    "rolling_mean",
    "rolling_std",
    "rolling_min",
    "rolling_max",
    "rolling_rank",
    "percent_rank",
    "z_score",
    "lag",
]
"""A window over the last bars of a term."""
_TWO_OR_MORE_BARS = frozenset({"rolling_std", "rolling_rank", "percent_rank", "z_score"})


class _Operators:
    """Python's operators on a term, each giving another: arithmetic, `>` and `<`, and the logic
    of `&`, `|`, and `~`."""

    def __add__(self, other: "Operand") -> "BinaryOperation":
        return pair("add", self, other)

    def __radd__(self, other: "Operand") -> "BinaryOperation":
        return pair("add", other, self)

    def __sub__(self, other: "Operand") -> "BinaryOperation":
        return pair("subtract", self, other)

    def __rsub__(self, other: "Operand") -> "BinaryOperation":
        return pair("subtract", other, self)

    def __mul__(self, other: "Operand") -> "BinaryOperation":
        return pair("multiply", self, other)

    def __rmul__(self, other: "Operand") -> "BinaryOperation":
        return pair("multiply", other, self)

    def __truediv__(self, other: "Operand") -> "BinaryOperation":
        return pair("divide", self, other)

    def __rtruediv__(self, other: "Operand") -> "BinaryOperation":
        return pair("divide", other, self)

    def __gt__(self, other: "Operand") -> "BinaryOperation":
        return pair("greater_than", self, other)

    def __lt__(self, other: "Operand") -> "BinaryOperation":
        return pair("greater_than", other, self)

    def __and__(self, other: "Operand") -> "BinaryOperation":
        return pair("and", self, other)

    def __rand__(self, other: "Operand") -> "BinaryOperation":
        return pair("and", other, self)

    def __or__(self, other: "Operand") -> "BinaryOperation":
        return pair("or", self, other)

    def __ror__(self, other: "Operand") -> "BinaryOperation":
        return pair("or", other, self)

    def __invert__(self) -> "Negation":
        return Negation(of=term_of(self))

    def __bool__(self) -> bool:
        raise TypeError(
            "Expected the terms of a combination joined with &, |, and ~, got one tested for "
            "truth, as Python's and, or, and not, and a chained comparison such as 30 < rsi < 70 "
            "test it: write (rsi > 30) & (rsi < 70)."
        )


class Constant(FrozenModel, _Operators):
    """A number or a flag, the same on every bar; a price in the bars' 1e-9 units."""

    kind: Literal["constant"] = "constant"
    value: bool | int | float

    @field_validator("value")
    @classmethod
    def _finite(cls, value: bool | float) -> bool | float:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Expected a finite number, got {value}")
        return value


class Column(FrozenModel, _Operators):
    """A column of the signal bars, or of another `instrument`'s bars at the same timeframe,
    joined as of each close (`InstrumentInput`)."""

    kind: Literal["column"] = "column"
    column: BarColumn
    instrument: str | None = Field(default=None, min_length=1)


class FeatureOutput(FrozenModel, _Operators):
    """The output `output` of the feature `name` with its `parameters`, the feature found by its
    content hash."""

    kind: Literal["feature"] = "feature"
    name: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, JsonValue]
    output: str = Field(min_length=1)


class BinaryOperation(FrozenModel, _Operators):
    """An operation on a `left` and a `right` term (module docstring)."""

    kind: BinaryKind
    left: "Combination"
    right: "Combination"


class Negation(FrozenModel, _Operators):
    """`not` of a flag."""

    kind: Literal["not"] = "not"
    of: "Combination"


class Window(FrozenModel, _Operators):
    """A window over the last `n` bars of a term, `lag` the term `n` bars before."""

    kind: WindowKind
    of: "Combination"
    n: int = Field(ge=1)

    @model_validator(mode="after")
    def _enough_bars(self) -> Self:
        if self.kind in _TWO_OR_MORE_BARS and self.n < 2:
            raise ValueError(
                f"Expected a {self.kind} over two bars at least, which one leaves without a "
                f"value, got n={self.n}"
            )
        return self


class AtTimeframe(FrozenModel, _Operators):
    """A term evaluated on the bars of `timeframe`, each value seen from its bar's close."""

    kind: Literal["at_timeframe"] = "at_timeframe"
    of: "Combination"
    timeframe: TimeframeText


Term = Constant | Column | FeatureOutput | BinaryOperation | Negation | Window | AtTimeframe
"""A term of a combination."""
Combination = Annotated[Term, Field(discriminator="kind")]
"""A combination's description, a term read by its `kind`."""
Operand = Term | FeatureSpec | FeatureDef | str | bool | int | float
"""A term, or what `term_of` reads as one."""
TERMS = (Constant, Column, FeatureOutput, BinaryOperation, Negation, Window, AtTimeframe)
"""The models of `Term`, which `term_of` takes as terms, as a test holds them."""

for _model in (BinaryOperation, Negation, Window, AtTimeframe):
    _model.model_rebuild()


def term_of(value: object) -> Term:
    """`value` as a term: a term; a feature of one output with its parameters; a feature with
    its defaults; a column of the bars by its name; or a number. A flag the same on every bar is
    `combine.constant(True)`: a bare `True` or `False` is what `==` and `!=` give, which compare
    two terms as Python objects, so it is refused rather than read as a constant."""
    if isinstance(value, TERMS):
        return value
    if isinstance(value, bool):
        raise ValueError(
            f"Expected a term of a combination, got {value}: == and != compare terms as Python "
            "objects, not bar by bar, so write the comparison with > and <, and a flag the same on "
            "every bar as combine.constant(True)."
        )
    if isinstance(value, FeatureSpec):
        return feature_output(value)
    if isinstance(value, FeatureDef):
        return feature_output(value())
    if isinstance(value, str):
        return Column.model_validate({"column": value})
    if isinstance(value, int | float):
        return Constant(value=value)
    raise ValueError(
        "Expected a term of a combination, a feature, a column of the bars, or a number, got "
        f"{value!r}."
    )


def pair(kind: BinaryKind, left: object, right: object) -> BinaryOperation:
    """The operation `kind` on `left` and `right`, each read as a term (`term_of`)."""
    return BinaryOperation(kind=kind, left=term_of(left), right=term_of(right))


def feature_output(spec: FeatureSpec, output: str | None = None) -> FeatureOutput:
    """The output `output` of the feature `spec`, its one output where `output` is None."""
    definition = spec.definition
    outputs = list(definition.outputs)
    if output is None and len(outputs) > 1:
        raise ValueError(
            f"Expected a feature of one output, got {definition.name} with {', '.join(outputs)}: "
            f"name the output, such as combine.output({definition.name}(...), {outputs[0]!r})."
        )
    chosen = outputs[0] if output is None else output
    if chosen not in outputs:
        raise ValueError(
            f"Expected an output of feature {definition.name}, {', '.join(outputs)}, got "
            f"{chosen!r}."
        )
    parameters = spec.parameters.model_dump(mode="json")
    return FeatureOutput(
        name=definition.name, hash=definition.hash, parameters=parameters, output=chosen
    )


def children_of(term: Term) -> tuple[Term, ...]:
    """The terms `term` operates on, left first; none for a leaf."""
    if isinstance(term, BinaryOperation):
        return (term.left, term.right)
    if isinstance(term, Negation | Window | AtTimeframe):
        return (term.of,)
    return ()


def with_children(term: Term, children: tuple[Term, ...]) -> Term:
    """`term` operating on `children` in place of its own (`children_of`)."""
    if isinstance(term, BinaryOperation):
        left, right = children
        return term.model_copy(update={"left": left, "right": right})
    if isinstance(term, Negation | Window | AtTimeframe):
        return term.model_copy(update={"of": children[0]})
    return term


def leaves(term: Term) -> Iterator[Term]:
    """The leaves of `term`, left to right: its constants, columns, and features' outputs."""
    children = children_of(term)
    if not children:
        yield term
    for child in children:
        yield from leaves(child)


def reads_bars(term: Term) -> bool:
    """Whether `term` reads a column or a feature, rather than constants alone."""
    return any(isinstance(leaf, Column | FeatureOutput) for leaf in leaves(term))
