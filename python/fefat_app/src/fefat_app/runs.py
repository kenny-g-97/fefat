"""The runs as the app serves them (step 5.3, D-84, ADR-0020): a backtest of a saved strategy
version asked for through the API, a submission with its `backtest` job until its folder is saved,
then the index of that folder, `runs/<run key>/`, which stays the record; what the executor's
lookup answers before a job is queued; and what a submission gives. A run's status is derived, not
kept: `succeeded` once its folder is indexed, whatever its job says, its job's before, so that the
reaper's requeues and timeouts never leave two statuses apart. The two states are two types since
step 5.6, told apart by `state`. Frozen models, as at every boundary, kept apart from the port in
`fefat_app.ports`, as `fefat_app.execution` and `fefat_app.library` keep theirs; they import
neither the ports nor the executor's specs, which read them."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
)

from fefat.backtest.estimates import WindowEstimate
from fefat.backtest.metrics import Metrics, Verdict
from fefat.backtest.record import Hash
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.market.fees import Fee
from fefat.market.fidelity import FidelityEra
from fefat.market.instruments import Currency
from fefat.market.schema import frozen
from fefat.market.snapshot import Sha256
from fefat_app.job_models import JobStatus

Parameters = Annotated[Mapping[str, JsonValue], AfterValidator(frozen)]
"""A run's parameters by name, held read-only, as the SDK's `StrategyPin` holds them."""


class RunOrigin(StrEnum):
    """Where a run's row comes from: asked for through the API, or found saved by the index; the
    batches of later phases add theirs."""

    MANUAL = "manual"


class RunState(StrEnum):
    """What a run's row is: a submission whose job has yet to save its run, or a saved run."""

    SUBMITTED = "submitted"
    SAVED = "saved"


class RequestedRun(BaseModel):
    """A backtest of a saved strategy version as the API asks for it and the executor runs it:
    the strategy's name, the version's number and content hash as the index holds them, the
    parameters given, its defaults filling those left out, the trade dates from `start` to
    `end`, and the run's settings, the SDK's own (`ff.backtest.RunConfig`), each default left
    out applied by the SDK."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    version: int = Field(ge=1)
    hash: Sha256
    parameters: Parameters
    start: date
    end: date
    settings: RunConfig


class LookupVerdict(StrEnum):
    """What the executor's lookup found of a run: saved already, or to make."""

    SAVED = "saved"
    TO_MAKE = "to_make"


class SavedRunFound(BaseModel):
    """A run whose request found it saved (`fefat.backtest.requests`): its run key and the key
    of that request, which a submission of it waiting may hold, with the parameters as the
    version bound them and the settings as the SDK applied them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[LookupVerdict.SAVED] = LookupVerdict.SAVED
    run_key: Hash
    request_key: Sha256
    parameters: Parameters
    settings: AppliedRunConfig


class RunToMake(BaseModel):
    """A run to make: its request key, None for a strategy whose expressions call Python, which
    keys none, with the parameters as bound and the settings as applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[LookupVerdict.TO_MAKE] = LookupVerdict.TO_MAKE
    request_key: Sha256 | None
    parameters: Parameters
    settings: AppliedRunConfig


class RunStrategy(BaseModel):
    """The saved strategy version a run names, as the index holds it: the strategy's row's id and
    name, the version's row's id and number, and the instrument its code names and the timeframe;
    the run's settings name the instrument it trades, which may be another (D-114)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    version_id: str
    version: int
    instrument: str
    timeframe: str


class KeyMetrics(BaseModel):
    """What a list shows of how a saved run went: its net P&L, its trades, its maximum drawdown,
    and its robustness verdict, as its record holds them."""

    model_config = ConfigDict(frozen=True)

    pnl: Decimal
    trades: int
    max_drawdown: Decimal
    verdict: Verdict


class _Run(BaseModel):
    """What every run's row holds: its id; when it was asked for, or saved where the index found
    it saved; its origin; its parameters as bound; the trade dates its window spans, its signal
    bars' once saved; its settings, every default applied; and, worked out at each read from the
    instrument it trades (D-117), the currency its money counts in and the fee its table charges
    on its last day, both None where its row names no instrument, as one indexed before D-114 for
    a strategy built in a notebook, or one this store no longer defines, and the fee None where
    the table does not price the instrument, as a submission refused since."""

    model_config = ConfigDict(frozen=True)

    id: str
    created_at: AwareDatetime
    origin: RunOrigin
    parameters: Parameters
    start: date
    end: date
    settings: AppliedRunConfig
    currency: Currency | None
    fee: Fee | None


class SubmittedRun(_Run):
    """A run asked for whose job has yet to save it: the version it runs, its job's id, and the
    job's status, progress, message, and error, and when it was asked to stop."""

    state: Literal[RunState.SUBMITTED] = RunState.SUBMITTED
    strategy: RunStrategy
    status: JobStatus
    progress: float
    message: str | None
    error: str | None
    job_id: str
    cancel_requested_at: AwareDatetime | None


class SavedRun(_Run):
    """A run whose folder is saved and indexed: `succeeded`, at 100; the version it names, None
    for a strategy built in a notebook; the job that made it, None where the index found it
    saved; its run key, the name of its folder; and what a list shows of how it went."""

    state: Literal[RunState.SAVED] = RunState.SAVED
    strategy: RunStrategy | None
    status: Literal[JobStatus.SUCCEEDED] = JobStatus.SUCCEEDED
    progress: Literal[100] = 100
    job_id: str | None
    run_key: Hash
    key_metrics: KeyMetrics


IndexedRun = Annotated[SubmittedRun | SavedRun, Field(discriminator="state")]
"""A run as the lists and its page hold it, in either state."""


class RunStatistics(BaseModel):
    """What a saved run's record says of how it went (step 5.7, D-116): its metrics, the currency
    their money is in, its net P&L as a share of its capital, the fidelity era of each trade date
    it filled on, and its warnings."""

    model_config = ConfigDict(frozen=True)

    currency: Currency
    pnl_share: float
    metrics: Metrics
    fidelity_eras: tuple[FidelityEra, ...]
    warnings: tuple[str, ...]


class EquityCurve(BaseModel):
    """A saved run's account for a chart (step 5.7, D-116): its capital, and for each decision
    kept, one entry a column: its close in whole seconds since the epoch, the equity, and how far
    the equity lies below its peak, each in the instrument's currency."""

    model_config = ConfigDict(frozen=True)

    capital: float
    time: tuple[int, ...]
    equity: tuple[float, ...]
    drawdown: tuple[float, ...]


class RunPage(BaseModel):
    """A page of the runs, newest first (step 5.6), with the cursor of the next, None on the
    last."""

    model_config = ConfigDict(frozen=True)

    runs: tuple[IndexedRun, ...]
    next_cursor: str | None


class StressedRuns(BaseModel):
    """The runs of a stress (step 5.6, D-29): the base run, then the same at one and at two more
    ticks of slippage on market and stop orders, each a run of its own."""

    model_config = ConfigDict(frozen=True)

    runs: tuple[IndexedRun, IndexedRun, IndexedRun]


class EstimateState(StrEnum):
    """What the estimate of a run found: the store holds none of its instrument, or an estimate."""

    NO_DATA = "no_data"
    ESTIMATED = "estimated"


class NoDataToEstimate(BaseModel):
    """A run's estimate where the store holds none of the instrument it would trade, with the
    version's timeframe and the `instruments` the store holds, which it could trade instead."""

    model_config = ConfigDict(frozen=True)

    state: Literal[EstimateState.NO_DATA] = EstimateState.NO_DATA
    instrument: str
    timeframe: str
    instruments: tuple[str, ...]


class RunEstimated(WindowEstimate):
    """What a run of the version would read, before anything runs (`WindowEstimate`), with the
    instrument it would trade, the version's timeframe, and the `instruments` the store holds."""

    state: Literal[EstimateState.ESTIMATED] = EstimateState.ESTIMATED
    instrument: str
    timeframe: str
    instruments: tuple[str, ...]


RunEstimate = Annotated[NoDataToEstimate | RunEstimated, Field(discriminator="state")]
"""What `POST /v1/runs/estimate` answers."""


class NewRun(BaseModel):
    """A run to queue (`fefat_app.ports.RunRecords.submitted`): the strategy version's row, the
    payload of its `backtest` job, the parameters as bound, the window asked for, the settings as
    applied, and its request key, None for a strategy that keys none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version_id: str
    payload: dict[str, Any]
    parameters: Parameters
    start: date
    end: date
    settings: AppliedRunConfig
    request_key: Sha256 | None


@dataclass(frozen=True)
class Submitted:
    """What a submission gives: its run, and the id of the job it queued for the dispatcher,
    None where it found the run of its request waiting already."""

    run: SubmittedRun
    queued_job_id: str | None


class NoSuchRunError(ValueError):
    """A run's id or run key that no run of the index has."""

    def __init__(self, run: str) -> None:
        super().__init__(f"Expected the id or the run key of a run, got {run!r}, which names none.")


class ResultsRefusedError(ValueError):
    """A run whose results cannot be read, in words that say what to do: not saved yet, its
    folder gone, or a folder this engine does not read (step 5.7)."""


class RunCursorError(ValueError):
    """A page's cursor the list did not give."""

    def __init__(self, cursor: str) -> None:
        super().__init__(f"Expected a cursor the list of runs gave, got {cursor!r}.")


class EstimateRefusedError(ValueError):
    """An estimate the SDK refuses, in its words, such as for a contract the store does not
    hold, or a session that holds only data finer than the fidelity."""
