"""The helpers that build an execution template's rules as `02-engine-and-data.md` §5 writes them,
`Stop(atr=1.5)`, `Target(r=2)`, `Fixed(1)`: each takes one choice by keyword and builds the rule of
`fefat.strategy.spec` that the choice names, so that a strategy reads like the builder's form.

    Execution(entry=Market(), stop=Stop(ticks=12), targets=[Target(ticks=24)], sizing=Fixed(1))
"""

from fefat.strategy.exits import (
    AfterTargetTrigger,
    AtrStop,
    AtrTarget,
    AtrTrail,
    BreakevenRule,
    ColumnStop,
    ColumnTarget,
    ColumnTrail,
    PercentStop,
    ProfitTarget,
    ProfitTrigger,
    RMultipleTarget,
    RMultipleTrigger,
    StopRule,
    TargetPrice,
    TicksStop,
    TicksTarget,
    TicksTrail,
    TicksTrigger,
    TrailBy,
    TrailingStop,
    TrailUpdate,
)
from fefat.strategy.spec import (
    FixedSize,
    LimitEntryAtColumn,
    LimitEntryOffset,
    MarketEntry,
    NotionalSize,
    RiskAmountSize,
    RiskPercentSize,
    StopEntryAtColumn,
    StopEntryOffset,
)


def _require_one(rule: str, **choices: object) -> None:
    """Refuse no choice, or more than one, among `choices` for `rule`."""
    given = [name for name, value in choices.items() if value is not None and value is not False]
    if len(given) != 1:
        raise ValueError(
            f"Expected one of {', '.join(choices)} for {rule}, got {', '.join(given) or 'none'}."
        )


def Market() -> MarketEntry:  # noqa: N802
    """An entry by a market order (F-MKT)."""
    return MarketEntry()


def Limit(  # noqa: N802
    *, column: bool = False, offset_ticks: int | None = None, time_to_live_bars: int | None = None
) -> LimitEntryAtColumn | LimitEntryOffset:
    """An entry by a limit order at the signal frame's `entry_price` (`column=True`) or
    `offset_ticks` from the signal bar's close, below it for a buy, working for
    `time_to_live_bars` signal bars."""
    _require_one("a limit entry", column=column, offset_ticks=offset_ticks)
    if offset_ticks is not None:
        return LimitEntryOffset(ticks=offset_ticks, time_to_live_bars=time_to_live_bars)
    return LimitEntryAtColumn(time_to_live_bars=time_to_live_bars)


def StopEntry(  # noqa: N802
    *, column: bool = False, offset_ticks: int | None = None, time_to_live_bars: int | None = None
) -> StopEntryAtColumn | StopEntryOffset:
    """An entry by a stop-market order at the signal frame's `entry_price` (`column=True`) or
    `offset_ticks` from the signal bar's close, above it for a buy, working for
    `time_to_live_bars` signal bars."""
    _require_one("a stop entry", column=column, offset_ticks=offset_ticks)
    if offset_ticks is not None:
        return StopEntryOffset(ticks=offset_ticks, time_to_live_bars=time_to_live_bars)
    return StopEntryAtColumn(time_to_live_bars=time_to_live_bars)


def Stop(  # noqa: N802
    *,
    ticks: int | None = None,
    percent: float | None = None,
    atr: float | None = None,
    column: bool = False,
    feature: str = "atr",
) -> StopRule:
    """The stop placed when an entry fills: `ticks` or `percent` % from the fill, `atr` times
    the entry bar's `feature` from it, or at the signal frame's `stop_price` (`column=True`)."""
    _require_one("a stop", ticks=ticks, percent=percent, atr=atr, column=column)
    if ticks is not None:
        return TicksStop(ticks=ticks)
    if percent is not None:
        return PercentStop(percent=percent)
    if atr is not None:
        return AtrStop(multiple=atr, feature=feature)
    return ColumnStop()


def Target(  # noqa: N802
    *,
    ticks: int | None = None,
    atr: float | None = None,
    r: float | None = None,
    column: bool = False,
    feature: str = "atr",
    fraction: float = 1.0,
) -> ProfitTarget:
    """A target that closes `fraction` of the position still open (the rest by default):
    `ticks` from the fill, `atr` times the entry bar's `feature` from it, `r` times the trade's
    initial risk, or at the signal frame's `target_price` (`column=True`)."""
    _require_one("a target", ticks=ticks, atr=atr, r=r, column=column)
    price: TargetPrice = ColumnTarget()
    if ticks is not None:
        price = TicksTarget(ticks=ticks)
    elif atr is not None:
        price = AtrTarget(multiple=atr, feature=feature)
    elif r is not None:
        price = RMultipleTarget(multiple=r)
    return ProfitTarget(price=price, fraction=fraction)


def Breakeven(  # noqa: N802
    *,
    ticks: int | None = None,
    r: float | None = None,
    after_target: int | None = None,
    offset_ticks: int = 0,
) -> BreakevenRule:
    """The stop moved to the entry's fill price, `offset_ticks` beyond it, once the trade gains
    `ticks` or `r` times its initial risk, or once target `after_target` (from 1) fills."""
    _require_one("a breakeven", ticks=ticks, r=r, after_target=after_target)
    trigger: ProfitTrigger
    if ticks is not None:
        trigger = TicksTrigger(ticks=ticks)
    elif r is not None:
        trigger = RMultipleTrigger(multiple=r)
    else:
        trigger = AfterTargetTrigger.model_validate({"target": after_target})
    return BreakevenRule(trigger=trigger, offset_ticks=offset_ticks)


def Trailing(  # noqa: N802
    *,
    ticks: int | None = None,
    atr: float | None = None,
    column: bool = False,
    feature: str = "atr",
    step_ticks: int | None = None,
    activation: ProfitTrigger | None = None,
    update: TrailUpdate | None = None,
) -> TrailingStop:
    """A stop that follows the price `ticks` or `atr` times the signal bars' `feature` behind
    the best price, or at the signal frame's `trail_ref` (`column=True`), `step_ticks` at a
    time, from `activation`, moving as `update` says: by default at every price, and at bar
    closes for the column, which moves at decisions alone (F-TRL-04)."""
    _require_one("a trailing stop", ticks=ticks, atr=atr, column=column)
    if update is None:
        update = TrailUpdate.BAR_CLOSE if column else TrailUpdate.INTRABAR
    by: TrailBy = ColumnTrail()
    if ticks is not None:
        by = TicksTrail(ticks=ticks)
    elif atr is not None:
        by = AtrTrail(multiple=atr, feature=feature)
    return TrailingStop(by=by, step_ticks=step_ticks, activation=activation, update=update)


def Fixed(units: float) -> FixedSize:  # noqa: N802
    """The same `units` on every entry: contracts, or the base asset for crypto."""
    return FixedSize(units=units)


def Notional(amount: float) -> NotionalSize:  # noqa: N802
    """The units whose value at the entry is `amount` in the account's currency."""
    return NotionalSize(amount=amount)


def RiskPerTrade(  # noqa: N802
    *, amount: float | None = None, percent: float | None = None
) -> RiskAmountSize | RiskPercentSize:
    """The units whose loss at the stop is `amount` in the account's currency, or `percent` %
    of equity."""
    _require_one("a risk per trade", amount=amount, percent=percent)
    if amount is not None:
        return RiskAmountSize(amount=amount)
    return RiskPercentSize.model_validate({"percent": percent})
