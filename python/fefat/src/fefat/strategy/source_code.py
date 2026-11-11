"""A strategy from its code (step 5.2, D-93): `from_source` runs the text of a strategy version's
code, a module whose function `strategy` gives a `SignalStrategy`, in a module of its own; builds
the strict model of the function's parameters, each annotated with its type and given its default
in the signature, as a feature's are (`fefat.features.definition`); builds the strategy with those
defaults; and builds its signal frame on bars that hold no rows, so that a column no bar holds, or
a signal that is no boolean, is refused before a version exists. A refusal is a
`StrategyCodeError` with the line of the code it is at: a syntax error's, the innermost of the
code's lines that ran into the error, or else the line that defines `strategy`.

    definition = ff.strategy.from_source(code)
    definition.parameter_schema  # the JSON schema of the strategy's parameters
    definition(lookback=20)  # the strategy with a parameter of its own

The code runs as written, with nothing bound but what it imports: the app runs it in the
executor's runner (`fefat_app.executor`), never in the server, and a notebook in its own process.
Its text is kept in `linecache` under a name of its own, as a notebook keeps a cell's, so that a
feature it defines finds its source, and its module in `sys.modules`, so that a dataclass or a
model it defines finds its module; never as `__main__`, so that a block under
`if __name__ == "__main__":` does not run."""

import ast
import hashlib
import inspect
import json
import linecache
import sys
import traceback
import typing
from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType, ModuleType
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model

from fefat.features.grids import Grid, PrintsGrid
from fefat.market.aggressor import SIDE_VOLUME_COLUMNS
from fefat.market.series_source import SIGNAL_BAR_COLUMNS
from fefat.strategy.signal_frame import require_named_columns
from fefat.strategy.signal_strategy import SignalStrategy

FUNCTION_NAME = "strategy"
"""The function of a strategy's code that gives its `SignalStrategy`."""
_PARAMETERS_CONFIG = ConfigDict(frozen=True, extra="forbid", strict=True)
_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


class StrategyCodeError(ValueError):
    """Code that gives no strategy, with the line of the code it is at, None where it has none."""

    def __init__(self, message: str, line: int | None) -> None:
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class StrategyDefinition:
    """A strategy's normalised code (`normalised`), its function, the model of its parameters, and
    the strategy the function gives with their defaults; call it with parameters for the strategy
    they give."""

    code: str
    function: Callable[..., object]
    parameter_model: type[BaseModel]
    with_defaults: SignalStrategy

    @property
    def parameter_schema(self) -> dict[str, Any]:
        """The JSON schema of the strategy's parameters: their types and defaults."""
        return self.parameter_model.model_json_schema()

    def __call__(self, **parameters: object) -> SignalStrategy:
        """The strategy with `parameters`, its defaults filling those left out, validated strictly:
        `lookback="20"` is refused, never read as 20."""
        try:
            bound = self.parameter_model(**parameters)
        except ValidationError as error:
            raise ValueError(
                f"Expected the strategy's parameters as its schema gives them, got: {error}"
            ) from error
        return _given_strategy(self.function(**dict(bound)), line=None)


def from_source(code: str) -> StrategyDefinition:
    """The strategy `code` defines, built with its defaults and checked on bars with no rows;
    refused with `StrategyCodeError` (module docstring)."""
    text = normalised(code)
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    filename = f"<strategy {digest}>"
    try:
        return _defined(text, digest, filename)
    except StrategyCodeError:
        raise
    except (Exception, SystemExit) as error:
        line = _line_in(error, filename)
        if line is None:
            line = _strategy_line(text)
        raise StrategyCodeError(_described(error), line) from error


def normalised(code: str) -> str:
    """`code` with LF line ends, no trailing spaces, and one final newline, each line where it
    was, so that the line a refusal names is the line as written."""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"


def _defined(text: str, digest: str, filename: str) -> StrategyDefinition:
    module = _run_as_module(text, f"fefat_strategy_{digest}", filename)
    line = _strategy_line(text)
    function = _strategy_function(module, line)
    model = _parameter_model(function, line)
    strategy = _given_strategy(function(), line)
    _build_on_no_bars(strategy)
    return StrategyDefinition(
        code=text, function=function, parameter_model=model, with_defaults=strategy
    )


def _run_as_module(text: str, name: str, filename: str) -> ModuleType:
    """Run `text` as the module `name`, kept in `sys.modules`, its text in `linecache` under
    `filename` (module docstring)."""
    module = ModuleType(name)
    lines = [f"{line}\n" for line in text[:-1].split("\n")]
    linecache.cache[filename] = (len(text), None, lines, filename)
    sys.modules[name] = module
    exec(compile(text, filename, "exec"), vars(module))
    return module


def _strategy_function(module: ModuleType, line: int | None) -> FunctionType:
    """The module's function `strategy`, refused where it defines none, or binds the name to
    another value, such as the `SignalStrategy` itself, as a notebook's cell does."""
    if FUNCTION_NAME not in vars(module):
        raise StrategyCodeError(
            "Expected the code to define a function strategy that gives the SignalStrategy, got "
            "no strategy.",
            line,
        )
    value = vars(module)[FUNCTION_NAME]
    if isinstance(value, FunctionType):
        return value
    if isinstance(value, SignalStrategy):
        raise StrategyCodeError(
            "Expected strategy as a function that gives the SignalStrategy, got the "
            "SignalStrategy itself: write `def strategy() -> ff.SignalStrategy:` above it and "
            "return it, with its parameters as the function's, each with its type and default.",
            line,
        )
    raise StrategyCodeError(
        f"Expected strategy as a function that gives a SignalStrategy, got {type(value).__name__}.",
        line,
    )


def _parameter_model(function: FunctionType, line: int | None) -> type[BaseModel]:
    """The strict, frozen model of the function's parameters, each with its annotation and its
    default, which a form can send back as JSON."""
    try:
        hints = typing.get_type_hints(function, include_extras=True)
    except NameError as error:
        raise StrategyCodeError(
            f"Expected the annotations of strategy to name types Python can find, got: {error}.",
            line,
        ) from error
    parameters = inspect.signature(function).parameters.values()
    fields: dict[str, Any] = {each.name: _field(each, hints, line) for each in parameters}
    model = create_model("strategy_parameters", __config__=_PARAMETERS_CONFIG, **fields)
    dropped = sorted(set(fields) - set(model.model_fields))
    if dropped:
        raise StrategyCodeError(
            "Expected parameter names Pydantic takes as fields, got "
            f"{', '.join(dropped)}, which it keeps for itself, as it keeps a name with a leading "
            "underscore or starting with model_: rename them.",
            line,
        )
    _require_json_defaults(model, line)
    return model


def _field(
    parameter: inspect.Parameter, hints: dict[str, Any], line: int | None
) -> tuple[Any, object]:
    """A parameter's field: its type, and its default checked strictly against it."""
    if parameter.kind not in _NAMED:
        raise StrategyCodeError(
            f"Expected the parameters of strategy by name, got {parameter}.", line
        )
    if parameter.name not in hints:
        raise StrategyCodeError(
            "Expected each parameter of strategy annotated with its type, got "
            f"{parameter.name} without one.",
            line,
        )
    if parameter.default is inspect.Parameter.empty:
        raise StrategyCodeError(
            "Expected each parameter of strategy with a default, which the strategy is built "
            f"with, got {parameter.name} without one.",
            line,
        )
    hint = hints[parameter.name]
    try:
        return (hint, TypeAdapter(hint).validate_python(parameter.default, strict=True))
    except ValidationError as error:
        reason = error.errors()[0]["msg"].rstrip(".")
        raise StrategyCodeError(
            f"Expected the default of {parameter.name} of its annotated type, got "
            f"{parameter.default!r}: {reason}.",
            line,
        ) from error


def _require_json_defaults(model: type[BaseModel], line: int | None) -> None:
    """Refuse parameters a form cannot send back as JSON, such as a `StrEnum`'s, which a strict
    model takes as its members alone, or a default JSON cannot write."""
    try:
        json.dumps(model.model_json_schema(), allow_nan=False)
        model(**json.loads(model().model_dump_json()))
    except ValueError as error:
        raise StrategyCodeError(
            "Expected parameters a form can send as JSON, of int, float, bool, str, or a Literal "
            f"of them, got: {error}",
            line,
        ) from error


def _given_strategy(value: object, line: int | None) -> SignalStrategy:
    if isinstance(value, SignalStrategy):
        return value
    raise StrategyCodeError(
        f"Expected strategy() to give a SignalStrategy, got {type(value).__name__}.", line
    )


def _build_on_no_bars(strategy: SignalStrategy) -> None:
    """Build the strategy's signal frame on bars, and on what its features read beside them, that
    hold no rows, as a run builds it on the bars it loads, and check the columns its template
    reads: a column no bar holds, or a signal that is no boolean, is refused, and no data is
    read."""
    # shortcut: a batch function (map_batches) that cannot take an empty column is refused here
    # though it runs on bars; build on a few generated bars when a trader meets it.
    graph = strategy.feature_graph()
    others = {grid: _no_rows(grid) for grid in graph.grids() if grid != graph.signal_grid}
    frame = strategy.signals(pl.DataFrame(schema=SIGNAL_BAR_COLUMNS), others).collect()
    require_named_columns(strategy.execution, frame.columns)


def _no_rows(grid: Grid) -> pl.DataFrame:
    """The frame of `grid` with no rows: its prints by side, or its bars."""
    schema = SIDE_VOLUME_COLUMNS if isinstance(grid, PrintsGrid) else SIGNAL_BAR_COLUMNS
    return pl.DataFrame(schema=schema)


def _line_in(error: BaseException, filename: str) -> int | None:
    """The line of the code `error` is at: a syntax error's in the code itself, or the innermost
    of the code's lines in its traceback; None where neither is."""
    if isinstance(error, SyntaxError) and error.filename == filename:
        return error.lineno
    frames = traceback.extract_tb(error.__traceback__)
    lines = [frame.lineno for frame in frames if frame.filename == filename]
    return lines[-1] if lines else None


def _strategy_line(text: str) -> int | None:
    """The line of the code's last statement that binds `strategy`, a function's or an
    assignment's; None where none does or the code does not parse."""
    try:
        statements = ast.parse(text).body
    except SyntaxError:
        return None
    lines = [statement.lineno for statement in statements if _binds_strategy(statement)]
    return lines[-1] if lines else None


def _binds_strategy(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
        return statement.name == FUNCTION_NAME
    if isinstance(statement, ast.Assign):
        return any(_names_strategy(target) for target in statement.targets)
    if isinstance(statement, ast.AnnAssign):
        return _names_strategy(statement.target)
    return False


def _names_strategy(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == FUNCTION_NAME


def _described(error: BaseException) -> str:
    """What `error` says, after its kind, as Python's own traceback ends."""
    said = error.msg if isinstance(error, SyntaxError) else str(error)
    return f"{type(error).__name__}: {said}"
