"""The strategy specification, `StrategySpec`: the JSON document that holds a signal strategy's
execution template, the contract between the strategy builder, the SDK, and the engine
(`02-engine-and-data.md` §2.1, D-53). The Rust types of `fefat-core` (`strategy_spec`) define it,
and its schema, `strategy_spec.schema.json` beside this module, is generated from them (`just
gen-schema`). These models mirror the Rust types field for field, so that a document they write
validates against the schema and loads back equal. Each rule that holds values is one object
tagged by its `kind`; an optional rule left out is not used, and a document leaves it out rather
than writing null:

    StrategySpec.model_validate_json(text).execution.stop  # TicksStop(kind='ticks', ticks=12)
"""

import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BeforeValidator, Field

from fefat.market.calendar_definition import TimeZoneName
from fefat.market.schema import FrozenModel, Timeframe

SPEC_SCHEMA_PATH = Path(__file__).with_name("strategy_spec.schema.json")
"""The JSON schema of the document, generated from the Rust types."""

_LARGEST_COUNT = 4_294_967_295

Count = Annotated[int, Field(ge=1, le=_LARGEST_COUNT)]
"""A count of ticks, signal bars, or minutes, above zero, as the schema's 32-bit counts."""
TickDistance = Annotated[int, Field(ge=0, le=_LARGEST_COUNT)]
"""A distance from a signal bar's close, in ticks."""
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
"""A number above zero: a multiple, a percentage, units, or an amount of money."""
FeatureName = Annotated[str, Field(min_length=1)]
"""A feature's column in the signal frame, such as `atr`."""
LocalTime = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
"""A local time of day, `HH:MM`."""


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


class TicksStop(FrozenModel):
    """A stop `ticks` from the entry's fill price."""

    kind: Literal["ticks"] = "ticks"
    ticks: Count


class PercentStop(FrozenModel):
    """A stop `percent` % of the entry's fill price from it: `0.5` is 0.5 %."""

    kind: Literal["percent"] = "percent"
    percent: Positive


class AtrStop(FrozenModel):
    """A stop `multiple` times a feature of the entry's signal bar, such as its ATR, from the
    entry's fill price."""

    kind: Literal["atr"] = "atr"
    multiple: Positive
    feature: FeatureName


class ColumnStop(FrozenModel):
    """A stop at the signal frame's `stop_price` on the entry's signal bar."""

    kind: Literal["column"] = "column"


StopRule = Annotated[TicksStop | PercentStop | AtrStop | ColumnStop, Field(discriminator="kind")]
"""The stop placed against the position when an entry fills, a stop-market order (F-STP)."""


class TicksTarget(FrozenModel):
    """A target `ticks` from the entry's fill price, in the position's favour."""

    kind: Literal["ticks"] = "ticks"
    ticks: Count


class AtrTarget(FrozenModel):
    """A target `multiple` times a feature of the entry's signal bar from the fill."""

    kind: Literal["atr"] = "atr"
    multiple: Positive
    feature: FeatureName


class RMultipleTarget(FrozenModel):
    """A target `multiple` times the trade's initial risk, the distance to its first stop."""

    kind: Literal["r_multiple"] = "r_multiple"
    multiple: Positive


class ColumnTarget(FrozenModel):
    """A target at the signal frame's `target_price` on the entry's signal bar."""

    kind: Literal["column"] = "column"


TargetPrice = Annotated[
    TicksTarget | AtrTarget | RMultipleTarget | ColumnTarget, Field(discriminator="kind")
]
"""Where a target is."""


class ProfitTarget(FrozenModel):
    """A target placed when an entry fills, a limit order (F-LMT) that closes `fraction` of the
    position still open: 1, the default, closes the rest."""

    price: TargetPrice
    fraction: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 1.0


class TicksTrigger(FrozenModel):
    """The price `ticks` from the entry's fill in the position's favour."""

    kind: Literal["ticks"] = "ticks"
    ticks: Count


class RMultipleTrigger(FrozenModel):
    """A profit of `multiple` times the trade's initial risk."""

    kind: Literal["r_multiple"] = "r_multiple"
    multiple: Positive


class AfterTargetTrigger(FrozenModel):
    """The fill of target `target`, counted from 1."""

    kind: Literal["after_target"] = "after_target"
    target: Annotated[int, Field(ge=1, le=3)]


ProfitTrigger = Annotated[
    TicksTrigger | RMultipleTrigger | AfterTargetTrigger, Field(discriminator="kind")
]
"""A point a trade reaches in its favour."""


class BreakevenRule(FrozenModel):
    """When the stop moves to the entry's fill price, `offset_ticks` beyond it in the position's
    favour (below zero, short of it)."""

    trigger: ProfitTrigger
    offset_ticks: int = 0


class TicksTrail(FrozenModel):
    """A trailing stop `ticks` behind the best price since its activation."""

    kind: Literal["ticks"] = "ticks"
    ticks: Count


class AtrTrail(FrozenModel):
    """A trailing stop `multiple` times a feature of the signal bars behind the best price."""

    kind: Literal["atr"] = "atr"
    multiple: Positive
    feature: FeatureName


class ColumnTrail(FrozenModel):
    """A trailing stop at the signal frame's `trail_ref` of each signal bar."""

    kind: Literal["column"] = "column"


TrailBy = Annotated[TicksTrail | AtrTrail | ColumnTrail, Field(discriminator="kind")]
"""How far behind the price a trailing stop follows."""


class TrailUpdate(StrEnum):
    """When a trailing stop moves: as the price moves inside a bar, or at signal bar closes."""

    INTRABAR = "intrabar"
    BAR_CLOSE = "bar_close"


class TrailingStop(FrozenModel):
    """A stop that follows the price `by` a distance, `step_ticks` at a time (every tick
    without it), from its `activation` (the entry's fill without it)."""

    by: TrailBy
    step_ticks: Count | None = None
    activation: ProfitTrigger | None = None
    update: TrailUpdate = TrailUpdate.INTRABAR


class Weekday(StrEnum):
    """A day of the week, as the specification spells it."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class EntryWindow(FrozenModel):
    """A stretch of local time, from `start` to `end`, in which entries may be placed, on
    `weekdays` (every day without them); an `end` before `start` runs past midnight."""

    start: LocalTime
    end: LocalTime
    weekdays: Annotated[Sequence[Weekday], AfterValidator(tuple)] | None = None


def _windows_of_pairs(windows: object) -> object:
    """Entry windows given as `(start, end)` pairs, as `02-engine-and-data.md` §5 writes them,
    read as the windows' fields."""
    if not isinstance(windows, list | tuple):
        return windows
    return [
        {"start": window[0], "end": window[1]}
        if isinstance(window, tuple) and len(window) == 2
        else window
        for window in windows
    ]


class TimeRules(FrozenModel):
    """Entry windows and time exits, in local time of `tz`. From `flat_by` each trade date, the
    position is closed at the first signal close at or after that time on the trade date's own
    day, which must fall inside its session, outside its halts, and on the signal bars' grid,
    and no entry is placed; `max_bars` and `max_minutes` limit how long a position stays open;
    `no_overnight` and `no_weekend` close it before each session's close and before the week's
    last session closes."""

    tz: TimeZoneName
    windows: Annotated[
        Sequence[EntryWindow], BeforeValidator(_windows_of_pairs), AfterValidator(tuple)
    ] = ()
    flat_by: LocalTime | None = None
    max_bars: Count | None = None
    max_minutes: Count | None = None
    no_overnight: bool = False
    no_weekend: bool = False


class BarsCooldown(FrozenModel):
    """No entry for the next `bars` signal bars after a losing trade."""

    kind: Literal["bars"] = "bars"
    bars: Count


class MinutesCooldown(FrozenModel):
    """No entry for the next `minutes` minutes after a losing trade."""

    kind: Literal["minutes"] = "minutes"
    minutes: Count


Cooldown = Annotated[BarsCooldown | MinutesCooldown, Field(discriminator="kind")]
"""How long no entry is placed after a losing trade."""


class Limits(FrozenModel):
    """Filters on entries: no entry on a bar where the feature `blackout` is true; at most
    `max_trades_per_day` entries and `max_losses_per_day` losing trades each trade date; none
    after a loss of `daily_loss_stop` or a profit of `profit_lock` in the account's currency that
    trade date, or during `cooldown_after_loss`; and with `fresh_signal`, only on a signal that
    was false on the bar before."""

    blackout: FeatureName | None = None
    max_trades_per_day: Count | None = None
    max_losses_per_day: Count | None = None
    daily_loss_stop: Positive | None = None
    profit_lock: Positive | None = None
    cooldown_after_loss: Cooldown | None = None
    fresh_signal: bool = False


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
