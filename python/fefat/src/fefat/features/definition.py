"""The feature contract (`02-engine-and-data.md` §6, step 3.1, D-71): `@ff.feature` turns a
function of the signal bars and its typed parameters into a `FeatureDef`, whose content hash is
the feature's identity, and calling it with parameters gives a `FeatureSpec`
(`fefat.features.evaluation`).

    @ff.feature(params={"n": 14}, warmup=lambda n: 10 * n, outputs={"rsi": "ratio"})
    def rsi(bars: pl.LazyFrame, n: int) -> pl.Expr:
        change = pl.col("close").diff()
        rise, fall = change.clip(lower_bound=0), (-change).clip(lower_bound=0)
        return 100 - 100 / (1 + rise.ewm_mean(alpha=1 / n) / fall.ewm_mean(alpha=1 / n))

    rsi(n=14)  # a FeatureSpec: the definition and its parameters, validated
    rsi.hash  # SHA-256 of the normalised source, the features it reads, and the schema

The function takes the bars first, `load`'s signal bars (`SIGNAL_BAR_COLUMNS`) as a LazyFrame,
then its parameters by name, each annotated with its type, their defaults in `params` and never
in the signature, so that the decorator, which the hashed source includes, holds them. It returns
one Polars expression for its one output, or a mapping of its outputs' names to expressions, over
the bars' rows. A value at a row reads only bars closed by that row's `ts_close` (D-12): no
negative shift, backward fill, or centred window, which the lint of step 3.4 finds.

`outputs` names each output with its kind (`OutputKind`), one output named after the function
and of kind `other` when it is left out. `inputs` declares what the feature reads beside the
bars: other features, by their `FeatureDef`, and `InstrumentInput`, `TimeframeInput`, and
`DatasetInput`, which the runtime of step 3.2 evaluates. `warmup` is the number of bars before
the feature's values mean what they say, or a lambda of its parameters written in the
decorator, such as `lambda n: 10 * n`.

The hash covers the function's own text: a helper it calls is not versioned with it, and
neither is a declaration bound to a name defined elsewhere, but the features it reads, whose
hashes it covers (`BACKLOG.md`).
"""

import ast
import hashlib
import inspect
import json
import textwrap
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model

from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import (
    DatasetInput,
    DeclaredInput,
    FeatureInput,
    InstrumentInput,
    OutputKind,
    TimeframeInput,
)
from fefat.market.api import SIGNAL_BAR_COLUMNS

_RESERVED_OUTPUTS = frozenset({"ts_close", "warmup", *SIGNAL_BAR_COLUMNS})
_INPUT_KINDS = (FeatureInput, InstrumentInput, TimeframeInput, DatasetInput)
_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
_PARAMETERS_CONFIG = ConfigDict(frozen=True, extra="forbid", strict=True)


@dataclass(frozen=True)
class FeatureDef:
    """A feature's definition (the module docstring): its function, its normalised source, the
    model of its parameters, the inputs it declares beside the bars, its outputs with their kinds,
    its warm-up, and its content hash. Call it with parameters for a `FeatureSpec`."""

    name: str
    function: Callable[..., object]
    code: str
    parameter_model: type[BaseModel]
    inputs: tuple[DeclaredInput, ...]
    outputs: Mapping[str, OutputKind]
    warmup: int | Callable[..., object]
    warmup_text: str
    hash: str

    @property
    def parameter_schema(self) -> dict[str, typing.Any]:
        """The JSON schema of the feature's parameters: their types and defaults."""
        return self.parameter_model.model_json_schema()

    def __call__(self, **parameters: object) -> FeatureSpec:
        """The feature with `parameters`, the defaults filling those left out, validated
        strictly: `rsi(n="14")` is refused, never read as 14."""
        try:
            bound = self.parameter_model(**parameters)
        except ValidationError as error:
            raise ValueError(self._refusal(error)) from error
        return FeatureSpec(definition=self, parameters=bound, warmup=self._warmup_bars(bound))

    def _refusal(self, error: ValidationError) -> str:
        """The first problem of `error` in words: the parameters expected, what came, and why."""
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        got = f"no {location}" if first["type"] == "missing" else f"{location}={first['input']!r}"
        expected = ", ".join(
            f"{name}: {_type_text(field.annotation)}"
            for name, field in self.parameter_model.model_fields.items()
        )
        reason = first["msg"].rstrip(".")
        return f"Expected the parameters of feature {self.name} as {{{expected}}}, got {got}: {reason}."

    def _warmup_bars(self, parameters: BaseModel) -> int:
        """The warm-up of the feature with `parameters`, in bars."""
        if not callable(self.warmup):
            return self.warmup
        read = inspect.signature(self.warmup).parameters
        bars = self.warmup(**{name: getattr(parameters, name) for name in read})
        if isinstance(bars, bool) or not isinstance(bars, int) or bars < 0:
            raise ValueError(
                f"Expected the warm-up of feature {self.name} as a whole number of bars, at least "
                f"0, got {bars!r} from {self.warmup_text} with {parameters!r}."
            )
        return bars


def feature(
    *,
    params: Mapping[str, object] | None = None,
    warmup: int | Callable[..., object] = 0,
    inputs: Sequence[FeatureDef | DeclaredInput] = (),
    outputs: Mapping[str, str] | None = None,
) -> Callable[[Callable[..., object]], FeatureDef]:
    """Define a feature (the module docstring): `params` gives its parameters' defaults, `warmup`
    its warm-up in bars or as a lambda of its parameters, `inputs` what it reads beside the bars,
    and `outputs` its outputs with their kinds."""

    def define(function: Callable[..., object]) -> FeatureDef:
        name = function.__name__
        code = _source(function)
        call = _feature_call(name, code)
        model = _parameter_model(name, function, {} if params is None else params)
        declared = tuple(_declared(name, each) for each in inputs)
        checked_warmup = _checked_warmup(name, warmup, model)
        return FeatureDef(
            name=name,
            function=function,
            code=code,
            parameter_model=model,
            inputs=declared,
            outputs=_outputs(name, {name: OutputKind.OTHER} if outputs is None else outputs),
            warmup=checked_warmup,
            warmup_text=_warmup_text(name, code, call, checked_warmup),
            hash=content_hash(code, declared, model.model_json_schema()),
        )

    return define


def content_hash(
    code: str, inputs: Sequence[DeclaredInput], parameter_schema: Mapping[str, object]
) -> str:
    """A feature's content hash (D-71): SHA-256 through `hashlib`, the store's hash, over its
    normalised source, the hashes of the features it reads in their declared order, and its
    parameter schema as JSON with sorted keys, each on lines of its own."""
    read = [declared.hash for declared in inputs if isinstance(declared, FeatureInput)]
    schema = json.dumps(parameter_schema, sort_keys=True, allow_nan=False)
    return hashlib.sha256("\n".join([code, *read, schema]).encode()).hexdigest()


def _source(function: Callable[..., object]) -> str:
    """The function's source as the hash reads it, its decorator included: dedented, with LF
    line ends and no trailing spaces, without blank lines around it, and one final newline, so
    that neither the file it came from nor its indentation there changes the hash."""
    try:
        text = inspect.getsource(function)
    except (OSError, TypeError) as error:
        raise ValueError(
            f"Expected the source of feature {function.__name__}, got none: define it in a file "
            f"or a notebook cell, whose text Python keeps ({error})."
        ) from error
    lines = textwrap.dedent(text.replace("\r\n", "\n")).split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n") + "\n"


def _feature_call(name: str, code: str) -> ast.Call:
    """The `@feature(...)` call among the function's decorators: its version keeps the
    declarations as that call writes them, so a feature made without it is refused."""
    statement = ast.parse(code).body[0]
    if isinstance(statement, ast.FunctionDef):
        for decorator in statement.decorator_list:
            if isinstance(decorator, ast.Call) and _names_feature(decorator.func):
                return decorator
    raise ValueError(
        f"Expected feature {name} defined with def under its decorator, @ff.feature(...), whose "
        "declarations its version keeps, got a function without it."
    )


def _names_feature(callee: ast.expr) -> bool:
    """Whether a decorator calls `feature`, as `@feature`, `@ff.feature`, or `@features.feature`."""
    if isinstance(callee, ast.Name):
        return callee.id == "feature"
    return isinstance(callee, ast.Attribute) and callee.attr == "feature"


def _parameter_model(
    name: str, function: Callable[..., object], params: Mapping[str, object]
) -> type[BaseModel]:
    """The strict, frozen model of the feature's parameters, those after the bars, each with its
    annotation and its default from `params`, a parameter without one required."""
    signature = list(inspect.signature(function).parameters.values())
    if not signature:
        raise ValueError(f"Expected the bars as the first parameter of feature {name}, got none.")
    named = [parameter.name for parameter in signature[1:]]
    unknown = sorted(set(params) - set(named))
    if unknown:
        raise ValueError(
            f"Expected params to name parameters of feature {name}, got {', '.join(unknown)}, "
            "which its signature lacks."
        )
    hints = typing.get_type_hints(function, include_extras=True)
    fields: dict[str, typing.Any] = {
        each.name: _field(name, each, hints, params) for each in signature[1:]
    }
    model = create_model(f"{name}_parameters", __config__=_PARAMETERS_CONFIG, **fields)
    try:
        json.dumps(model.model_json_schema(), allow_nan=False)
    except ValueError as error:
        raise ValueError(
            f"Expected defaults of feature {name} that JSON can write, got: {error}."
        ) from error
    return model


def _field(
    name: str,
    parameter: inspect.Parameter,
    hints: Mapping[str, typing.Any],
    params: Mapping[str, object],
) -> tuple[typing.Any, object]:
    """A parameter's field: its type, and its default from `params` checked strictly, or `...`,
    required, when `params` gives none."""
    if parameter.kind not in _NAMED:
        raise ValueError(f"Expected the parameters of feature {name} by name, got {parameter}.")
    if parameter.name not in hints:
        raise ValueError(
            f"Expected each parameter of feature {name} annotated with its type, got "
            f"{parameter.name} without one."
        )
    if parameter.default is not inspect.Parameter.empty:
        raise ValueError(
            f"Expected the defaults of feature {name} in params, which its decorator keeps, got "
            f"{parameter} in its signature."
        )
    hint = hints[parameter.name]
    if parameter.name not in params:
        return (hint, ...)
    default = params[parameter.name]
    try:
        return (hint, TypeAdapter(hint).validate_python(default, strict=True))
    except ValidationError as error:
        reason = error.errors()[0]["msg"].rstrip(".")
        raise ValueError(
            f"Expected the default of {parameter.name} of feature {name} as {_type_text(hint)}, "
            f"got {default!r}: {reason}."
        ) from error


def _type_text(hint: object) -> str:
    """A type as a message names it: `int`, or `str` for a constrained `Annotated[str, ...]`."""
    base = typing.get_args(hint)[0] if typing.get_origin(hint) is typing.Annotated else hint
    return getattr(base, "__name__", str(base))


def _declared(name: str, declared: FeatureDef | DeclaredInput) -> DeclaredInput:
    """An input of the feature as its version keeps it: another feature by its name and hash."""
    if isinstance(declared, FeatureDef):
        return FeatureInput(name=declared.name, hash=declared.hash)
    if isinstance(declared, _INPUT_KINDS):
        return declared
    kinds = ", ".join(kind.__name__ for kind in _INPUT_KINDS)
    raise ValueError(
        f"Expected each input of feature {name} as a feature or one of {kinds}, got {declared!r}."
    )


def _outputs(name: str, declared: Mapping[str, str]) -> Mapping[str, OutputKind]:
    """The outputs with their kinds, named apart from the bars' columns, `ts_close`, and
    `warmup`, which the frame of `FeatureSpec.evaluate` holds beside them."""
    taken = sorted(set(declared) & _RESERVED_OUTPUTS)
    if taken:
        raise ValueError(
            f"Expected outputs of feature {name} named apart from ts_close, warmup, and the bars' "
            f"columns, got {', '.join(taken)}."
        )
    kinds = [kind.value for kind in OutputKind]
    unknown = {output: kind for output, kind in declared.items() if kind not in kinds}
    if unknown:
        raise ValueError(
            f"Expected the kinds of the outputs of feature {name} among {', '.join(kinds)}, got "
            f"{unknown}."
        )
    return MappingProxyType({output: OutputKind(kind) for output, kind in declared.items()})


def _checked_warmup(
    name: str, warmup: int | Callable[..., object], model: type[BaseModel]
) -> int | Callable[..., object]:
    """`warmup` once it is a whole number of bars, at least 0, or a function of the feature's
    parameters alone."""
    if callable(warmup):
        unknown = sorted(set(inspect.signature(warmup).parameters) - set(model.model_fields))
        if unknown:
            raise ValueError(
                f"Expected the warm-up of feature {name} to read its parameters "
                f"({', '.join(model.model_fields)}), got {', '.join(unknown)}."
            )
        return warmup
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ValueError(
            f"Expected the warm-up of feature {name} as a whole number of bars, at least 0, or a "
            f"lambda of its parameters, got {warmup!r}."
        )
    return warmup


def _warmup_text(name: str, code: str, call: ast.Call, warmup: int | Callable[..., object]) -> str:
    """The warm-up as the decorator writes it, which the version keeps: a number of bars or a
    lambda. One bound to a name defined elsewhere is refused, since the version would miss its
    code."""
    written = next((keyword.value for keyword in call.keywords if keyword.arg == "warmup"), None)
    if written is None and warmup == 0:
        return "0"
    if isinstance(written, ast.Constant | ast.Lambda):
        segment = ast.get_source_segment(code, written)
        if segment is not None:
            return segment
    got = "none in it" if written is None else ast.unparse(written)
    raise ValueError(
        f"Expected the warm-up of feature {name} written in its decorator, as a number of bars or "
        f"a lambda of its parameters, got {got}."
    )
