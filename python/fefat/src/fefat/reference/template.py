"""The execution template in the reference engine (step 2.3, D-53): `TemplateStrategy` runs a
`StrategySpec`'s basic subset over its signal frame as an `on_bar` strategy
(`fefat.reference.strategy`), so that the Rust engine has an oracle for templates too. The subset
is a market entry that ignores opposite signals; a stop in ticks or at the frame's `stop_price`
and one target in ticks, as an R multiple of a stop in ticks, or at `target_price`; signal exits;
flat-by; and a fixed size times `size_mult` in whole lots. The rest of the template arrives in
step 2.8 and is refused until then.

    template = TemplateStrategy(strategy.to_spec(), signals, parameters, sessions)
    engine.run(tape, decisions_of(signals), template.on_bar)
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl

from fefat.market.calendar import SessionTable, utc_text
from fefat.market.schema import Timeframe
from fefat.reference.orders import AtPrice, Side, TemplateBracket, TicksAway
from fefat.reference.strategy import DecisionContext
from fefat.reference.time_rules import flat_by_instants
from fefat.reference.units import InstrumentParameters, lots_of, price_text
from fefat.strategy.exits import (
    ColumnStop,
    ColumnTarget,
    Limits,
    ProfitTarget,
    RMultipleTarget,
    StopRule,
    TicksStop,
    TicksTarget,
    TimeRules,
)
from fefat.strategy.signal_frame import require_one_entry_per_bar, validated_signal_frame
from fefat.strategy.spec import (
    Execution,
    FixedSize,
    MarketEntry,
    OppositeSignal,
    StrategySpec,
)

_SUBSET = "a market entry, a stop and one target, signal exits, flat-by, and a fixed size"


def basic_subset_refusals(spec: StrategySpec) -> list[str]:
    """What `spec` holds beyond the reference engine's basic subset, in words: nothing when the
    subset holds all of it."""
    execution = spec.execution
    limits = [] if execution.limits == Limits() else ["entry limits"]
    return [
        *_entry_refusals(execution),
        *_exit_refusals(execution),
        *_time_refusals(execution.time),
        *limits,
    ]


def _entry_refusals(execution: Execution) -> list[str]:
    refusals = []
    if not isinstance(execution.entry, MarketEntry):
        refusals.append(f"an entry of kind {execution.entry.kind}")
    if execution.on_opposite_signal is not OppositeSignal.IGNORE:
        refusals.append(f"on_opposite_signal {execution.on_opposite_signal}")
    if not isinstance(execution.sizing, FixedSize):
        refusals.append(f"sizing of kind {execution.sizing.kind}")
    return refusals


def _exit_refusals(execution: Execution) -> list[str]:
    stop, targets = execution.stop, execution.targets
    refusals = []
    if stop is None:
        refusals.append("no stop")
    elif not isinstance(stop, TicksStop | ColumnStop):
        refusals.append(f"a stop of kind {stop.kind}")
    if len(targets) != 1:
        refusals.append(f"{len(targets)} targets")
    else:
        refusals += _target_refusals(targets[0], stop)
    if execution.breakeven is not None:
        refusals.append("breakeven")
    if execution.trailing is not None:
        refusals.append("a trailing stop")
    return refusals


def _target_refusals(target: ProfitTarget, stop: StopRule | None) -> list[str]:
    refusals = [] if target.fraction == 1 else ["a target closing part of the position"]
    price = target.price
    if not isinstance(price, TicksTarget | RMultipleTarget | ColumnTarget):
        return [*refusals, f"a target of kind {price.kind}"]
    if not isinstance(price, RMultipleTarget):
        return refusals
    if not isinstance(stop, TicksStop):
        return [*refusals, "an R multiple without a stop in ticks"]
    if not _is_whole(_exact(price.multiple) * stop.ticks):
        off = f"an R multiple of {price.multiple:g} times {stop.ticks} ticks, off the tick"
        return [*refusals, off]
    return refusals


def _time_refusals(time: TimeRules | None) -> list[str]:
    if time is None:
        return []
    used = {
        "entry windows": bool(time.windows),
        "max_bars": time.max_bars is not None,
        "max_minutes": time.max_minutes is not None,
        "no_overnight": time.no_overnight,
        "no_weekend": time.no_weekend,
    }
    return [rule for rule, is_used in used.items() if is_used]


def _exact(number: float) -> Decimal:
    """A number of a specification as the decimal it reads as, `1.3` for 1.3."""
    return Decimal(repr(number))


def _is_whole(number: Decimal) -> bool:
    return number == number.to_integral_value()


class TemplateStrategy:
    """A `StrategySpec`'s basic subset as an `on_bar` strategy over its signal frame, whose rows
    are the decisions (`decisions_of`). At each signal close, in this order: nothing while a
    market order is on its way out of the position, the exit it placed or a stop triggered on
    TBBO (F-STP-02); from the trade date's flat-by time, the position is closed and no
    entry placed; `long_exit` while long or `short_exit` while short closes the position, with
    signal exits on; with a position or working orders, nothing more, an opposite signal being
    ignored; on a bar whose `wake` is false, no entry; and otherwise an entry signal enters at
    the market, its bracket placed when it fills (F-OCO-02)."""

    def __init__(
        self,
        spec: StrategySpec,
        signals: pl.DataFrame,
        instrument: InstrumentParameters,
        sessions: SessionTable | None,
    ) -> None:
        execution, refusals = spec.execution, basic_subset_refusals(spec)
        sizing = execution.sizing
        if refusals or not isinstance(sizing, FixedSize):
            raise ValueError(
                f"Expected a StrategySpec within the reference engine's basic subset ({_SUBSET}), "
                f"got {'; '.join(refusals)}: the rest arrives in step 2.8."
            )
        validated_signal_frame(signals)
        require_one_entry_per_bar(signals)
        self._execution = execution
        self._tick = instrument.tick
        self._lots = lots_of(_exact(sizing.units), instrument.lot_step)
        self._target_ticks = _target_ticks(execution)
        self._require_price_columns(signals)
        self._flat_by = _flat_by_instants(spec, signals, sessions)

    def on_bar(self, bar: Mapping[str, Any], context: DecisionContext) -> None:
        """The decision at one signal close, `bar` the signal frame's row (class docstring)."""
        if context.is_exiting():
            return
        if self._past_flat_by(bar):
            if context.position != 0 or context.has_working_orders():
                context.flatten()
            return
        if self._signals_exit(bar, context.position):
            context.flatten()
            return
        if context.position != 0 or context.has_working_orders() or not _wakes(bar):
            return
        if bar["long_entry"] or bar["short_entry"]:
            side = Side.BUY if bar["long_entry"] else Side.SELL
            context.market(side, self._lots_at(bar), self._bracket(bar, side))

    def _past_flat_by(self, bar: Mapping[str, Any]) -> bool:
        trade_date = bar["trade_date"]
        return trade_date in self._flat_by and bar["ts_close"] >= self._flat_by[trade_date]

    def _signals_exit(self, bar: Mapping[str, Any], position: int) -> bool:
        if not self._execution.signal_exit or position == 0:
            return False
        return bool(bar["long_exit"] if position > 0 else bar["short_exit"])

    def _lots_at(self, bar: Mapping[str, Any]) -> int:
        """The lots of an entry on `bar`: the fixed size times its `size_mult`, in whole lots."""
        if "size_mult" not in bar:
            return self._lots
        multiple = bar["size_mult"]
        lots = _exact(multiple) * self._lots
        if not _is_whole(lots) or lots < 1:
            raise ValueError(
                f"Expected size_mult to make whole lots, at least one, got {multiple} times "
                f"{self._lots} lots on the bar closing at {utc_text(bar['ts_close'])}."
            )
        return int(lots)

    def _bracket(self, bar: Mapping[str, Any], side: Side) -> TemplateBracket:
        """The entry's stop and target: in ticks from its fill, or at the row's prices."""
        stop = self._execution.stop
        stop_leg = (
            TicksAway(ticks=stop.ticks)
            if isinstance(stop, TicksStop)
            else self._column_leg(bar, "stop_price")
        )
        target_leg = (
            TicksAway(ticks=self._target_ticks)
            if self._target_ticks is not None
            else self._column_leg(bar, "target_price")
        )
        if isinstance(stop_leg, AtPrice) and isinstance(target_leg, AtPrice):
            _require_stop_on_the_losing_side(stop_leg, target_leg, side, bar["ts_close"])
        return TemplateBracket(stop=stop_leg, target=target_leg)

    def _column_leg(self, bar: Mapping[str, Any], column: str) -> AtPrice:
        price, at = bar[column], utc_text(bar["ts_close"])
        if price is None:
            raise ValueError(
                f"Expected the signal frame's {column} on the entry's bar closing at {at}, got null."
            )
        if price % self._tick:
            raise ValueError(
                f"Expected {column} on the instrument's tick of {price_text(self._tick)}, got "
                f"{price_text(price)} at {at}."
            )
        return AtPrice(price=price)

    def _require_price_columns(self, signals: pl.DataFrame) -> None:
        at_columns = {
            "stop_price": ("a stop", isinstance(self._execution.stop, ColumnStop)),
            "target_price": ("a target", self._target_ticks is None),
        }
        for column, (rule, at_column) in at_columns.items():
            if at_column and column not in signals.columns:
                raise ValueError(
                    f"Expected the signal frame's {column} for {rule} at the column, got no such "
                    "column."
                )


def _target_ticks(execution: Execution) -> int | None:
    """The target's distance from the fill in ticks, its own or its R multiple of the stop's;
    none for a target at the signal frame's `target_price`."""
    (target,) = execution.targets
    price, stop = target.price, execution.stop
    if isinstance(price, TicksTarget):
        return price.ticks
    if isinstance(price, RMultipleTarget) and isinstance(stop, TicksStop):
        return int(_exact(price.multiple) * stop.ticks)
    return None


def _flat_by_instants(
    spec: StrategySpec, signals: pl.DataFrame, sessions: SessionTable | None
) -> dict[date, int]:
    time = spec.execution.time
    if time is None or time.flat_by is None:
        return {}
    if sessions is None:
        raise ValueError(
            f"Expected a session calendar for the flat-by time {time.flat_by}, got an instrument "
            "without one."
        )
    trade_dates = signals.get_column("trade_date").to_list()
    timeframe = Timeframe.parse(spec.timeframe)
    return flat_by_instants(trade_dates, time.flat_by, time.tz, sessions, timeframe)


def _wakes(bar: Mapping[str, Any]) -> bool:
    """Whether an entry may be placed on `bar`: without a `wake` column, on every bar."""
    return "wake" not in bar or bool(bar["wake"])


def _require_stop_on_the_losing_side(stop: AtPrice, target: AtPrice, side: Side, at: int) -> None:
    if (target.price - stop.price) * side.sign() > 0:
        return
    below = "below" if side is Side.BUY else "above"
    raise ValueError(
        f"Expected the stop_price {below} the target_price of a {side} entry on the bar closing at "
        f"{utc_text(at)}, got {price_text(stop.price)} and {price_text(target.price)}."
    )
