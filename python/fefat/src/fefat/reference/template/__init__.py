"""The execution template in the reference engine (steps 2.3 and 2.8, D-53): `TemplateStrategy`
runs a `StrategySpec` over its signal frame as an `on_bar` strategy (`fefat.reference.strategy`),
by the rules of `docs/spec/fill-semantics.md` §20 to §28, so that the Rust engine has an oracle
for templates too. An entry carries its exit plan (`fefat.reference.template.exits`), which the
engine works on every record (`fefat.reference.exit_plan`).

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
from fefat.reference.orders import OrderRole, Side
from fefat.reference.strategy import DecisionContext
from fefat.reference.template.exits import exit_plan_of
from fefat.reference.time_rules import flat_by_instants
from fefat.reference.units import InstrumentParameters, lots_of
from fefat.strategy.exits import ColumnStop, ColumnTarget, Limits, TimeRules
from fefat.strategy.signal_frame import require_one_entry_per_bar, validated_signal_frame
from fefat.strategy.spec import (
    Execution,
    FixedSize,
    MarketEntry,
    OppositeSignal,
    StrategySpec,
)

_SUBSET = "a market entry, any exit plan, signal exits, flat-by, and a fixed size"


def basic_subset_refusals(spec: StrategySpec) -> list[str]:
    """What `spec` holds beyond what the reference engine runs so far, in words: nothing when
    it runs all of it."""
    execution = spec.execution
    limits = [] if execution.limits == Limits() else ["entry limits"]
    return [*_entry_refusals(execution), *_time_refusals(execution.time), *limits]


def _entry_refusals(execution: Execution) -> list[str]:
    refusals = []
    if not isinstance(execution.entry, MarketEntry):
        refusals.append(f"an entry of kind {execution.entry.kind}")
    if execution.on_opposite_signal is not OppositeSignal.IGNORE:
        refusals.append(f"on_opposite_signal {execution.on_opposite_signal}")
    if not isinstance(execution.sizing, FixedSize):
        refusals.append(f"sizing of kind {execution.sizing.kind}")
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
    """A `StrategySpec` as an `on_bar` strategy over its signal frame, whose rows are the
    decisions (`decisions_of`). At each signal close, in this order (F-ENT-01): the exit plans'
    turn at the decision (F-PLN-04); nothing more while a market order is on its way out of the
    position or into it, its own exit or a stop triggered on TBBO (F-STP-02); from the trade
    date's flat-by time, the position is closed and no entry placed; `long_exit` while long or
    `short_exit` while short closes the position, with signal exits on; with a position or
    working orders, nothing more, an opposite signal being ignored; on a bar whose `wake` is
    false, no entry; and otherwise an entry signal enters at the market, its exit plan placed
    when it fills (F-PLN-01)."""

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
        self._require_price_columns(signals)
        self._flat_by = flat_by_instants_for(spec, signals, sessions)

    def on_bar(self, bar: Mapping[str, Any], context: DecisionContext) -> None:
        """The decision at one signal close, `bar` the signal frame's row (class docstring)."""
        context.update_exit_plans(bar)
        if context.is_exiting() or context.is_entering():
            return
        if self._past_flat_by(bar):
            if context.position != 0 or context.has_working_orders():
                context.flatten(OrderRole.FLAT_BY)
            return
        if self._signals_exit(bar, context.position):
            context.flatten(OrderRole.SIGNAL_EXIT)
            return
        if context.position != 0 or context.has_working_orders() or not _wakes(bar):
            return
        if bar["long_entry"] or bar["short_entry"]:
            side = Side.BUY if bar["long_entry"] else Side.SELL
            plan = exit_plan_of(self._execution, bar, side, self._tick)
            context.market(side, self._lots_at(bar), plan)

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

    def _require_price_columns(self, signals: pl.DataFrame) -> None:
        targets = self._execution.targets
        at_columns = {
            "stop_price": ("a stop", isinstance(self._execution.stop, ColumnStop)),
            "target_price": (
                "a target",
                any(isinstance(target.price, ColumnTarget) for target in targets),
            ),
        }
        for column, (rule, at_column) in at_columns.items():
            if at_column and column not in signals.columns:
                raise ValueError(
                    f"Expected the signal frame's {column} for {rule} at the column, got no such "
                    "column."
                )


def flat_by_instants_for(
    spec: StrategySpec, signals: pl.DataFrame, sessions: SessionTable | None
) -> dict[date, int]:
    """The instant of `spec`'s flat-by time on each trade date of `signals`, from the session
    table (`fefat.reference.time_rules`); none without a flat-by time. `fefat-cli run` reads
    the same instants (`fefat.reference.rust_batch`)."""
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
