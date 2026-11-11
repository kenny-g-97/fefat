"""What an execution of the trader's code is (step 4.5, `01-architecture.md` sections 6 and 10):
the spec of each kind the executor runs, the code with the bars it reads and the limits it runs
within; the progress its runner reports; and its result, validated before the app trusts it.
Frozen Pydantic models, as at every boundary (`08-code-design.md` section 3.3), kept apart from
the port in `fefat_app.ports` so that the runner reads them without the app's other seams.

From step 5.2 (D-93), the library's kinds: a strategy's code validated, a strategy version saved,
and a feature version saved, each through the SDK in the runner, never in the server; what the
SDK refuses comes back as the runner's answer, with the line of the code it is at, rather than as
a failure."""

from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fefat.strategy.source_lint import StrategyLintFinding


class ExecutionKind(StrEnum):
    """What an execution runs: a feature's preview, or a snippet of Python, which the job kinds
    of the same names run (step 4.5); a strategy's code validated, a strategy version saved, or a
    feature version saved, which the library's routes run (step 5.2)."""

    FEATURE_PREVIEW = "feature_preview"
    PYTHON_SNIPPET = "python_snippet"
    STRATEGY_VALIDATION = "strategy_validation"
    STRATEGY_SAVE = "strategy_save"
    FEATURE_SAVE = "feature_save"


MOST_SECONDS = 24 * 60 * 60
"""The longest timeout an execution takes: a day, longer than any run FEFAT starts."""
MOST_BYTES = 2**63 - 1
"""The largest memory limit an execution takes, the most a limit of 64 bits holds."""


class ExecutionLimits(BaseModel):
    """What an execution may take: the seconds of the wall clock from its start, and the bytes of
    memory its processes may commit together, past which an allocation fails."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(gt=0, le=MOST_SECONDS)
    memory_bytes: int = Field(gt=0, le=MOST_BYTES)


class BarsReference(BaseModel):
    """The bars an execution reads, as `ff.market.load` names them: a root, or a contract for a
    snippet, a timeframe, the trade dates from `start` to `end`, and the provider where several
    hold the root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str
    timeframe: str
    start: date
    end: date
    provider: str | None = None


class FeaturePreviewSpec(BaseModel):
    """A feature's preview: the feature that `code` defines (`ff.features.from_source`), with
    `parameters`, computed over `bars` (`ff.features.compute`), whose cache serves a repeated
    preview; its statistics and a downsampled series come back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.FEATURE_PREVIEW] = ExecutionKind.FEATURE_PREVIEW
    code: str
    parameters: dict[str, Any]
    bars: BarsReference
    limits: ExecutionLimits


class PythonSnippetSpec(BaseModel):
    """A snippet of Python, run with `ff` and `pl` bound, and `bars`, the frame `ff.market.load`
    gives, where it names a dataset of the store; the tail of what it prints comes back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.PYTHON_SNIPPET] = ExecutionKind.PYTHON_SNIPPET
    code: str
    bars: BarsReference | None
    limits: ExecutionLimits


class StrategyValidationSpec(BaseModel):
    """A strategy's code, built as a version's is (`ff.strategy.from_source`), with its signal
    frame on bars with no rows; nothing is saved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.STRATEGY_VALIDATION] = ExecutionKind.STRATEGY_VALIDATION
    code: str
    limits: ExecutionLimits


class StrategySaveSpec(BaseModel):
    """A strategy version saved as a notebook saves it (`ff.strategy.save`): the strategy's name,
    its code, its hypothesis, and its changelog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.STRATEGY_SAVE] = ExecutionKind.STRATEGY_SAVE
    name: str
    code: str
    hypothesis: str
    changelog: str
    limits: ExecutionLimits


class FeatureSaveSpec(BaseModel):
    """A feature version saved as a notebook saves it: the feature `code` defines
    (`ff.features.from_source`), refused unless it is the feature `name`, saved with
    `ff.features.save`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.FEATURE_SAVE] = ExecutionKind.FEATURE_SAVE
    name: str
    code: str
    limits: ExecutionLimits


type LibrarySpec = StrategyValidationSpec | StrategySaveSpec | FeatureSaveSpec
"""An execution of the library's kinds (step 5.2)."""
type ExecutionSpec = Annotated[
    FeaturePreviewSpec
    | PythonSnippetSpec
    | StrategyValidationSpec
    | StrategySaveSpec
    | FeatureSaveSpec,
    Field(discriminator="kind"),
]
EXECUTION_SPEC: TypeAdapter[ExecutionSpec] = TypeAdapter(ExecutionSpec)
"""Reads and writes a spec of any kind, told apart by its `kind`."""


class ExecutionProgress(BaseModel):
    """How far an execution has come, which its runner reports as a line of JSON: a percent, a
    message, and any figures of its kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    percent: float = Field(ge=0, le=100)
    message: str
    details: dict[str, Any]


type ProgressReport = Callable[[ExecutionProgress], None]
"""Where an execution's progress goes as it comes, a job's events or a notebook's output; what it
raises stops the execution, as a job asked to stop does."""
type StopCheck = Callable[[], None]
"""Asked whenever a second passes without a report while an execution runs; what it raises stops
the execution, as a job asked to stop does, so that a long computation that reports nothing still
stops within a second."""


def keep_running() -> None:
    """The check of an execution nothing asks to stop, as a notebook's."""


class ExecutionOutcome(StrEnum):
    """How an execution ended: it ran to its end, it failed, or it ran out of time and was
    stopped. A memory limit reached is a failure, whose error names it."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
"""A number that is neither NaN nor infinite, which JSON can carry."""


class SeriesStatistics(BaseModel):
    """A preview's figures of one output of its feature: how many of its values are finite, the
    share of bars whose value is null, NaN, or infinite, and the least, greatest, mean, standard
    deviation, and last of the finite ones, None where there are too few."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=0)
    missing_share: float = Field(ge=0, le=1)
    min: FiniteNumber | None
    max: FiniteNumber | None
    mean: FiniteNumber | None
    std: FiniteNumber | None
    last: FiniteNumber | None


class SeriesPoint(BaseModel):
    """A point of a preview's downsampled series: an output's finite value at a bar's close, in
    nanoseconds since the Unix epoch, UTC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: str
    ts_close: int
    value: FiniteNumber


class FeaturePreviewOutput(BaseModel):
    """What a feature's preview gives: each output's statistics; its series, downsampled to at
    most a thousand points an output that keep its highs and lows, by output and in time order;
    and what the bars' loading warned of."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.FEATURE_PREVIEW] = ExecutionKind.FEATURE_PREVIEW
    statistics: dict[str, SeriesStatistics]
    series: tuple[SeriesPoint, ...]
    warnings: tuple[str, ...]


class PythonSnippetOutput(BaseModel):
    """What a snippet gives: the last characters it printed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.PYTHON_SNIPPET] = ExecutionKind.PYTHON_SNIPPET
    stdout_tail: str


class CodeVerdict(StrEnum):
    """What the runner made of the trader's code for the library: a strategy that builds, a
    version saved, or found saved with the same content, or code the SDK refused."""

    VALID = "valid"
    SAVED = "saved"
    REFUSED = "refused"


class RefusedCode(BaseModel):
    """Code the SDK refused: the line of the code the refusal is at, None where it has none, and
    why, in the SDK's words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[CodeVerdict.REFUSED] = CodeVerdict.REFUSED
    line: int | None
    message: str


class ValidStrategy(BaseModel):
    """A strategy's code that builds: the instrument and the timeframe its strategy names with
    its defaults, the JSON schema of its parameters, and the lint's findings in its code, which
    warn (`ff.strategy.lint`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[CodeVerdict.VALID] = CodeVerdict.VALID
    instrument: str
    timeframe: str
    parameter_schema: dict[str, Any]
    lint: tuple[StrategyLintFinding, ...]


class SavedVersion(BaseModel):
    """A version saved, or found saved with the same content: its name and its number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[CodeVerdict.SAVED] = CodeVerdict.SAVED
    name: str
    version: int = Field(ge=1)


class StrategyValidationOutput(BaseModel):
    """What a strategy's validation gives: its code valid, or refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.STRATEGY_VALIDATION] = ExecutionKind.STRATEGY_VALIDATION
    answer: Annotated[ValidStrategy | RefusedCode, Field(discriminator="verdict")]


class StrategySaveOutput(BaseModel):
    """What a strategy version's save gives: the version saved, or its code refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.STRATEGY_SAVE] = ExecutionKind.STRATEGY_SAVE
    answer: Annotated[SavedVersion | RefusedCode, Field(discriminator="verdict")]


class FeatureSaveOutput(BaseModel):
    """What a feature version's save gives: the version saved, or its code refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ExecutionKind.FEATURE_SAVE] = ExecutionKind.FEATURE_SAVE
    answer: Annotated[SavedVersion | RefusedCode, Field(discriminator="verdict")]


type LibraryOutput = StrategyValidationOutput | StrategySaveOutput | FeatureSaveOutput
"""What an execution of the library's kinds gives (step 5.2)."""


class ExecutionSucceeded(BaseModel):
    """An execution that ran to its end, with what its kind gives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal[ExecutionOutcome.SUCCEEDED] = ExecutionOutcome.SUCCEEDED
    output: Annotated[
        FeaturePreviewOutput
        | PythonSnippetOutput
        | StrategyValidationOutput
        | StrategySaveOutput
        | FeatureSaveOutput,
        Field(discriminator="kind"),
    ]


class ExecutionFailed(BaseModel):
    """An execution that failed: the end of its traceback, or why its result was refused, with
    the last characters a snippet printed before."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal[ExecutionOutcome.FAILED] = ExecutionOutcome.FAILED
    error: str
    stdout_tail: str


class ExecutionTimedOut(BaseModel):
    """An execution still running at its timeout, whose processes were stopped then."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal[ExecutionOutcome.TIMED_OUT] = ExecutionOutcome.TIMED_OUT


type ExecutionResult = Annotated[
    ExecutionSucceeded | ExecutionFailed | ExecutionTimedOut, Field(discriminator="outcome")
]
"""How an execution ended, with what it gave."""
