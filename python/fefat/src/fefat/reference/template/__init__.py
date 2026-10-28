"""The execution template in the reference engine (steps 2.3 and 2.8, D-53): `TemplateStrategy`
runs a `StrategySpec` over its signal frame as an `on_bar` strategy (`fefat.reference.strategy`),
by the rules of `docs/spec/fill-semantics.md` §20 to §28, so that the Rust engine has an oracle
for templates too. An entry carries its exit plan (`fefat.reference.template.exits`), which the
engine works on every record (`fefat.reference.exit_plan`); the time rules read the columns
`fefat.reference.time_rules` adds to the frame; and the entries, limits, and sizes are those of
`entries`, `limits`, and `sizing`.

    template = TemplateStrategy(strategy.to_spec(), signals, parameters, sessions)
    engine.run(tape, decisions_of(signals), template.on_bar)
"""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from decimal import Decimal
from itertools import pairwise
from typing import Any

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.reference.exit_plan import ExitPlan
from fefat.reference.orders import OrderKind, OrderRole, Side
from fefat.reference.strategy import DecisionContext, Entry
from fefat.reference.template.entries import f_ent_01, f_ent_02, f_ent_03, f_ent_04
from fefat.reference.template.exits import exit_plan_of
from fefat.reference.template.limits import EntryLimits, f_lim_04
from fefat.reference.template.sizing import EntryPricing, NoEntry, computed_lots, f_siz_01
from fefat.reference.time_rules import f_tim_02, with_time_rules
from fefat.reference.units import InstrumentParameters, lots_of
from fefat.strategy.exits import ColumnStop, ColumnTarget, ColumnTrail
from fefat.strategy.signal_frame import require_one_entry_per_bar, validated_signal_frame
from fefat.strategy.spec import (
    FixedSize,
    LimitEntryAtColumn,
    MarketEntry,
    OppositeSignal,
    RiskPercentSize,
    StopEntryAtColumn,
    StrategySpec,
)


class TemplateStrategy:
    """A `StrategySpec` as an `on_bar` strategy over its signal frame, whose rows are the
    decisions (`decisions_of`). At each signal close, in this order (F-ENT-01): the trades closed
    since the last decision are counted (F-LIM-02), the exit plans take their turn (F-PLN-04), and
    the entries whose time to live has ended are cancelled (F-ENT-03); nothing more while a market
    order is on its way out of the position or into it, its own exit or a stop triggered on TBBO
    (F-STP-02); from the trade date's flat-by time, and from the last signal close before a stop of
    trading with no overnight or before a weekend with no weekend, the position is closed, the
    working orders cancelled, and no entry placed (F-TIM-01, F-TIM-03); a position held max_bars
    decisions or max_minutes is closed (F-TIM-02); an entry signal against the position closes or
    reverses it as `on_opposite_signal` says, and with signal exits on `long_exit` closes a long
    and `short_exit` a short (F-ENT-04); and flat with nothing working, on a row whose `wake` is
    true, inside the entry windows (F-TIM-04), and that the limits allow (§27), an entry signal
    enters (F-ENT-01, F-ENT-02), its size worked out (§28) and its exit plan placed when it fills
    (F-PLN-01)."""

    def __init__(
        self,
        spec: StrategySpec,
        signals: pl.DataFrame,
        instrument: InstrumentParameters,
        sessions: SessionTable | None,
    ) -> None:
        execution = spec.execution
        validated_signal_frame(signals)
        if isinstance(execution.entry, MarketEntry):
            require_one_entry_per_bar(signals)
        self._execution = execution
        self._instrument = instrument
        sizing = execution.sizing
        units = Decimal(repr(sizing.units)) if isinstance(sizing, FixedSize) else None
        self._fixed_lots = None if units is None else lots_of(units, instrument.lot_step)
        self._require_columns(signals)
        ordered = signals.sort("ts_close")
        timed = with_time_rules(spec, ordered, sessions)
        self._timed = {row["ts_close"]: row for row in timed.iter_rows(named=True)}
        self._closes = timed.get_column("ts_close").to_list()
        rows = list(ordered.iter_rows(named=True))
        self._before = {row["ts_close"]: before for before, row in pairwise(rows)}
        self._limits = EntryLimits(execution.limits)

    def on_bar(self, bar: Mapping[str, Any], context: DecisionContext) -> None:
        """The decision at one signal close, `bar` the signal frame's row (class docstring)."""
        now = bar["ts_close"]
        decision = bisect_left(self._closes, now)
        closed = context.closed_trades(self._limits.counted)
        self._limits.count(closed, bar["trade_date"], decision)
        context.update_exit_plans(bar)
        expired = f_ent_03(self._execution.entry, self._closes, now)
        if expired is not None:
            context.cancel_entries_placed_by(expired)
        if context.is_exiting() or context.is_entering():
            return
        timed = self._timed[now]
        stop_exit = _stop_exit(timed)
        if stop_exit is not None:
            if context.position != 0 or context.has_working_orders():
                context.flatten(stop_exit)
            return
        held_exit = self._held_exit(now, context)
        if held_exit is not None:
            context.flatten(held_exit)
            return
        self._signals(f_lim_04(self._execution.limits, bar, self._before.get(now)), context)

    def _signals(self, bar: Mapping[str, Any], context: DecisionContext) -> None:
        """The row's signals, as they count (F-LIM-04): an opposite signal or a signal exit
        (F-ENT-04), then an entry where the row and the limits allow one."""
        decision = bisect_left(self._closes, bar["ts_close"])
        timed = self._timed[bar["ts_close"]]
        allowed = _wakes(bar) and timed.get("in_window", True)
        allowed = allowed and self._limits.allow(bar, decision)
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
        """Enters on `sides`, each order with its exit plan and its size (F-ENT-02, F-PLN-01,
        §28); an offset entry with no mark yet places nothing, nor does an entry whose size has
        no lots, and the log says why."""
        tick, entries = self._instrument.tick, []
        for side in sides:
            order = f_ent_02(self._execution.entry, side, bar, context.mark, tick)
            if order is None:
                context.skipped("no mark to count the entry's offset from", "F-ENT-02")
                return
            plan = exit_plan_of(self._execution, bar, side, tick)
            lots = self._lots(bar, context, side, order, plan)
            if isinstance(lots, NoEntry):
                context.skipped(lots.why, lots.rule)
                continue
            entries.append(Entry(side, *order, lots, plan))
        if entries:
            context.enter(entries, reversing)
            self._limits.entered()

    def _lots(
        self,
        bar: Mapping[str, Any],
        context: DecisionContext,
        side: Side,
        order: tuple[OrderKind, int | None],
        plan: ExitPlan,
    ) -> int | NoEntry:
        """An entry's size (§28): a fixed size times `size_mult`, or a computed one priced at the
        order's own price, or for a market order at the mark."""
        if self._fixed_lots is not None:
            return f_siz_01(self._fixed_lots, bar)
        kind, price = order
        priced_at = context.mark if kind is OrderKind.MARKET else price
        sizing = self._execution.sizing
        equity = context.equity if isinstance(sizing, RiskPercentSize) else 0
        pricing = EntryPricing(side, priced_at, plan, equity)
        return computed_lots(sizing, pricing, bar, self._instrument)

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

    def _require_columns(self, signals: pl.DataFrame) -> None:
        """Each column a rule reads, which a frame without it would leave the rule without: a
        trailing stop by the column would never move, and a blackout would never hold."""
        execution = self._execution
        trailing, blackout = execution.trailing, execution.limits.blackout
        needed = {
            "entry_price": (
                "an entry at the column",
                isinstance(execution.entry, LimitEntryAtColumn | StopEntryAtColumn),
            ),
            "stop_price": ("a stop at the column", isinstance(execution.stop, ColumnStop)),
            "target_price": (
                "a target at the column",
                any(isinstance(target.price, ColumnTarget) for target in execution.targets),
            ),
            "trail_ref": (
                "a trailing stop by the column",
                trailing is not None and isinstance(trailing.by, ColumnTrail),
            ),
        }
        if blackout is not None:
            needed[blackout] = ("the blackout", True)
        for column, (rule, needs) in needed.items():
            if needs and column not in signals.columns:
                raise ValueError(
                    f"Expected the signal frame's {column} for {rule}, got no such column."
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
