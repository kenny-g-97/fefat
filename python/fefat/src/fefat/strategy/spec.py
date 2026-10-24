"""The strategy specification, `StrategySpec`: the JSON document that holds a signal strategy's
execution template, the contract between the strategy builder, the SDK, and the engine
(`02-engine-and-data.md` §2.1, D-53). The Rust types of `fefat-core` (`strategy_spec`) define it,
and its schema, `strategy_spec.schema.json` beside this module, is generated from them (`just
gen-schema`). These models, with the exits, time rules, and limits of `fefat.strategy.exits`,
mirror the Rust types field for field, so that a document they write validates against the
schema and loads back equal. Each rule that holds values is one object tagged by its `kind`; an
optional rule left out is not used, and a document leaves it out rather than writing null:

    StrategySpec.model_validate_json(text).execution.stop  # TicksStop(kind='ticks', ticks=12)
"""

import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field

from fefat.market.schema import FrozenModel, Timeframe
from fefat.strategy.exits import (
    BreakevenRule,
    Count,
    Limits,
    Positive,
    ProfitTarget,
    StopRule,
    TickDistance,
    TimeRules,
    TrailingStop,
)

SPEC_SCHEMA_PATH = Path(__file__).with_name("strategy_spec.schema.json")
"""The JSON schema of the document, generated from the Rust types."""


def _timeframe_text(text: str) -> str:
    """`text` once it reads as a timeframe, such as `5m`."""
    Timeframe.parse(text)
    return text


TimeframeText = Annotated[str, AfterValidator(_timeframe_text)]
"""The timeframe of the signal bars, such as `5m`: a count, then `s`, `m`, `h`, or `d`."""
InstrumentRoot = Annotated[str, Field(min_length=1)]
"""The root a strategy trades, as the instrument table names it, such as `ES`."""


class MarketEntry(FrozenModel):
    """An entry by a market order (F-MKT)."""

    kind: Literal["market"] = "market"


class LimitEntryAtColumn(FrozenModel):
    """An entry by a limit order at the signal frame's `entry_price` (F-LMT), working for
    `time_to_live_bars` signal bars, or until it fills without it."""

    kind: Literal["limit_at_column"] = "limit_at_column"
    time_to_live_bars: Count | None = None


class LimitEntryOffset(FrozenModel):
    """An entry by a limit order `ticks` from the signal bar's close, below it for a buy and above
    it for a sell (F-LMT)."""

    kind: Literal["limit_offset"] = "limit_offset"
    ticks: TickDistance
    time_to_live_bars: Count | None = None


class StopEntryAtColumn(FrozenModel):
    """An entry by a stop-market order at the signal frame's `entry_price` (F-STP)."""

    kind: Literal["stop_at_column"] = "stop_at_column"
    time_to_live_bars: Count | None = None


class StopEntryOffset(FrozenModel):
    """An entry by a stop-market order `ticks` from the signal bar's close, above it for a buy and
    below it for a sell (F-STP)."""

    kind: Literal["stop_offset"] = "stop_offset"
    ticks: TickDistance
    time_to_live_bars: Count | None = None


EntryOrder = Annotated[
    MarketEntry | LimitEntryAtColumn | LimitEntryOffset | StopEntryAtColumn | StopEntryOffset,
    Field(discriminator="kind"),
]
"""The order an entry signal places; with a limit or a stop entry, both entry signals on one bar
place a buy and a sell as one OCO group, and with a market entry such a bar is refused."""


class OppositeSignal(StrEnum):
    """What an entry signal against the open position does."""

    IGNORE = "ignore"
    CLOSE = "close"
    REVERSE = "reverse"


class FixedSize(FrozenModel):
    """The same `units` on every entry: contracts, or the base asset for crypto."""

    kind: Literal["fixed"] = "fixed"
    units: Positive


class NotionalSize(FrozenModel):
    """The units whose value at the entry is `amount` in the account's currency."""

    kind: Literal["notional"] = "notional"
    amount: Positive


class RiskAmountSize(FrozenModel):
    """The units whose loss at the stop is `amount` in the account's currency."""

    kind: Literal["risk_amount"] = "risk_amount"
    amount: Positive


class RiskPercentSize(FrozenModel):
    """The units whose loss at the stop is `percent` % of equity, the run's capital and its
    closed profit and loss: `1` is 1 %."""

    kind: Literal["risk_percent"] = "risk_percent"
    percent: Positive


Sizing = Annotated[
    FixedSize | NotionalSize | RiskAmountSize | RiskPercentSize, Field(discriminator="kind")
]
"""How many units an entry trades, in whole lot steps; the signal frame's `size_mult`
multiplies the size where it is given."""


class Execution(FrozenModel):
    """The execution template: how a strategy enters on its signals, what an entry signal
    against the open position does, the stop, the targets (three at most, one OCO group with the
    stop), breakeven, trailing, time rules, entry limits, sizing, and whether the signal frame's
    `long_exit` and `short_exit` close the position."""

    entry: EntryOrder
    on_opposite_signal: OppositeSignal = OppositeSignal.IGNORE
    stop: StopRule | None = None
    targets: Annotated[Sequence[ProfitTarget], Field(max_length=3), AfterValidator(tuple)] = ()
    breakeven: BreakevenRule | None = None
    trailing: TrailingStop | None = None
    time: TimeRules | None = None
    limits: Limits = Field(default_factory=Limits)
    sizing: Sizing
    signal_exit: bool = True


class StrategySpec(FrozenModel):
    """A signal strategy's specification: the instrument it trades, the timeframe of the signal
    bars whose closes decide, and its execution template."""

    spec_version: Literal[1]
    instrument: InstrumentRoot
    timeframe: TimeframeText
    execution: Execution

    def document(self) -> dict[str, Any]:
        """The specification as its JSON document holds it, without the rules not used."""
        return self.model_dump(mode="json", exclude_none=True)

    def document_json(self) -> str:
        """The JSON document, indented by two spaces."""
        return self.model_dump_json(exclude_none=True, indent=2)


def spec_schema() -> dict[str, Any]:
    """The JSON schema of the document, as the Rust types generate it (draft 2020-12)."""
    return json.loads(SPEC_SCHEMA_PATH.read_text(encoding="utf-8"))
