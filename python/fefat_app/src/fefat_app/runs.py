"""The runs as the app serves them (step 5.3, D-84, ADR-0020): a backtest of a saved strategy
version asked for through the API, a submission with its `backtest` job until its folder is saved,
then the index of that folder, `runs/<run key>/`, which stays the record; what the executor's
lookup answers before a job is queued; and what a submission gives. A run's status is derived, not
kept: `succeeded` once its folder is indexed, whatever its job says, its job's before, so that the
reaper's requeues and timeouts never leave two statuses apart. Frozen models, as at every
boundary, kept apart from the port in `fefat_app.ports`, as `fefat_app.execution` and
`fefat_app.library` keep theirs; they import neither the ports nor the executor's specs, which
read them."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from fefat.backtest.metrics import Metrics
from fefat.backtest.record import Hash
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.market.fidelity import FidelityEra
from fefat.market.snapshot import Sha256
from fefat_app.job_models import JobStatus


class RunOrigin(StrEnum):
    """Where a run's row comes from: asked for through the API, or found saved by the index; the
    batches of later phases add theirs."""

    MANUAL = "manual"


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
    parameters: dict[str, JsonValue]
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
    parameters: dict[str, JsonValue]
    settings: AppliedRunConfig


class RunToMake(BaseModel):
    """A run to make: its request key, None for a strategy whose expressions call Python, which
    keys none, with the parameters as bound and the settings as applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[LookupVerdict.TO_MAKE] = LookupVerdict.TO_MAKE
    request_key: Sha256 | None
    parameters: dict[str, JsonValue]
    settings: AppliedRunConfig


class RunStrategy(BaseModel):
    """The saved strategy version a run names, as the index holds it: the strategy's row's id and
    name, and the version's row's id and number."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    version_id: str
    version: int


class IndexedRun(BaseModel):
    """A run as the index holds it: its row's id; when it was asked for, or saved where the index
    found it saved; its origin; the strategy version it names, None for one written in a notebook;
    its parameters as bound; the trade dates its window spans, its signal bars' once saved; its
    settings, every default applied; its status, `succeeded` once its folder is indexed, else its
    job's, with the job's progress, message, and error; its job's id, None where the index found
    it saved; and its run key once saved, the name of its folder."""

    model_config = ConfigDict(frozen=True)

    id: str
    created_at: AwareDatetime
    origin: RunOrigin
    strategy: RunStrategy | None
    parameters: dict[str, JsonValue]
    start: date
    end: date
    settings: AppliedRunConfig
    status: JobStatus
    progress: float
    message: str | None
    error: str | None
    job_id: str | None
    run_key: Hash | None


class RunWithMetrics(IndexedRun):
    """A run with what its record says of how it went, once saved: its metrics, the fidelity era
    of each trade date it filled on, and its warnings; none of them before."""

    metrics: Metrics | None
    fidelity_eras: tuple[FidelityEra, ...]
    warnings: tuple[str, ...]


class NewRun(BaseModel):
    """A run to queue (`fefat_app.ports.RunRecords.submitted`): the strategy version's row, the
    payload of its `backtest` job, the parameters as bound, the window asked for, the settings as
    applied, and its request key, None for a strategy that keys none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version_id: str
    payload: dict[str, Any]
    parameters: dict[str, JsonValue]
    start: date
    end: date
    settings: AppliedRunConfig
    request_key: Sha256 | None


@dataclass(frozen=True)
class Submitted:
    """What a submission gives: its run, and the id of the job it queued for the dispatcher,
    None where it found the run of its request waiting already."""

    run: IndexedRun
    queued_job_id: str | None


class NoSuchRunError(ValueError):
    """A run's id that no run of the index has."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Expected the id of a run, got {run_id!r}, which names none.")
