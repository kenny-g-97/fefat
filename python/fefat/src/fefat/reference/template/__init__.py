"""The execution template in the reference engine (steps 2.3 and 2.8, D-53): `TemplateStrategy`
runs a `StrategySpec` over its signal frame as an `on_bar` strategy (`fefat.reference.strategy`),
by the rules of `docs/spec/fill-semantics.md` §20 to §28, so that the Rust engine has an oracle
for templates too. An entry carries its exit plan (`fefat.reference.template.exits`), which the
engine works on every record (`fefat.reference.exit_plan`), and the time rules read the columns
`fefat.reference.time_rules` adds to the frame.

    template = TemplateStrategy(strategy.to_spec(), signals, parameters, sessions)
    engine.run(tape, decisions_of(signals), template.on_bar)
"""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import polars as pl

from fefat.market.calendar import SessionTable, utc_text
from fefat.reference.orders import OrderRole, Side
from fefat.reference.strategy import DecisionContext, Entry
from fefat.reference.template.entries import f_ent_01, f_ent_02, f_ent_03, f_ent_04
from fefat.reference.template.exits import exit_plan_of
from fefat.reference.time_rules import f_tim_02, with_time_rules
from fefat.reference.units import InstrumentParameters, lots_of
from fefat.strategy.exits import ColumnStop, ColumnTarget, Limits
from fefat.strategy.signal_frame import require_one_entry_per_bar, validated_signal_frame
from fefat.strategy.spec import (
    Execution,
    FixedSize,
    LimitEntryAtColumn,
    MarketEntry,
    OppositeSignal,
    StopEntryAtColumn,
    StrategySpec,
)

_SUBSET = "any entry, exit plan, and time rule, and a fixed size"


def basic_subset_refusals(spec: StrategySpec) -> list[str]:
    """What `spec` holds beyond what the reference engine runs so far, in words: nothing when
    it runs all of it."""
    execution = spec.execution
    limits = [] if execution.limits == Limits() else ["entry limits"]
    return [*_entry_refusals(execution), *limits]


def _entry_refusals(execution: Execution) -> list[str]:
    if not isinstance(execution.sizing, FixedSize):
        return [f"sizing of kind {execution.sizing.kind}"]
    return []


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
    date's flat-by time, and from the last signal close before a stop of trading with no
    overnight or before a weekend with no weekend, the position is closed, the working orders
    cancelled, and no entry placed (F-TIM-01, F-TIM-03); a position held max_bars decisions or
    max_minutes is closed (F-TIM-02); `long_exit` while long or `short_exit` while short closes
    the position, with signal exits on; with a position or working orders, nothing more, an
    opposite signal being ignored; on a bar whose `wake` is false, or outside the entry windows
    (F-TIM-04), no entry; and otherwise an entry signal enters at the market, its exit plan
    placed when it fills (F-PLN-01)."""

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
        if isinstance(execution.entry, MarketEntry):
            require_one_entry_per_bar(signals)
        self._execution = execution
        self._tick = instrument.tick
        self._lots = lots_of(_exact(sizing.units), instrument.lot_step)
        self._require_price_columns(signals)
        timed = with_time_rules(spec, signals.sort("ts_close"), sessions)
        self._timed = {row["ts_close"]: row for row in timed.iter_rows(named=True)}
        self._closes = timed.get_column("ts_close").to_list()

    def on_bar(self, bar: Mapping[str, Any], context: DecisionContext) -> None:
        """The decision at one signal close, `bar` the signal frame's row (class docstring)."""
        context.update_exit_plans(bar)
        expired = f_ent_03(self._execution.entry, self._closes, bar["ts_close"])
        if expired is not None:
            context.cancel_entries_placed_by(expired)
        if context.is_exiting() or context.is_entering():
            return
        timed = self._timed[bar["ts_close"]]
        stop_exit = _stop_exit(timed)
        if stop_exit is not None:
            if context.position != 0 or context.has_working_orders():
                context.flatten(stop_exit)
            return
        held_exit = self._held_exit(bar["ts_close"], context)
        if held_exit is not None:
            context.flatten(held_exit)
            return
        allowed = _wakes(bar) and timed.get("in_window", True)
        reverse_to = f_ent_04(self._execution.on_opposite_signal, bar, context.position)
        if reverse_to is not None:
            context.flatten(OrderRole.OPPOSITE_SIGNAL)
            if self._execution.on_opposite_signal is OppositeSignal.REVERSE and allowed:
                self._enter(bar, context, [reverse_to], reversing=True)
            return
        if self._signals_exit(bar, context.position):
            context.flatten(OrderRole.SIGNAL_EXIT)
            return
        if context.position == 0 and not context.has_working_orders() and allowed:
            self._enter(bar, context, f_ent_01(bar))

    def _enter(
        self,
        bar: Mapping[str, Any],
        context: DecisionContext,
        sides: list[Side],
        reversing: bool = False,
    ) -> None:
        """Enters on `sides`, each order with its exit plan (F-ENT-02, F-PLN-01); an offset entry
        with no mark yet places nothing, and the log says why."""
        entries = []
        for side in sides:
            order = f_ent_02(self._execution.entry, side, bar, context.mark, self._tick)
            if order is None:
                context.skipped("no mark to count the entry's offset from", "F-ENT-02")
                return
            plan = exit_plan_of(self._execution, bar, side, self._tick)
            entries.append(Entry(side, *order, self._lots_at(bar), plan))
        if entries:
            context.enter(entries, reversing)

    def _held_exit(self, now: int, context: DecisionContext) -> OrderRole | None:
        """Max bars or max minutes of an open position (F-TIM-02), counting the decisions from
        its entry's fill to `now`."""
        opened_at = context.opened_at
        if context.position == 0 or opened_at is None:
            return None
        decisions = bisect_right(self._closes, now) - bisect_left(self._closes, opened_at)
        return f_tim_02(self._execution.time, opened_at, now, decisions)

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
        entry = self._execution.entry
        at_columns = {
            "entry_price": (
                "an entry",
                isinstance(entry, LimitEntryAtColumn | StopEntryAtColumn),
            ),
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


def _stop_exit(timed: Mapping[str, Any]) -> OrderRole | None:
    """The time exit that closes the position and places no entry on a row, the first that
    applies: the flat-by time, then a stop of trading, then a weekend (F-TIM-01, F-TIM-03); each
    reads its column of `fefat.reference.time_rules`, there only with its rule."""
    if "flat_by" in timed and timed["ts_close"] >= timed["flat_by"]:
        return OrderRole.FLAT_BY
    if timed.get("session_end"):
        return OrderRole.NO_OVERNIGHT
    if timed.get("week_end"):
        return OrderRole.NO_WEEKEND
    return None


def _wakes(bar: Mapping[str, Any]) -> bool:
    """Whether an entry may be placed on `bar`: without a `wake` column, on every bar."""
    return "wake" not in bar or bool(bar["wake"])
