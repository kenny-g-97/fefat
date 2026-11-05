"""Combinators (step 3.7, `02-engine-and-data.md` §6): new features from existing ones without
writing their code. A combination is a description (`fefat.features.combinations`), a tree of
terms that the functions here build and Python's operators join, and `define` makes it a feature
as any other, its code generated from the description (`fefat.features.combination_code`) and
built from that text (`ff.features.from_source`), so that it is hashed, versioned, validated, and
read by a strategy as a hand-written feature is, and its version keeps the description.

    from fefat.features import combine

    rsi = ff.indicators.rsi
    rsi_stretch = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 10))
    rsi_stretch.code  # its generated source
    rsi_stretch.combination  # its description, as JSON through model_dump(mode="json")

A term is a feature with its parameters, or one of a feature's outputs (`output`), a column of
the bars or of another instrument's (`column`), or a number (`constant`), and the combinators are
arithmetic (`add`, `subtract`, `multiply`, `divide`, `ratio_to`), comparisons and logic
(`greater_than`, `crosses_above`, `crosses_below`, `and_`, `or_`, `not_`), windows
(`rolling_mean`, `rolling_std`, `rolling_min`, `rolling_max`, `rolling_rank`, `lag`),
normalisations (`percent_rank`, `z_score`, `scaled_by_atr`), a higher timeframe
(`at_timeframe`), and spreads across instruments, such as
`subtract(column("close"), column("close", instrument="NQ"))`. A feature a combination reads is
named in its code with its parameters, its defaults filled in, so that the combination needs no
slot of it, and is found among those this process defined or else in the library
(`ff.features.ref`); an `at_timeframe` inside a combination is a feature of its own,
`<name>_<timeframe>`, which the combination reads."""

import dataclasses

from fefat.features.combination_code import combination_code
from fefat.features.combinations import (
    AtTimeframe,
    BinaryOperation,
    Column,
    Constant,
    FeatureOutput,
    Negation,
    Operand,
    Term,
    Window,
    WindowKind,
    children_of,
    feature_output,
    leaves,
    pair,
    term_of,
    with_children,
)
from fefat.features.definition import FeatureDef
from fefat.features.evaluation import FeatureSpec
from fefat.features.registry import register
from fefat.features.source_code import from_source
from fefat.features.versions import saved_definition


def column(name: str, instrument: str | None = None) -> Column:
    """The column `name` of the signal bars, or of `instrument`'s bars, another root's, at the
    signal bars' timeframe."""
    return Column.model_validate({"column": name, "instrument": instrument})


def constant(value: bool | int | float) -> Constant:
    """A number or a flag, the same on every bar; a price in the bars' 1e-9 units."""
    return Constant(value=value)


def output(feature: FeatureSpec, name: str) -> FeatureOutput:
    """The output `name` of `feature`, a feature of several outputs with its parameters."""
    return feature_output(feature, name)


def add(left: Operand, right: Operand) -> BinaryOperation:
    return pair("add", left, right)


def subtract(left: Operand, right: Operand) -> BinaryOperation:
    return pair("subtract", left, right)


def multiply(left: Operand, right: Operand) -> BinaryOperation:
    """`left` times `right`, in floats."""
    return pair("multiply", left, right)


def divide(left: Operand, right: Operand) -> BinaryOperation:
    """`left` over `right`, null where `right` is 0."""
    return pair("divide", left, right)


def ratio_to(left: Operand, right: Operand) -> BinaryOperation:
    """How far `left` lies from `right` as a share of it, `(left - right) / right`, null where
    `right` is 0, as the return of the close from its VWAP."""
    return pair("ratio_to", left, right)


def greater_than(left: Operand, right: Operand) -> BinaryOperation:
    """Whether `left` is above `right`; `greater_than(right, left)` for below."""
    return pair("greater_than", left, right)


def crosses_above(left: Operand, right: Operand) -> BinaryOperation:
    """Whether `left` is above `right` on the bar and was at or below it on the bar before."""
    return pair("crosses_above", left, right)


def crosses_below(left: Operand, right: Operand) -> BinaryOperation:
    """Whether `left` is below `right` on the bar and was at or above it on the bar before."""
    return pair("crosses_below", left, right)


def and_(left: Operand, right: Operand) -> BinaryOperation:
    """Whether both flags are true, `left & right`."""
    return pair("and", left, right)


def or_(left: Operand, right: Operand) -> BinaryOperation:
    """Whether either flag is true, `left | right`."""
    return pair("or", left, right)


def not_(term: Operand) -> Negation:
    """Whether the flag is false, `~term`."""
    return Negation(of=term_of(term))


def rolling_mean(term: Operand, n: int) -> Window:
    """The mean of the last `n` bars of `term`."""
    return _window("rolling_mean", term, n)


def rolling_std(term: Operand, n: int) -> Window:
    """The standard deviation of the last `n` bars of `term`, the population's (D-75)."""
    return _window("rolling_std", term, n)


def rolling_min(term: Operand, n: int) -> Window:
    """The lowest of the last `n` bars of `term`."""
    return _window("rolling_min", term, n)


def rolling_max(term: Operand, n: int) -> Window:
    """The highest of the last `n` bars of `term`."""
    return _window("rolling_max", term, n)


def rolling_rank(term: Operand, n: int) -> Window:
    """The rank of `term` among its last `n` bars, from 1 for the lowest to `n`, ties ranked at
    their highest."""
    return _window("rolling_rank", term, n)


def percent_rank(term: Operand, n: int) -> Window:
    """Where `term` lies among its last `n` bars, from 0 at their lowest to 1 at their highest,
    `(rolling_rank - 1) / (n - 1)`."""
    return _window("percent_rank", term, n)


def z_score(term: Operand, n: int) -> Window:
    """How many standard deviations of its last `n` bars `term` lies from their mean, null where
    they have not moved."""
    return _window("z_score", term, n)


def lag(term: Operand, n: int = 1) -> Window:
    """`term` `n` bars before."""
    return _window("lag", term, n)


def scaled_by_atr(term: Operand, n: int = 14) -> BinaryOperation:
    """`term` in ATRs of `n` bars, a distance of price over `ff.indicators.atr(n)`."""
    from fefat.indicators.ranges import (
        atr,
    )  # the indicators are defined as features of this package

    return divide(term, atr(n))


def at_timeframe(term: Operand, timeframe: str) -> AtTimeframe:
    """`term` evaluated on the bars of `timeframe`, such as `15m`, each value seen from its
    bar's close on the bars that read it."""
    return AtTimeframe.model_validate({"of": term_of(term), "timeframe": timeframe})


def define(name: str, term: Operand) -> FeatureDef:
    """The feature `name` that `term` describes (module docstring), registered as this process's
    definition of its hash with its description."""
    return _defined(name, _completed(term_of(term)), {name}, {})


def _window(kind: WindowKind, term: Operand, n: int) -> Window:
    return Window(kind=kind, of=term_of(term), n=n)


def _defined(
    name: str, description: Term, used: set[str], nested: dict[str, FeatureOutput]
) -> FeatureDef:
    """The feature `name` that `description` describes, each `at_timeframe` below its top a
    feature of its own, named apart from those in `used`, the same one where it repeats."""
    lowered = _lowered(name, description, used, nested)
    definitions = {
        leaf.hash: _definition_of(leaf)
        for leaf in leaves(lowered)
        if isinstance(leaf, FeatureOutput)
    }
    code = combination_code(name, lowered, definitions)
    definition = from_source(code)
    described = dataclasses.replace(definition, combination=description)
    register(described)
    return described


def _lowered(name: str, term: Term, used: set[str], nested: dict[str, FeatureOutput]) -> Term:
    """`term` with each `at_timeframe` below its top a feature the combination `name` reads."""
    if isinstance(term, AtTimeframe):
        return term.model_copy(update={"of": _below(name, term.of, used, nested)})
    return _below(name, term, used, nested)


def _below(name: str, term: Term, used: set[str], nested: dict[str, FeatureOutput]) -> Term:
    if isinstance(term, AtTimeframe):
        described = term.model_dump_json()
        if described not in nested:
            feature_name = _apart(f"{name}_{term.timeframe}", used)
            feature = _defined(feature_name, term, used, nested)
            nested[described] = FeatureOutput(
                name=feature.name, hash=feature.hash, parameters={}, output=feature.name
            )
        return nested[described]
    children = children_of(term)
    if not children:
        return term
    return with_children(term, tuple(_below(name, child, used, nested) for child in children))


def _apart(name: str, used: set[str]) -> str:
    """`name`, numbered from 2 where `used` holds it, kept in `used`."""
    chosen, number = name, 1
    while chosen in used:
        number += 1
        chosen = f"{name}_{number}"
    used.add(chosen)
    return chosen


def _completed(term: Term) -> Term:
    """`term` with each feature's output checked against its definition and its parameters
    completed with their defaults, as the combination's code names them."""
    if isinstance(term, FeatureOutput):
        definition = _definition_of(term)
        completed = feature_output(definition(**term.parameters), term.output)
        return term.model_copy(update={"parameters": completed.parameters})
    children = children_of(term)
    if not children:
        return term
    return with_children(term, tuple(_completed(child) for child in children))


def _definition_of(term: FeatureOutput) -> FeatureDef:
    """The definition of the feature `term` reads, of its name, this process's or the library's
    (`saved_definition`)."""
    definition = saved_definition(term.name, term.hash, "a combination")
    if definition.name != term.name:
        raise ValueError(
            f"Expected the feature of hash {term.hash[:12]} named {term.name}, got "
            f"{definition.name}."
        )
    return definition


__all__ = [
    "add",
    "and_",
    "at_timeframe",
    "column",
    "constant",
    "crosses_above",
    "crosses_below",
    "define",
    "divide",
    "greater_than",
    "lag",
    "multiply",
    "not_",
    "or_",
    "output",
    "percent_rank",
    "ratio_to",
    "rolling_max",
    "rolling_mean",
    "rolling_min",
    "rolling_rank",
    "rolling_std",
    "scaled_by_atr",
    "subtract",
    "z_score",
]
