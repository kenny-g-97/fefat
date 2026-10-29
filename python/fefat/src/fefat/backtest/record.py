"""A run's record, `run.json` (step 2.10, `02` §7, D-47, D-51): its id and key, the engine's
versions, its strategy, its window, its instrument, each dataset it read with the terms it came
under and the hash of its snapshot, the signal frame's hash, its settings with every default
applied, its fee table, the rolls it crossed, the config the engine read, the fills by fidelity,
the warnings, and a summary of its end."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field

from fefat.backtest.run_config import AppliedRunConfig
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


class StrategyRecord(FrozenModel):
    """The strategy's specification as its document writes it, and the names of its features."""

    spec: dict[str, Any]
    features: tuple[str, ...]


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
    """`run.json`: what a run is, what it read, how it ran, and how it ended."""

    run_id: Hash
    run_key: Hash
    versions: EngineVersions
    strategy: StrategyRecord
    window: Window
    instrument: InstrumentRecord
    datasets: tuple[DatasetRecord, ...] = Field(min_length=1)
    signal_frame_hash: Hash
    config: AppliedRunConfig
    fee_table: FeeTableRecord
    rolls: tuple[RollRecord, ...]
    engine_config: dict[str, Any]
    fidelity_summary: dict[str, int]
    warnings: tuple[str, ...]
    summary: RunSummary
