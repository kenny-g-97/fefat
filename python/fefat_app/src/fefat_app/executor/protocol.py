"""What the executor and its runner exchange (step 4.5): the files of an execution's folder, the
spec the executor writes, the result the runner leaves, and a preview's series in Parquet, each
read back with a cap on its size and validated before the app trusts it, since the trader's code
ran beside them; and the lines the runner prints, a report of progress each, then an empty one
once the execution's result is in its folder."""

import io
import traceback
from pathlib import Path
from typing import Annotated, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from fefat_app.execution import (
    BacktestOutput,
    ExecutionFailed,
    ExecutionKind,
    ExecutionOutcome,
    FeatureSaveOutput,
    PythonSnippetOutput,
    RefusedCode,
    RunLookupOutput,
    SeriesPoint,
    SeriesStatistics,
    StrategySaveOutput,
    StrategyValidationOutput,
)

SPEC_FILE = "spec.json"
RESULT_FILE = "result.json"
SERIES_FILE = "series.parquet"
RESULT_BYTES = 1024 * 1024
"""The largest result the executor reads; an error, a tail of prints, and a preview's statistics
take a few kilobytes."""
SERIES_BYTES = 4 * 1024 * 1024
"""The largest series the executor reads; a thousand points an output take a few dozen
kilobytes."""
SERIES_POINTS = 1000
"""The most points of an output's downsampled series."""
SERIES_SCHEMA = pl.Schema({"output": pl.String, "ts_close": pl.Int64, "value": pl.Float64})
"""The columns of `series.parquet`: an output's finite values by the close of their bars."""
END_OF_EXECUTION = "\n"
"""The line the runner prints once an execution's result is in its folder."""
ERROR_CHARS = 4000
"""How much of a failure's traceback its result keeps, from its end, and of a refusal of the
trader's code, from its start."""


class RunnerOutputError(ValueError):
    """What a runner printed or left that the executor refuses: a line of progress, a result, or
    a series that is not one, or one too large."""


class PreviewSummary(BaseModel):
    """What a preview's runner leaves in `result.json`: each output's statistics, and what the
    bars' loading warned of; its series is in `series.parquet`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.FEATURE_PREVIEW] = ExecutionKind.FEATURE_PREVIEW
    statistics: dict[str, SeriesStatistics]
    warnings: tuple[str, ...]


class RunnerSucceeded(BaseModel):
    """`result.json` of an execution that ran to its end, with what its kind gave."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal[ExecutionOutcome.SUCCEEDED] = ExecutionOutcome.SUCCEEDED
    output: Annotated[
        PreviewSummary
        | PythonSnippetOutput
        | StrategyValidationOutput
        | StrategySaveOutput
        | FeatureSaveOutput
        | RunLookupOutput
        | BacktestOutput,
        Field(discriminator="kind"),
    ]


type RunnerResult = Annotated[RunnerSucceeded | ExecutionFailed, Field(discriminator="outcome")]
RUNNER_RESULT: TypeAdapter[RunnerResult] = TypeAdapter(RunnerResult)
"""Reads and writes `result.json`, told apart by its `outcome`."""


def failed_with(failure: BaseException, stdout_tail: str) -> ExecutionFailed:
    """The failure of an execution that raised `failure`: the end of its traceback, with the tail
    of what a snippet printed before."""
    trace = "".join(traceback.format_exception(failure))
    return ExecutionFailed(error=trace[-ERROR_CHARS:], stdout_tail=stdout_tail)


def refused_code(message: str, line: int | None) -> RefusedCode:
    """The SDK's refusal of the trader's code in `message`, at the code's `line` where it has
    one, which the runner answers rather than failing (steps 5.2 and 5.3)."""
    return RefusedCode(line=line, message=message[:ERROR_CHARS])


def write_result_file(folder: Path, result: RunnerResult) -> None:
    """Leave `result` in `folder`, which the executor reads once the runner says so."""
    (folder / RESULT_FILE).write_bytes(RUNNER_RESULT.dump_json(result))


def read_result_file(folder: Path) -> RunnerResult:
    """The result the runner left in `folder`; refused where it left none, one too large, or one
    that is not a result."""
    content = _capped(folder / RESULT_FILE, RESULT_BYTES)
    try:
        return RUNNER_RESULT.validate_json(content)
    except ValidationError as error:
        raise RunnerOutputError(
            f"Expected {RESULT_FILE} to hold the result of an execution, got: {problems(error)}."
        ) from error


def read_series(folder: Path) -> tuple[SeriesPoint, ...]:
    """The downsampled series the runner left in `folder`, by output and in time order; refused
    where it left none, one too large, one of other columns, more points an output than
    `SERIES_POINTS`, or a value that is not finite."""
    content = _capped(folder / SERIES_FILE, SERIES_BYTES)
    try:
        series = pl.read_parquet(io.BytesIO(content))
    except pl.exceptions.PolarsError as error:
        raise RunnerOutputError(f"Expected {SERIES_FILE} to be Parquet, got: {error}") from error
    if series.schema != SERIES_SCHEMA:
        raise RunnerOutputError(
            f"Expected {SERIES_FILE} of the columns {_described(SERIES_SCHEMA)}, got "
            f"{_described(series.schema)}."
        )
    most = series.group_by("output").len().get_column("len").max()
    if isinstance(most, int) and most > SERIES_POINTS:
        raise RunnerOutputError(f"Expected at most {SERIES_POINTS} points an output, got {most}.")
    rows = series.sort("output", "ts_close").iter_rows(named=True)
    try:
        return tuple(SeriesPoint.model_validate(row) for row in rows)
    except ValidationError as error:
        raise RunnerOutputError(
            f"Expected {SERIES_FILE} to hold points, got: {problems(error)}."
        ) from error


def problems(error: ValidationError) -> str:
    """What `error` found wrong, by place, without the values it read, which may be prices
    (D-21)."""
    found = error.errors(include_input=False, include_url=False)
    return "; ".join(
        _problem(".".join(str(part) for part in each["loc"]), each["msg"]) for each in found
    )


def _problem(place: str, message: str) -> str:
    if not place:
        return message
    return f"{place}: {message}"


def _capped(path: Path, most_bytes: int) -> bytes:
    """The bytes of `path`, refused where the runner left none, or more than `most_bytes`, which
    are never read."""
    if not path.is_file():
        raise RunnerOutputError(
            f"Expected the runner to leave {path.name} in its folder, got none."
        )
    with path.open("rb") as file:
        content = file.read(most_bytes + 1)
    if len(content) > most_bytes:
        raise RunnerOutputError(f"Expected {path.name} of at most {most_bytes} bytes, got more.")
    return content


def _described(schema: pl.Schema) -> str:
    return ", ".join(f"{name} ({dtype})" for name, dtype in schema.items())
