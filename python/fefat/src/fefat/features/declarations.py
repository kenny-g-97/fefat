"""What a feature's decorator writes (step 3.1, D-71): a version keeps the feature's source, the
`@feature(...)` call included, and its hash covers that text, the hashes of the features it reads,
and its parameter schema. So the outputs, the inputs other than features, and the warm-ups, in
bars and in sessions (step 3.6, D-78), are written in the call as literals, and one bound to a
name defined elsewhere is refused, since it would change no hash; `load` holds a saved record's
declarations to its code the same way.

    @ff.feature(
        params={"n": 14},
        warmup=lambda n: 10 * n,
        inputs=[base, ff.features.TimeframeInput(timeframe="15m")],
        outputs={"rsi": "ratio"},
    )
"""

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fefat.features.inputs import (
    DatasetInput,
    DeclaredInput,
    FeatureInput,
    InstrumentInput,
    OutputKind,
    TimeframeInput,
    TradesInput,
)

INPUT_KINDS = (FeatureInput, InstrumentInput, TimeframeInput, DatasetInput, TradesInput)
_INPUTS_BY_NAME = {kind.__name__: kind for kind in INPUT_KINDS}


class WarmupUnit(StrEnum):
    """What a feature's warm-up counts (D-78): bars of its grid, its `warmup`, or whole sessions,
    its `warmup_sessions`, as for the session before or the week so far."""

    BARS = "bars"
    SESSIONS = "sessions"

    @property
    def keyword(self) -> str:
        """The decorator's keyword that declares it."""
        return "warmup" if self is WarmupUnit.BARS else "warmup_sessions"

    @property
    def label(self) -> str:
        """How a message names it."""
        return "warm-up" if self is WarmupUnit.BARS else "session warm-up"


@dataclass(frozen=True)
class WrittenDeclarations:
    """What a feature's source writes: the name its `def` gives, and the declarations of its
    `@feature(...)` call: its outputs with their kinds, its inputs, each the input it writes or
    None where it names a feature, and its warm-ups, in bars and in sessions, each a number or the
    text of a lambda."""

    name: str
    outputs: Mapping[str, str]
    inputs: tuple[DeclaredInput | None, ...]
    warmup: int | str
    warmup_sessions: int | str


def written_declarations(name: str, code: str) -> WrittenDeclarations:
    """The declarations the `@feature(...)` call in `code`, a feature's normalised source,
    writes; the defaults where it writes none: one output named after the feature of kind
    `other`, no inputs, and no warm-up."""
    defined, keywords = _decorated(name, code)
    outputs, inputs = keywords.get("outputs"), keywords.get("inputs")
    warmups = {
        unit: _written_warmup(name, code, keywords.get(unit.keyword), unit) for unit in WarmupUnit
    }
    return WrittenDeclarations(
        name=defined,
        outputs={name: "other"} if outputs is None else _written_outputs(name, outputs),
        inputs=() if inputs is None else _written_inputs(name, inputs),
        warmup=warmups[WarmupUnit.BARS],
        warmup_sessions=warmups[WarmupUnit.SESSIONS],
    )


def inputs_as_written(
    declared: Sequence[DeclaredInput], written: Sequence[DeclaredInput | None]
) -> bool:
    """Whether `declared` are the inputs the call writes: a feature where it names one, and the
    same input where it writes one."""
    return len(declared) == len(written) and all(
        isinstance(each, FeatureInput) if literal is None else each == literal
        for each, literal in zip(declared, written, strict=True)
    )


def _decorated(name: str, code: str) -> tuple[str, dict[str | None, ast.expr]]:
    """The name the `def` in `code` gives, and the keywords of the `@feature(...)` call among its
    decorators; a feature made without it, or whose declarations it unpacks from a mapping, is
    refused."""
    statement = ast.parse(code).body[0]
    call = feature_call(statement)
    if call is None or not isinstance(statement, ast.FunctionDef):
        raise ValueError(
            f"Expected feature {name} defined with def under its decorator, @ff.feature(...), "
            "whose declarations its version keeps, got a function without it."
        )
    if any(keyword.arg is None for keyword in call.keywords):
        raise ValueError(
            f"Expected the declarations of feature {name} written in its decorator by name, got "
            f"{ast.unparse(call)}."
        )
    return statement.name, {keyword.arg: keyword.value for keyword in call.keywords}


def feature_call(statement: ast.stmt) -> ast.Call | None:
    """The `@feature(...)` call among a function's decorators, or None."""
    if not isinstance(statement, ast.FunctionDef):
        return None
    decorators = statement.decorator_list
    calls = (
        each for each in decorators if isinstance(each, ast.Call) and _names(each.func, "feature")
    )
    return next(calls, None)


def _names(node: ast.expr, wanted: str) -> bool:
    """Whether `node` names `wanted`, as `feature`, `ff.feature`, or `features.feature` do."""
    if isinstance(node, ast.Name):
        return node.id == wanted
    return isinstance(node, ast.Attribute) and node.attr == wanted


def _written_outputs(name: str, node: ast.expr) -> dict[str, str]:
    """The outputs a mapping of names to kinds writes, each kind a string or a member of
    `OutputKind`, and the default one, named after the feature and of kind `other`, where it
    writes None."""
    if isinstance(node, ast.Constant) and node.value is None:
        return {name: "other"}
    written = _literal_outputs(node) if isinstance(node, ast.Dict) else None
    if written is not None:
        return written
    raise ValueError(
        f"Expected the outputs of feature {name} written in its decorator as a mapping of names "
        f'to kinds, such as {{"rsi": "ratio"}}, got {ast.unparse(node)}.'
    )


def _literal_outputs(mapping: ast.Dict) -> dict[str, str] | None:
    """The outputs a mapping writes, or None when a name or a kind in it is not a literal."""
    names = [_text(key) for key in mapping.keys]
    kinds = [_kind(value) for value in mapping.values]
    if None in names or None in kinds:
        return None
    return {str(output): str(kind) for output, kind in zip(names, kinds, strict=True)}


def _text(node: ast.expr | None) -> str | None:
    """The string a literal writes, or None for anything else, such as a `**` unpacking."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kind(node: ast.expr) -> str | None:
    """An output's kind as written: a string, or a member of `OutputKind`, such as
    `ff.features.OutputKind.RATIO`."""
    if isinstance(node, ast.Attribute) and _names(node.value, "OutputKind"):
        member = OutputKind.__members__.get(node.attr)
        return None if member is None else member.value
    return _text(node)


def _written_inputs(name: str, node: ast.expr) -> tuple[DeclaredInput | None, ...]:
    """The inputs a literal list writes: None where it names a feature, and the input where it
    writes one with literal values, such as `InstrumentInput(root="MNQ")`."""
    if not isinstance(node, ast.List | ast.Tuple):
        raise ValueError(
            f"Expected the inputs of feature {name} written in its decorator as a list, got "
            f"{ast.unparse(node)}."
        )
    return tuple(_written_input(name, each) for each in node.elts)


def _written_input(name: str, node: ast.expr) -> DeclaredInput | None:
    if isinstance(node, ast.Name | ast.Attribute):
        return None
    written = _literal_input(node) if isinstance(node, ast.Call) else None
    if written is not None:
        return written
    raise ValueError(
        f"Expected each input of feature {name} written in its decorator, a feature by its name "
        f'or an input with literal values such as InstrumentInput(root="MNQ"), got '
        f"{ast.unparse(node)}."
    )


def _literal_input(call: ast.Call) -> DeclaredInput | None:
    """The input a call of an input kind writes with literal keywords alone, or None."""
    kind = _input_kind(call.func)
    try:
        values = {str(keyword.arg): ast.literal_eval(keyword.value) for keyword in call.keywords}
    except (ValueError, TypeError):
        return None
    if kind is None or call.args:
        return None
    return kind.model_validate(values)


def _input_kind(callee: ast.expr) -> type[DeclaredInput] | None:
    """The input kind a call names, as `InstrumentInput` or `ff.features.InstrumentInput`."""
    if isinstance(callee, ast.Attribute):
        return _INPUTS_BY_NAME.get(callee.attr)
    if isinstance(callee, ast.Name):
        return _INPUTS_BY_NAME.get(callee.id)
    return None


def _written_warmup(name: str, code: str, node: ast.expr | None, unit: WarmupUnit) -> int | str:
    """The warm-up in `unit` the call writes: none where it writes none, a number, or the text of
    a lambda of the feature's parameters. One bound to a name defined elsewhere is refused."""
    if node is None:
        return 0
    if isinstance(node, ast.Lambda):
        segment = ast.get_source_segment(code, node)
        if segment is not None:
            return segment
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    raise ValueError(
        f"Expected the {unit.label} of feature {name} written in its decorator, as a number of "
        f"{unit} or a lambda of its parameters, got {ast.unparse(node)}."
    )
