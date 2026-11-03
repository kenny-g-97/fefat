"""What a feature's decorator writes (step 3.1, D-71): a version keeps the feature's source, the
`@feature(...)` call included, and its hash covers that text, the hashes of the features it reads,
and its parameter schema. So the outputs, the inputs other than features, and the warm-up are
written in the call as literals, and one bound to a name defined elsewhere is refused, since it
would change no hash; `load` holds a saved record's declarations to its code the same way.

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

from fefat.features.inputs import (
    DatasetInput,
    DeclaredInput,
    FeatureInput,
    InstrumentInput,
    TimeframeInput,
)

INPUT_KINDS = (FeatureInput, InstrumentInput, TimeframeInput, DatasetInput)
_INPUTS_BY_NAME = {kind.__name__: kind for kind in INPUT_KINDS}


@dataclass(frozen=True)
class WrittenDeclarations:
    """The declarations of a feature's `@feature(...)` call: its outputs with their kinds, its
    inputs, each the input it writes or None where it names a feature, and its warm-up, a number
    of bars or the text of a lambda."""

    outputs: Mapping[str, str]
    inputs: tuple[DeclaredInput | None, ...]
    warmup: int | str


def written_declarations(name: str, code: str) -> WrittenDeclarations:
    """The declarations the `@feature(...)` call in `code`, a feature's normalised source,
    writes; the defaults where it writes none: one output named after the feature of kind
    `other`, no inputs, and no warm-up."""
    keywords = _keywords(name, code)
    outputs, inputs, warmup = (keywords.get(key) for key in ("outputs", "inputs", "warmup"))
    return WrittenDeclarations(
        outputs={name: "other"} if outputs is None else _written_outputs(name, outputs),
        inputs=() if inputs is None else _written_inputs(name, inputs),
        warmup=0 if warmup is None else _written_warmup(name, code, warmup),
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


def _keywords(name: str, code: str) -> dict[str | None, ast.expr]:
    """The keywords of the `@feature(...)` call among the decorators of the function in `code`;
    a feature made without it, or whose declarations it unpacks from a mapping, is refused."""
    statement = ast.parse(code).body[0]
    decorators = statement.decorator_list if isinstance(statement, ast.FunctionDef) else []
    for decorator in decorators:
        if isinstance(decorator, ast.Call) and _names_feature(decorator.func):
            if any(keyword.arg is None for keyword in decorator.keywords):
                raise ValueError(
                    f"Expected the declarations of feature {name} written in its decorator by "
                    f"name, got {ast.unparse(decorator)}."
                )
            return {keyword.arg: keyword.value for keyword in decorator.keywords}
    raise ValueError(
        f"Expected feature {name} defined with def under its decorator, @ff.feature(...), whose "
        "declarations its version keeps, got a function without it."
    )


def _names_feature(callee: ast.expr) -> bool:
    """Whether a decorator calls `feature`, as `@feature`, `@ff.feature`, or `@features.feature`."""
    if isinstance(callee, ast.Name):
        return callee.id == "feature"
    return isinstance(callee, ast.Attribute) and callee.attr == "feature"


def _written_outputs(name: str, node: ast.expr) -> dict[str, str]:
    """The outputs a literal mapping of names to kinds writes, and the default one, named after
    the feature and of kind `other`, where it writes None."""
    if isinstance(node, ast.Constant) and node.value is None:
        return {name: "other"}
    try:
        outputs = ast.literal_eval(node)
    except (ValueError, TypeError):
        outputs = None
    if isinstance(outputs, dict) and all(
        isinstance(output, str) and isinstance(kind, str) for output, kind in outputs.items()
    ):
        return outputs
    raise ValueError(
        f"Expected the outputs of feature {name} written in its decorator as a mapping of names "
        f'to kinds, such as {{"rsi": "ratio"}}, got {ast.unparse(node)}.'
    )


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


def _written_warmup(name: str, code: str, node: ast.expr) -> int | str:
    """The warm-up the call writes: a number of bars, or the text of a lambda of the feature's
    parameters. One bound to a name defined elsewhere is refused."""
    if isinstance(node, ast.Lambda):
        segment = ast.get_source_segment(code, node)
        if segment is not None:
            return segment
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    raise ValueError(
        f"Expected the warm-up of feature {name} written in its decorator, as a number of bars or "
        f"a lambda of its parameters, got {ast.unparse(node)}."
    )
