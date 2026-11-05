"""A run's record, `run.json` (step 2.10, `02` §7, D-47, D-51): its id and key, the engine's
versions, its strategy, its window, its instrument, each dataset it read with the terms it came
under and the hash of its snapshot, the signal frame's hash, its settings with every default
applied, its fee table, the rolls it crossed, the config the engine read, the warnings, a summary
of its end, and, from step 2.11, its metrics; from step 2.12, the fidelity era of each trade
date, in place of the fills by fidelity; from step 2.13, the mix of its trades' path
fidelities; from step 3.2, the era of each trade date's signal bars, the level each was built
from; and, from step 3.7, the version of each feature its strategy's slots read."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, JsonValue

from fefat.backtest.metrics import Metrics
from fefat.backtest.run_config import AppliedRunConfig
from fefat.market.fidelity import FidelityEra, FidelityText
from fefat.market.instruments import InstrumentKind
from fefat.market.layout import DatasetOrigin
from fefat.market.roll_decisions import RollReason
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""A BLAKE3 hash as 64 lower-case hexadecimal digits."""


class EngineVersions(FrozenModel):
    """The versions a run key covers (`02` §4)."""

    engine: int = Field(ge=1)
    fill_model: int = Field(ge=1)
    artifact_schema: int = Field(ge=1)


class FeaturePin(FrozenModel):
    """A feature a strategy reads in a slot, pinned as the library keeps it (step 3.7): the slot,
    the feature's name, the number and content hash of its saved version, and the parameters the
    slot binds."""

    slot: str
    name: str
    version: int = Field(ge=1)
    hash: Sha256
    parameters: dict[str, JsonValue]


class StrategyRecord(FrozenModel):
    """The strategy's specification as its document writes it, the names of its features'
    columns, and, from step 3.7, the version of each feature its slots read, none for a plain
    expression or in a record written before."""

    spec: dict[str, Any]
    features: tuple[str, ...]
    feature_versions: tuple[FeaturePin, ...] = ()


class Window(FrozenModel):
    """The trade dates a run's signal bars span, from `start` to `end`."""

    start: date
    end: date


class InstrumentRecord(FrozenModel):
    """The instrument as the instrument table gives it."""

    root: str
    kind: InstrumentKind
    currency: str
    tick_size: Decimal
    point_value: Decimal
    lot_step: Decimal


class DatasetRecord(FrozenModel):
    """A dataset a run read: where it is, under which terms it came (D-47), and the snapshot of
    the files the run pinned, its request's dates and its hash (ADR-0019)."""

    provider: str
    schema_name: str
    root: str
    origin: DatasetOrigin
    licence_scope: str
    first: date
    last: date
    snapshot: Sha256


class FeeTableRecord(FrozenModel):
    """The fee table a run paid, and each schedule's date and fee of its root as text."""

    name: str
    schedules: tuple[tuple[date, str], ...]


class RollRecord(FrozenModel):
    """A roll a run crossed (D-44): the trade date its new front serves from, the contracts,
    the gap in the instrument's price, and why."""

    trade_date: date
    rolled_from: str
    contract: str
    gap: Decimal
    reason: RollReason


class PathFidelity(FrozenModel):
    """The trades whose paths have one fidelity, the coarsest level their marks and fills came
    from (`03-prop-simulator.md` §4.4, step 2.13)."""

    fidelity: FidelityText
    trades: int = Field(ge=1)


class RunSummary(FrozenModel):
    """A run's end: its fills, the ambiguous ones among them (F-BAR-05), its trades, the lots
    held, positive long, the cash, and the net profit and loss of its trades, in the
    instrument's currency."""

    fills: int = Field(ge=0)
    ambiguous_fills: int = Field(ge=0)
    trades: int = Field(ge=0)
    position: int
    cash: Decimal
    pnl: Decimal


class RunRecord(FrozenModel):
    """`run.json`: what a run is, what it read, how it ran, the fidelity eras of its trade dates,
    the mix of its trades' path fidelities, in the order each first closed, how it ended, and its
    metrics."""

    run_id: Hash
    run_key: Hash
    versions: EngineVersions
    strategy: StrategyRecord
    window: Window
    instrument: InstrumentRecord
    datasets: tuple[DatasetRecord, ...] = Field(min_length=1)
    signal_frame_hash: Hash
    signal_bar_eras: tuple[FidelityEra, ...] = Field(min_length=1)
    config: AppliedRunConfig
    fee_table: FeeTableRecord
    rolls: tuple[RollRecord, ...]
    engine_config: dict[str, Any]
    fidelity_eras: tuple[FidelityEra, ...] = Field(min_length=1)
    path_fidelities: tuple[PathFidelity, ...]
    warnings: tuple[str, ...]
    summary: RunSummary
    metrics: Metrics
