"""The exits, time rules, and limits of an execution template (`02-engine-and-data.md` §2.1,
D-53), and the values a specification counts in, mirroring the Rust module `strategy_spec::exits`
of `fefat-core` field for field (`fefat.strategy.spec`)."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field

from fefat.market.calendar_definition import TimeZoneName
from fefat.market.schema import FrozenModel

_LARGEST_COUNT = 4_294_967_295

Count = Annotated[int, Field(ge=1, le=_LARGEST_COUNT)]
"""A count of ticks, signal bars, or minutes, above zero, as the schema's 32-bit counts."""
TickDistance = Annotated[int, Field(ge=0, le=_LARGEST_COUNT)]
"""A distance from a signal bar's close, in ticks."""
TickOffset = Annotated[int, Field(ge=-(2**63), le=2**63 - 1)]
"""A signed number of ticks, as the schema's 64-bit integers."""
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
"""A number above zero: a multiple, a percentage, units, or an amount of money."""
FeatureName = Annotated[str, Field(min_length=1)]
"""A feature's column in the signal frame, such as `atr`."""
LocalTime = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
"""A local time of day, `HH:MM`."""


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
    offset_ticks: TickOffset = 0


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
    weekdays: Annotated[Sequence[Weekday], Field(min_length=1), AfterValidator(tuple)] | None = None


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
