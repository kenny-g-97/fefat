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
the bars' rows, or a frame of `ts_close` and its outputs on the bars' rows, for a join or a
group-by (step 3.2). A value at a row reads only bars closed by that row's `ts_close` (D-12): no
negative shift, backward fill, or centred window, which the lint of step 3.4 finds.

`outputs` names each output with its kind (`OutputKind`), one output named after the function
and of kind `other` when it is left out. `inputs` declares what the feature reads beside the
bars: other features, by their `FeatureDef`, `InstrumentInput`, `TimeframeInput`, and
`TradesInput`, which the runtime evaluates (`fefat.features.runtime`), and `DatasetInput`,
reserved for Phase 10. `warmup` is the number of bars before the feature's values mean what they
say, or a lambda of its parameters, such as `lambda n: 10 * n`, and `warmup_sessions` the number
of whole sessions before them, as a feature reading the session before declares one (step 3.6,
D-78): its values mean what they say once, from where the features it reads have their first
values, that many whole sessions and then its bars have passed. All of them are written in the
decorator, whose text the hash covers (`fefat.features.declarations`); a helper the function calls
is not versioned with it (`BACKLOG.md`).
"""

import hashlib
import inspect
import json
import textwrap
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import FunctionType, MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model

from fefat.features.declarations import (
    INPUT_KINDS,
    WarmupUnit,
    WrittenDeclarations,
    inputs_as_written,
    written_declarations,
)
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import DeclaredInput, FeatureInput, OutputKind
from fefat.features.registry import register
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import counted

if typing.TYPE_CHECKING:
    from fefat.features.combinations import Combination

BarCount = typing.Annotated[int, Field(ge=1)]
"""A number of bars, at least one, as a moving average's or a range's."""
TwoOrMoreBars = typing.Annotated[int, Field(ge=2)]
"""A number of bars, at least two, as a standard deviation's or a directional index's, which a
single bar leaves without a value."""
SessionCount = typing.Annotated[int, Field(ge=1)]
"""A number of whole sessions, at least one, as an average over the sessions before reads."""

_RESERVED_OUTPUTS = frozenset({"ts_close", "warmup", *SIGNAL_BAR_COLUMNS})
_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
_PARAMETERS_CONFIG = ConfigDict(frozen=True, extra="forbid", strict=True)


@dataclass(frozen=True, eq=False)
class FeatureDef:
    """A feature's definition (the module docstring): its function, its normalised source, the
    model of its parameters, the inputs it declares beside the bars, its outputs with their kinds,
    its warm-ups in bars and in sessions, each also as its decorator writes it, its content hash,
    by which two definitions are equal, and a combination's description, which the hash leaves
    out (`fefat.features.combine`). Call it with parameters for a `FeatureSpec`."""

    name: str
    function: Callable[..., object]
    code: str
    parameter_model: type[BaseModel]
    inputs: tuple[DeclaredInput, ...]
    outputs: Mapping[str, OutputKind]
    warmup: int | Callable[..., object]
    written_warmup: int | str
    warmup_sessions: int | Callable[..., object]
    written_warmup_sessions: int | str
    hash: str
    combination: "Combination | None" = None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FeatureDef) and other.hash == self.hash

    def __hash__(self) -> int:
        return hash(self.hash)

    @property
    def parameter_schema(self) -> dict[str, typing.Any]:
        """The JSON schema of the feature's parameters: their types and defaults."""
        return self.parameter_model.model_json_schema()

    def __call__(self, *values: object, **parameters: object) -> FeatureSpec:
        """The feature with its parameters, given in their order as `values`, such as
        `atr(14)`, or by name, the defaults filling those left out, validated strictly:
        `rsi(n="14")` is refused, never read as 14."""
        try:
            bound = self.parameter_model(**self._named(values, parameters))
        except ValidationError as error:
            raise ValueError(self._refusal(error)) from error
        return FeatureSpec(
            definition=self,
            parameters=bound,
            warmup=self._bound_warmup(WarmupUnit.BARS, bound),
            warmup_sessions=self._bound_warmup(WarmupUnit.SESSIONS, bound),
        )

    def _named(
        self, values: tuple[object, ...], parameters: dict[str, object]
    ) -> dict[str, object]:
        """The parameters given in their order, `values`, by name, beside those given by name."""
        names = list(self.parameter_model.model_fields)
        if len(values) > len(names):
            raise ValueError(
                f"Expected at most {counted(len(names), 'parameter')} of feature {self.name} in "
                f"its order ({', '.join(names)}), got {len(values)}: "
                f"{', '.join(map(repr, values))}."
            )
        in_order = dict(zip(names, values, strict=False))
        twice = sorted(set(in_order) & set(parameters))
        if twice:
            raise ValueError(
                f"Expected each parameter of feature {self.name} once, got {', '.join(twice)} in "
                "its order and by name."
            )
        return {**in_order, **parameters}

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
        return (
            f"Expected the parameters of feature {self.name} as {{{expected}}}, got {got}: "
            f"{reason}."
        )

    def _bound_warmup(self, unit: WarmupUnit, parameters: BaseModel) -> int:
        """The warm-up of the feature in `unit` with `parameters`."""
        declared, written = (
            (self.warmup, self.written_warmup)
            if unit is WarmupUnit.BARS
            else (self.warmup_sessions, self.written_warmup_sessions)
        )
        if not callable(declared):
            return declared
        read = inspect.signature(declared).parameters
        try:
            count = declared(**{name: getattr(parameters, name) for name in read})
        except Exception as error:
            raise ValueError(
                f"Expected the {unit.label} of feature {self.name}, {written}, to give a number "
                f"of {unit} with {parameters!r}, got {error!r}."
            ) from error
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(
                f"Expected the {unit.label} of feature {self.name} as a whole number of {unit}, at "
                f"least 0, got {count!r} from {written} with {parameters!r}."
            )
        return count


def feature(
    *,
    params: Mapping[str, object] | None = None,
    warmup: int | Callable[..., object] = 0,
    warmup_sessions: int | Callable[..., object] = 0,
    inputs: Sequence[FeatureDef | DeclaredInput] = (),
    outputs: Mapping[str, str] | None = None,
) -> Callable[[Callable[..., object]], FeatureDef]:
    """Define a feature (the module docstring): `params` gives its parameters' defaults, `warmup`
    its warm-up in bars and `warmup_sessions` in whole sessions, each a number or a lambda of its
    parameters, `inputs` what it reads beside the bars, and `outputs` its outputs with their
    kinds, all but `params` written in the decorator."""

    def define(function: Callable[..., object]) -> FeatureDef:
        name = function.__name__
        code = _source(function)
        model = _parameter_model(name, function, {} if params is None else params)
        checked_warmup = _checked_warmup(name, WarmupUnit.BARS, warmup, model)
        checked_sessions = _checked_warmup(name, WarmupUnit.SESSIONS, warmup_sessions, model)
        declared = tuple(_declared(name, each) for each in inputs)
        written = written_declarations(name, code)
        _require_inputs_as_written(name, declared, written)
        definition = FeatureDef(
            name=name,
            function=function,
            code=code,
            parameter_model=model,
            inputs=declared,
            outputs=_outputs(name, {name: OutputKind.OTHER} if outputs is None else outputs),
            warmup=checked_warmup,
            written_warmup=written.warmup,
            warmup_sessions=checked_sessions,
            written_warmup_sessions=written.warmup_sessions,
            hash=content_hash(code, declared, model.model_json_schema()),
        )
        register(definition)
        return definition

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
    try:
        hints = typing.get_type_hints(function, include_extras=True)
    except NameError as error:
        raise ValueError(
            f"Expected the annotations of feature {name} to name types Python can find, got: "
            f"{error}."
        ) from error
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


def _require_inputs_as_written(
    name: str, declared: Sequence[DeclaredInput], written: WrittenDeclarations
) -> None:
    """Refuse inputs other than those the decorator writes: an input other than a feature bound
    to a name defined elsewhere would change no hash."""
    if inputs_as_written(declared, written.inputs):
        return
    writes = ", ".join("a name" if each is None else repr(each) for each in written.inputs)
    raise ValueError(
        f"Expected each input of feature {name} other than a feature written in its decorator "
        f'with literal values, such as InstrumentInput(root="MNQ"), got {declared!r} where it '
        f"writes {writes}."
    )


def _declared(name: str, declared: FeatureDef | DeclaredInput) -> DeclaredInput:
    """An input of the feature as its version keeps it: another feature by its name and hash."""
    if isinstance(declared, FeatureDef):
        return FeatureInput(name=declared.name, hash=declared.hash)
    if isinstance(declared, INPUT_KINDS):
        return declared
    kinds = ", ".join(kind.__name__ for kind in INPUT_KINDS)
    raise ValueError(
        f"Expected each input of feature {name} as a feature or one of {kinds}, got {declared!r}."
    )


def _outputs(name: str, declared: Mapping[str, str]) -> Mapping[str, OutputKind]:
    """The outputs with their kinds, at least one, named apart from the bars' columns,
    `ts_close`, and `warmup`, which the frame of `FeatureSpec.evaluate` holds beside them."""
    taken = sorted(set(declared) & _RESERVED_OUTPUTS)
    if taken or not declared:
        raise ValueError(
            f"Expected outputs of feature {name}, at least one, named apart from ts_close, warmup, "
            f"and the bars' columns, got {', '.join(taken) if taken else 'none'}."
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
    name: str, unit: WarmupUnit, warmup: int | Callable[..., object], model: type[BaseModel]
) -> int | Callable[..., object]:
    """`warmup` once it is a whole number of `unit`, at least 0, or a function of the feature's
    parameters alone."""
    if callable(warmup):
        unknown = sorted(set(inspect.signature(warmup).parameters) - set(model.model_fields))
        if unknown:
            raise ValueError(
                f"Expected the {unit.label} of feature {name} to read its parameters "
                f"({', '.join(model.model_fields)}), got {', '.join(unknown)}."
            )
        outside = _names_read_outside(warmup)
        if outside:
            raise ValueError(
                f"Expected the {unit.label} of feature {name} to read its parameters alone, got "
                f"{', '.join(outside)}, whose values its version would miss."
            )
        return warmup
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ValueError(
            f"Expected the {unit.label} of feature {name} as a whole number of {unit}, at least "
            f"0, or a lambda of its parameters, got {warmup!r}."
        )
    return warmup


def _names_read_outside(warmup: Callable[..., object]) -> list[str]:
    """The names a warm-up function reads from outside its parameters, a global or a closure's
    value, which the decorator's text does not hold; a builtin such as `max` is part of Python."""
    if not isinstance(warmup, FunctionType):
        return []
    read = inspect.getclosurevars(warmup)
    return sorted({*read.nonlocals, *read.globals})
