"""The strategy protocol of the reference engine (step 2.2): a callable `on_bar(bar, context)`
that the engine calls at each decision, a bar close (F-ACT-01), with the bar's row and a
`DecisionContext` through which it places orders, such as a market order with a bracket, and
closes its position. The signal strategies of step 2.3 give the engine a specification
instead.

    def on_bar(bar, context):
        if bar["cross_up"] and context.position == 0 and not context.has_working_orders():
            context.market(Side.BUY, 1, TicksBracket(stop_ticks=12, target_ticks=24))
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import polars as pl

from fefat.reference.event_log import EventKind, EventLog
from fefat.reference.orders import (
    Book,
    Bracket,
    Order,
    OrderKind,
    OrderRole,
    OrderState,
    PricedOrder,
    Side,
    TicksBracket,
    WorkingOrder,
)
from fefat.reference.units import instant_text, lots_of


@dataclass(frozen=True, slots=True)
class Decision:
    """A decision at the instant `ts`, a bar's close, with that bar's row for `on_bar`."""

    ts: int
    bar: Mapping[str, Any]


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
        lot_step: Decimal,
        log: EventLog,
    ) -> None:
        self._book = book
        self.now = now
        self._timeline_position = timeline_position
        self._latency = latency
        self._lot_step = lot_step
        self._log = log

    @property
    def position(self) -> int:
        return self._book.position

    def has_working_orders(self) -> bool:
        return bool(self._book.live())

    def market(self, side: Side, lots: int, bracket: TicksBracket | None = None) -> int:
        """Enters with a market order for `lots`, with a bracket placed when it fills
        (F-OCO-02), and returns its id. A strategy holds one position at a time, so it enters
        flat and with nothing working; `flatten` closes the position."""
        if lots < 1:
            raise ValueError(f"Expected a whole number of lots above zero, got {lots}.")
        working = len(self._book.live())
        if self._book.position != 0 or working:
            raise ValueError(
                "Expected an entry while flat with no working orders (one position per strategy), "
                f"got {self._book.position} lots and {working} working orders at "
                f"{instant_text(self.now)}; close the position with flatten()."
            )
        order_id = self._book.new_id()
        self._place(order_id, side, OrderKind.MARKET, None, lots, bracket=bracket)
        return order_id

    def flatten(self) -> None:
        """Cancels every working order and, with a position open, places a market order that
        closes it."""
        for order in self._book.live():
            self._book.close(order, OrderState.CANCELLED)
            cancelled = f"order {order.id}: cancelled by the strategy"
            self._log.note(self.now, EventKind.CANCELLED, cancelled, order.id)
        if self._book.position != 0:
            side = Side.SELL if self._book.position > 0 else Side.BUY
            lots, order_id = abs(self._book.position), self._book.new_id()
            self._place(order_id, side, OrderKind.MARKET, None, lots, role=OrderRole.EXIT)

    def place(self, order: Order) -> None:
        """Places a scenario's order under its own id (`fefat.reference.orders`)."""
        price = order.price if isinstance(order, PricedOrder) else None
        lots, kind = lots_of(order.quantity, self._lot_step), OrderKind(order.kind)
        self._place(order.id, order.side, kind, price, lots, oco=order.oco, bracket=order.bracket)

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
        bracket: Bracket | TicksBracket | None = None,
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
            bracket=bracket,
        )
        self._book.orders.append(order)
        placed = f"order {order_id}: {order.described()}, active from {instant_text(activation)}"
        self._log.note(self.now, EventKind.PLACED, placed, order_id, "F-ACT-01")


OnBar = Callable[[Mapping[str, Any], DecisionContext], None]
"""A strategy: called at each decision with the bar's row and the decision's context."""
