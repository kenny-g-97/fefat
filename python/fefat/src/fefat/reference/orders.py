"""Orders: those of a fill scenario, market, stop-market, and limit orders placed at decision
instants, with OCO groups and brackets, and the position held when the tape starts
(`docs/spec/fill-semantics.md`, F-ACT-01, F-OCO-01, and F-OCO-02); and the orders the
reference engine holds while it runs, in its `Book` (step 2.2)."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fefat.market.schema import FrozenModel
from fefat.reference.units import Instant, Price, Quantity, price_text

OrderId = Annotated[int, Field(ge=1)]
BracketLegs = tuple[tuple[int, int], tuple[int, int]]
"""A bracket's stop and target, each as its order id and price."""


class Side(StrEnum):
    """An order's side. The specification writes each rule for a buy, and a sell mirrors it
    (`docs/spec/fill-semantics.md` §1)."""

    BUY = "buy"
    SELL = "sell"

    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY

    def moved(self, price: int, ticks: int, tick: int) -> int:
        """`price` moved by `ticks` against the trader: up for a buy, down for a sell."""
        return price + self.sign() * ticks * tick

    def worse(self, first: int, second: int) -> int:
        """The costlier of two prices: the higher for a buy, the lower for a sell."""
        return max(first, second) if self is Side.BUY else min(first, second)


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class BracketLeg(FrozenModel):
    """One exit of a bracket: the id the scenario gives it and its price."""

    id: OrderId
    price: Price


class Bracket(FrozenModel):
    """The stop and the target placed, as one OCO group, when their entry fills (F-OCO-02)."""

    stop: BracketLeg
    target: BracketLeg

    def legs(self, side: Side, price: int, tick: int, new_id: Callable[[], int]) -> BracketLegs:
        """The ids and prices of the stop and the target, as the scenario gives them."""
        return ((self.stop.id, self.stop.price), (self.target.id, self.target.price))


class ScenarioOrder(FrozenModel):
    """What every order of a scenario states: its id, the decision instant it was placed at
    (it becomes active the latency later, F-ACT-01), its side, its quantity in the
    instrument's units, and optionally its OCO group and a bracket."""

    id: OrderId
    placed_at: Instant
    side: Side
    quantity: Quantity
    oco: str | None = None
    bracket: Bracket | None = None

    @model_validator(mode="after")
    def _bracket_stop_on_the_losing_side(self) -> Self:
        if self.bracket is None:
            return self
        stop, target = self.bracket.stop.price, self.bracket.target.price
        buying = self.side is Side.BUY
        if not (stop < target if buying else stop > target):
            raise ValueError(
                f"Expected order {self.id}'s bracket stop {'below' if buying else 'above'} its "
                f"target, got stop {price_text(stop)} and target {price_text(target)}."
            )
        return self

    def ids(self) -> tuple[int, ...]:
        """This order's id, then its bracket's."""
        if self.bracket is None:
            return (self.id,)
        return (self.id, self.bracket.stop.id, self.bracket.target.id)

    def prices(self) -> tuple[int, ...]:
        """The prices this order names: its bracket's, and its own where its kind has one."""
        if self.bracket is None:
            return ()
        return (self.bracket.stop.price, self.bracket.target.price)


class MarketOrder(ScenarioOrder):
    """An order to buy or sell at the market (F-MKT)."""

    kind: Literal["market"]


class PricedOrder(ScenarioOrder):
    """An order that names its price: a stop or a limit."""

    price: Price

    def prices(self) -> tuple[int, ...]:
        return (self.price, *super().prices())


class StopOrder(PricedOrder):
    """A stop-market order at `price` (F-STP)."""

    kind: Literal["stop"]


class LimitOrder(PricedOrder):
    """A limit order at `price` (F-LMT)."""

    kind: Literal["limit"]


Order = Annotated[MarketOrder | StopOrder | LimitOrder, Field(discriminator="kind")]


def oco_groups(orders: tuple[Order, ...]) -> list[set[int]]:
    """The sets of orders of which one at most may fill (F-OCO-01): each named OCO group, and
    each bracket's stop and target."""
    named: dict[str, set[int]] = {}
    for order in orders:
        if order.oco is not None:
            named.setdefault(order.oco, set()).add(order.id)
    legs = [set(order.ids()[1:]) for order in orders if order.bracket is not None]
    return [*named.values(), *legs]


class OpenPosition(FrozenModel):
    """A position held when the tape starts: its side, quantity, and average entry price."""

    side: PositionSide
    quantity: Quantity
    price: Price


class OrderKind(StrEnum):
    """An order's class (`docs/spec/fill-semantics.md` §2)."""

    MARKET = "market"
    STOP = "stop"
    LIMIT = "limit"


class OrderRole(StrEnum):
    """What an order does for a position: open it, protect it (a bracket's stop), take its
    profit (a bracket's target), or close it when the strategy says so."""

    ENTRY = "entry"
    STOP = "stop"
    TARGET = "target"
    EXIT = "exit"


class OrderState(StrEnum):
    """Where an order stands: placed and waiting for the first record or bar it sees (F-ACT-01,
    F-ACT-02), working, triggered (a stop on TBBO, which fills at the next record's quote,
    F-STP-02), filled, or cancelled."""

    WAITING = "waiting"
    WORKING = "working"
    TRIGGERED = "triggered"
    FILLED = "filled"
    CANCELLED = "cancelled"


LIVE_STATES = frozenset({OrderState.WAITING, OrderState.WORKING, OrderState.TRIGGERED})


class TicksBracket(FrozenModel):
    """A bracket set in ticks from its entry's fill price: the stop `stop_ticks` against the
    position, the target `target_ticks` in its favour (the strategy protocol of step 2.2)."""

    stop_ticks: int = Field(gt=0)
    target_ticks: int = Field(gt=0)

    def legs(self, side: Side, price: int, tick: int, new_id: Callable[[], int]) -> BracketLegs:
        """New ids, and the stop and the target set from the entry's fill `price`, a buy's stop
        below it and its target above."""
        away = side.sign() * tick
        return (new_id(), price - self.stop_ticks * away), (
            new_id(),
            price + self.target_ticks * away,
        )


@dataclass(slots=True)
class WorkingOrder:
    """An order the engine holds from its placement to its fill or cancellation. `price` is a
    stop's or a limit's, in 1e-9 units; `activation` the instant from which it can fill; and
    `seen_after` its place in the run's timeline after which it sees records: the decision
    that placed it, or the record that filled its entry. `rested` says whether it has seen a
    price without filling (F-LMT-04)."""

    id: int
    side: Side
    kind: OrderKind
    price: int | None
    lots: int
    role: OrderRole
    placed_at: int
    activation: int
    seen_after: int
    oco: str | None = None
    bracket: Bracket | TicksBracket | None = None
    state: OrderState = OrderState.WAITING
    rested: bool = False

    def level(self) -> int:
        """The price of a stop or a limit; a market order has none."""
        if self.price is None:
            raise ValueError(f"Expected a stop or a limit, got order {self.id}, a {self.kind}.")
        return self.price

    def described(self) -> str:
        """Such as `sell stop at 4995 x 1`."""
        at = "" if self.price is None else f" at {price_text(self.price)}"
        return f"{self.side} {self.kind}{at} x {self.lots}"

    def bracket_leg(self, kind: OrderKind, leg: tuple[int, int], ts: int, index: int) -> Self:
        """The stop or the target, of `leg`'s id and price, that this entry's fill at `ts`, the
        `index`th event of the run, places: an exit of its lots in the group of its bracket,
        active at once (F-OCO-02)."""
        leg_id, price = leg
        return type(self)(
            id=leg_id,
            side=self.side.opposite(),
            kind=kind,
            price=price,
            lots=self.lots,
            role=OrderRole.STOP if kind is OrderKind.STOP else OrderRole.TARGET,
            placed_at=ts,
            activation=ts,
            seen_after=index,
            oco=f"bracket of {self.id}",
        )


@dataclass(slots=True)
class Book:
    """What the engine holds while it runs: the live orders, the position in lots (positive
    long, negative short), the mark (F-MRK-01), none before the first tradeable price, and the
    next id it gives an order of its own."""

    orders: list[WorkingOrder] = field(default_factory=list)
    position: int = 0
    mark: int | None = None
    next_id: int = 1

    def live(self, *states: OrderState, kind: OrderKind | None = None) -> list[WorkingOrder]:
        """The live orders in one of `states`, all of them without, of `kind` where it is
        named, by id: the lower id first at one instant."""
        wanted = states or LIVE_STATES
        found = [
            order
            for order in self.orders
            if order.state in wanted and (kind is None or order.kind is kind)
        ]
        return sorted(found, key=lambda order: order.id)

    def each(self, state: OrderState, kind: OrderKind | None = None) -> Iterator[WorkingOrder]:
        """The orders in `state`, of `kind` where it is named, by id, each while it still is:
        an order that filled, or that an earlier fill cancelled, is passed over."""
        for order in self.live(state, kind=kind):
            if order.state is state:
                yield order

    def close(self, order: WorkingOrder, state: OrderState) -> None:
        """`order` filled or cancelled: it leaves the book."""
        order.state = state
        self.orders.remove(order)

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id - 1
