"""The strategy protocol of the reference engine (step 2.2): a callable `on_bar(bar, context)`
that the engine calls at each decision, a bar close (F-ACT-01), with the bar's row and a
`DecisionContext` through which it places orders, such as a market order with a bracket, and
closes its position. A signal strategy's specification runs through the same protocol
(`fefat.reference.template`, step 2.3).

    def on_bar(bar, context):
        if bar["cross_up"] and context.position == 0 and not context.has_working_orders():
            context.market(Side.BUY, 1, ExitPlan.in_ticks(stop_ticks=12, target_ticks=24))
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from fefat.reference.event_log import EventKind, EventLog
from fefat.reference.exit_plan import ExitPlan
from fefat.reference.orders import (
    EXIT_ROLES,
    Book,
    Order,
    OrderKind,
    OrderRole,
    OrderState,
    PricedOrder,
    Side,
    WorkingOrder,
)
from fefat.reference.units import InstrumentParameters, instant_text, lots_of


@dataclass(frozen=True, slots=True)
class Decision:
    """A decision at the instant `ts`, a bar's close, with that bar's row for `on_bar`."""

    ts: int
    bar: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Entry:
    """An entry a decision places: its side, its class and price, a limit's or a stop's, its
    lots, and the exit plan its fill places (F-PLN-01)."""

    side: Side
    kind: OrderKind
    price: int | None
    lots: int
    plan: ExitPlan | None = None


def decisions_of(frame: pl.DataFrame) -> tuple[Decision, ...]:
    """A decision at the close of each bar of `frame`, a frame `load` returned with any columns
    a notebook added, in the order of their closes."""
    return tuple(
        Decision(ts=row["ts_close"], bar=row)
        for row in frame.sort("ts_close").iter_rows(named=True)
    )


class DecisionContext:
    """What a strategy sees and does at one decision: the instant, its position in lots, and
    whether it has working orders; and the orders it places, each active the run's latency
    after the decision (F-ACT-01) and seeing only the records after it."""

    def __init__(
        self,
        book: Book,
        now: int,
        timeline_position: int,
        latency: int,
        instrument: InstrumentParameters,
        log: EventLog,
    ) -> None:
        self._book = book
        self.now = now
        self._timeline_position = timeline_position
        self._latency = latency
        self._instrument = instrument
        self._log = log

    @property
    def position(self) -> int:
        return self._book.position

    @property
    def mark(self) -> int | None:
        """The mark, the last tradeable price before the decision (F-MRK-01), none before the
        first."""
        return self._book.mark

    @property
    def opened_at(self) -> int | None:
        """The instant of the fill that opened the position, none when flat or for a position
        held when the tape starts (F-TIM-02)."""
        return self._book.opened_at

    def has_working_orders(self) -> bool:
        return bool(self._book.live())

    def is_exiting(self) -> bool:
        """Whether a market order is on its way out of the position: one `flatten` placed, or a
        stop triggered on TBBO, a market order from its trigger that no decision cancels
        (F-STP-02)."""
        return any(
            order.role in EXIT_ROLES
            or (order.state is OrderState.TRIGGERED and order.role is not OrderRole.ENTRY)
            for order in self._book.live()
        )

    def is_entering(self) -> bool:
        """Whether an entry stop triggered on TBBO is on its way into a position, a market order
        from its trigger that no decision cancels (F-STP-02, F-ENT-03)."""
        return any(
            order.state is OrderState.TRIGGERED and order.role is OrderRole.ENTRY
            for order in self._book.live()
        )

    def update_exit_plans(self, row: Mapping[str, Any]) -> None:
        """The decision's turn of each live exit plan (F-PLN-04): a trailing stop by a feature
        takes the row's distance, and one that moves at decisions moves (F-TRL-02, F-TRL-04)."""
        tick, mark = self._instrument.tick, self._book.mark
        for live in self._book.plans_in_order():
            for move in live.at_decision(self._book, row, mark, tick):
                self._log.moved(self.now, move.order, move.before, move.after, move.rule)

    def market(self, side: Side, lots: int, plan: ExitPlan | None = None) -> int:
        """Enters with a market order for `lots`, with an exit plan placed when it fills
        (F-OCO-02, F-PLN-01), and returns its id. A strategy holds one position at a time, so it
        enters flat and with nothing working; `flatten` closes the position."""
        return self.enter([Entry(side, OrderKind.MARKET, None, lots, plan)])[0]

    def enter(self, entries: Sequence[Entry], reversing: bool = False) -> list[int]:
        """Places `entries`, one entry or a long and short pair, the pair as one OCO group
        (F-ENT-01), and returns their ids. A strategy holds one position at a time, so it enters
        flat with nothing working, or, `reversing`, right after `flatten` placed its exit, whose
        id comes first (F-ENT-04)."""
        for entry in entries:
            if entry.lots < 1:
                raise ValueError(f"Expected a whole number of lots above zero, got {entry.lots}.")
        working = len(self._book.live())
        if not reversing and (self._book.position != 0 or working):
            raise ValueError(
                "Expected an entry while flat with no working orders (one position per strategy), "
                f"got {self._book.position} lots and {working} working orders at "
                f"{instant_text(self.now)}; close the position with flatten()."
            )
        ids = [self._book.new_id() for _ in entries]
        group = f"pair {ids[0]}" if len(ids) > 1 else None
        for order_id, entry in zip(ids, entries, strict=True):
            self._place(
                order_id,
                entry.side,
                entry.kind,
                entry.price,
                entry.lots,
                oco=group,
                plan=entry.plan,
            )
        return ids

    def cancel_entries_placed_by(self, instant: int) -> None:
        """Cancels the live entries placed at or before `instant`, whose time to live has ended
        (F-ENT-03); an entry stop triggered on TBBO, a market order already sent, stays
        (F-STP-02)."""
        for order in self._book.live():
            ended = order.role is OrderRole.ENTRY and order.placed_at <= instant
            if ended and order.state is not OrderState.TRIGGERED:
                self._book.close(order, OrderState.CANCELLED)
                text = f"order {order.id}: its time to live has ended"
                self._log.note(self.now, EventKind.CANCELLED, text, order.id, "F-ENT-03")

    def skipped(self, why: str, rule: str) -> None:
        """Logs an entry signal the strategy could not act on, and why (F-ENT-02, F-SIZ-04)."""
        self._log.skipped(self.now, why, rule)

    def flatten(self, reason: OrderRole = OrderRole.EXIT) -> None:
        """Cancels every working order and, with a position open, places a market order that
        closes it, its role the exit reason (F-TAG-01); nothing while a market order is already
        on its way out of the position (`is_exiting`), and a stop triggered on TBBO stays, since
        no decision cancels it (F-STP-02)."""
        if self.is_exiting():
            return
        for order in self._book.live():
            if order.state is OrderState.TRIGGERED:
                continue
            self._book.close(order, OrderState.CANCELLED)
            cancelled = f"order {order.id}: cancelled by the strategy"
            self._log.note(self.now, EventKind.CANCELLED, cancelled, order.id)
        if self._book.position != 0:
            side = Side.SELL if self._book.position > 0 else Side.BUY
            lots, order_id = abs(self._book.position), self._book.new_id()
            self._place(order_id, side, OrderKind.MARKET, None, lots, role=reason)

    def place(self, order: Order) -> None:
        """Places a scenario's order under its own id (`fefat.reference.orders`), its bracket
        as an exit plan."""
        price = order.price if isinstance(order, PricedOrder) else None
        lots, kind = lots_of(order.quantity, self._instrument.lot_step), OrderKind(order.kind)
        plan = None if order.bracket is None else order.bracket.exit_plan()
        self._place(order.id, order.side, kind, price, lots, oco=order.oco, plan=plan)

    def _place(
        self,
        order_id: int,
        side: Side,
        kind: OrderKind,
        price: int | None,
        lots: int,
        *,
        role: OrderRole = OrderRole.ENTRY,
        oco: str | None = None,
        plan: ExitPlan | None = None,
    ) -> None:
        activation = self.now + self._latency
        order = WorkingOrder(
            id=order_id,
            side=side,
            kind=kind,
            price=price,
            lots=lots,
            role=role,
            placed_at=self.now,
            activation=activation,
            seen_after=self._timeline_position,
            oco=oco,
            plan=plan,
        )
        self._book.orders.append(order)
        placed = f"order {order_id}: {order.described()}, active from {instant_text(activation)}"
        self._log.note(self.now, EventKind.PLACED, placed, order_id, "F-ACT-01")


OnBar = Callable[[Mapping[str, Any], DecisionContext], None]
"""A strategy: called at each decision with the bar's row and the decision's context."""
