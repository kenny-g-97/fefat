"""The exit plan an execution template's entry carries (`docs/spec/fill-semantics.md` §22 to
§24): its stop, targets, breakeven, and trailing stop from the specification, with the entry
row's features and prices worked into whole ticks where the fill does not change them
(F-RND-01), and the rest left to the fill (`fefat.reference.exit_plan`)."""

from collections.abc import Mapping
from typing import Any

from fefat.market.calendar import utc_text
from fefat.reference.exit_plan import (
    AtPrice,
    BreakevenPlan,
    ExitPlan,
    PercentAway,
    PlannedLeg,
    RiskMultiple,
    RiskTrigger,
    TargetTrigger,
    TicksAway,
    TicksTrigger,
    TrailingPlan,
    Trigger,
    exact,
    feature_ticks,
    feature_units,
)
from fefat.reference.orders import Side
from fefat.reference.units import price_text
from fefat.strategy import exits as rules
from fefat.strategy.spec import Execution


def exit_plan_of(execution: Execution, row: Mapping[str, Any], side: Side, tick: int) -> ExitPlan:
    """The exit plan of an entry on `side` that `row`, the entry row, places (F-PLN-01)."""
    stop = None if execution.stop is None else _stop(execution.stop, row, tick)
    targets = tuple(_target(target, row, tick) for target in execution.targets)
    stops_and_targets = [leg for leg in (stop, *targets) if leg is not None]
    _require_the_stop_below_the_targets(stops_and_targets, stop, row, side)
    return ExitPlan(
        stop,
        targets,
        None if execution.breakeven is None else _breakeven(execution.breakeven),
        None if execution.trailing is None else _trailing(execution.trailing, row, tick),
    )


def _stop(stop: rules.StopRule, row: Mapping[str, Any], tick: int) -> PlannedLeg:
    if isinstance(stop, rules.TicksStop):
        return PlannedLeg(TicksAway(stop.ticks))
    if isinstance(stop, rules.PercentStop):
        return PlannedLeg(PercentAway(exact(stop.percent)))
    if isinstance(stop, rules.AtrStop):
        units = feature_units(row, stop.feature)
        return PlannedLeg(TicksAway(feature_ticks(exact(stop.multiple), units, tick, False)))
    return PlannedLeg(AtPrice(column_price(row, "stop_price", tick)))


def _target(target: rules.ProfitTarget, row: Mapping[str, Any], tick: int) -> PlannedLeg:
    price = target.price
    fraction = exact(target.fraction)
    if isinstance(price, rules.TicksTarget):
        return PlannedLeg(TicksAway(price.ticks), fraction=fraction)
    if isinstance(price, rules.AtrTarget):
        units = feature_units(row, price.feature)
        ticks = feature_ticks(exact(price.multiple), units, tick, True)
        return PlannedLeg(TicksAway(ticks), fraction=fraction)
    if isinstance(price, rules.RMultipleTarget):
        return PlannedLeg(RiskMultiple(exact(price.multiple)), fraction=fraction)
    return PlannedLeg(AtPrice(column_price(row, "target_price", tick)), fraction=fraction)


def _trigger(trigger: rules.ProfitTrigger) -> Trigger:
    if isinstance(trigger, rules.TicksTrigger):
        return TicksTrigger(trigger.ticks)
    if isinstance(trigger, rules.RMultipleTrigger):
        return RiskTrigger(exact(trigger.multiple))
    return TargetTrigger(trigger.target)


def _breakeven(breakeven: rules.BreakevenRule) -> BreakevenPlan:
    return BreakevenPlan(_trigger(breakeven.trigger), breakeven.offset_ticks)


def _trailing(trailing: rules.TrailingStop, row: Mapping[str, Any], tick: int) -> TrailingPlan:
    """The trailing stop's distance at the entry row: its ticks, or its multiple of the row's
    feature rounded down (F-TRL-02); none by the column, which moves to `trail_ref`."""
    by = trailing.by
    ticks, multiple, feature = None, None, None
    if isinstance(by, rules.TicksTrail):
        ticks = by.ticks
    elif isinstance(by, rules.AtrTrail):
        multiple, feature = exact(by.multiple), by.feature
        ticks = feature_ticks(multiple, feature_units(row, feature), tick, False)
    return TrailingPlan(
        ticks=ticks,
        multiple=multiple,
        feature=feature,
        step_ticks=trailing.step_ticks,
        activation=None if trailing.activation is None else _trigger(trailing.activation),
        intrabar=trailing.update is rules.TrailUpdate.INTRABAR,
    )


def column_price(row: Mapping[str, Any], column: str, tick: int) -> int:
    """A price the signal frame gives on `row`, which must be there and on the tick (F-RND-01)."""
    price, at = row.get(column), utc_text(row["ts_close"])
    if price is None:
        raise ValueError(
            f"Expected the signal frame's {column} on the entry's bar closing at {at}, got null."
        )
    if price % tick:
        raise ValueError(
            f"Expected {column} on the instrument's tick of {price_text(tick)}, got "
            f"{price_text(price)} at {at}."
        )
    return price


def _require_the_stop_below_the_targets(
    legs: list[PlannedLeg], stop: PlannedLeg | None, row: Mapping[str, Any], side: Side
) -> None:
    """A stop at `stop_price` lies on the losing side of a target at `target_price`."""
    prices = [leg.price for leg in legs]
    if stop is None or not isinstance(stop.price, AtPrice):
        return
    for target in prices[1:]:
        if isinstance(target, AtPrice) and (target.price - stop.price.price) * side.sign() <= 0:
            below = "below" if side is Side.BUY else "above"
            raise ValueError(
                f"Expected the stop_price {below} the target_price of a {side} entry on the bar "
                f"closing at {utc_text(row['ts_close'])}, got {price_text(stop.price.price)} and "
                f"{price_text(target.price)}."
            )
