"""Orders: those of a fill scenario, market, stop-market, and limit orders placed at decision
instants, with OCO groups and brackets, and the position held when the tape starts
(`docs/spec/fill-semantics.md`, F-ACT-01, F-OCO-01, and F-OCO-02); and the orders the
reference engine holds while it runs, in its `Book` (step 2.2)."""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, model_validator

from fefat.market.schema import FrozenModel
from fefat.reference.units import Instant, Price, Quantity, price_text

if TYPE_CHECKING:
    from fefat.reference.exit_plan import ExitPlan, LivePlan

OrderId = Annotated[int, Field(ge=1)]


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

    def better(self, first: int, second: int) -> int:
        """The price further in the favour of a position this side opened: the higher for a
        long, the lower for a short."""
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

    def exit_plan(self) -> "ExitPlan":
        """The bracket as an exit plan of one stop and one target for the whole entry, at the
        scenario's prices and under its ids (F-PLN-01)."""
        from fefat.reference.exit_plan import AtPrice, ExitPlan, PlannedLeg

        stop = PlannedLeg(AtPrice(self.stop.price), order_id=self.stop.id)
        return ExitPlan(stop, (PlannedLeg(AtPrice(self.target.price), order_id=self.target.id),))


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
    """What an order does for a position, which its fill records (F-TAG-01): open it, protect it
    (an exit plan's stop), take its profit (target 1 to 3), close it at the market, for the
    strategy's own reason (`exit`) or an execution template's exit reason (§20), or carry it
    across a roll, a leg of the roll for its reason (F-ROL-02)."""

    ENTRY = "entry"
    STOP = "stop"
    TARGET_1 = "target_1"
    TARGET_2 = "target_2"
    TARGET_3 = "target_3"
    EXIT = "exit"
    FLAT_BY = "flat_by"
    NO_OVERNIGHT = "no_overnight"
    NO_WEEKEND = "no_weekend"
    MAX_BARS = "max_bars"
    MAX_MINUTES = "max_minutes"
    OPPOSITE_SIGNAL = "opposite_signal"
    SIGNAL_EXIT = "signal_exit"
    ROLL_VOLUME = "roll_volume"
    ROLL_OPEN_INTEREST = "roll_open_interest"
    ROLL_CALENDAR = "roll_calendar"
    ROLL_EXPIRY = "roll_expiry"


EXIT_ROLES = frozenset(
    {
        OrderRole.EXIT,
        OrderRole.FLAT_BY,
        OrderRole.NO_OVERNIGHT,
        OrderRole.NO_WEEKEND,
        OrderRole.MAX_BARS,
        OrderRole.MAX_MINUTES,
        OrderRole.OPPOSITE_SIGNAL,
        OrderRole.SIGNAL_EXIT,
    }
)
"""The roles of a market order that closes the position on the strategy's word."""

ROLL_ROLES = frozenset(
    {
        OrderRole.ROLL_VOLUME,
        OrderRole.ROLL_OPEN_INTEREST,
        OrderRole.ROLL_CALENDAR,
        OrderRole.ROLL_EXPIRY,
    }
)
"""The roles of a roll's legs, which carry a position from one contract to the next (F-ROL-02)."""


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


@dataclass(slots=True)
class WorkingOrder:
    """An order the engine holds from its placement to its fill or cancellation. `price` is a
    stop's or a limit's, in 1e-9 units; `activation` the instant from which it can fill; and
    `seen_after` its place in the run's timeline after which it sees records: the decision
    that placed it, or the record that filled its entry. `rested` says whether it has seen a
    price without filling (F-LMT-04). An entry carries the exit plan its fill places, and a leg
    of that plan names its entry (F-PLN-01)."""

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
    plan: "ExitPlan | None" = None
    leg_of: int | None = None
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


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """A trade that closed (`docs/spec/fill-semantics.md` §20): the instant of the fill that left
    the position flat, and what its fills moved the cash by, less their fees, in micro-units, a
    loss below zero."""

    closed_at: int
    pnl: int


@dataclass(slots=True)
class Book:
    """What the engine holds while it runs: the live orders, the position in lots (positive
    long, negative short), the mark (F-MRK-01), none before the first tradeable price, the next
    id it gives an order of its own, the exit plans of the entries that have filled, by the
    entry's id, while a leg of theirs is live (F-PLN-01), the instant of the fill that opened
    the position, none when flat or for a position held when the tape starts (F-TIM-02), the
    cash in micro-units, what the fills of the trade still open moved it by, and the trades
    closed so far (F-LIM-02)."""

    orders: list[WorkingOrder] = field(default_factory=list)
    position: int = 0
    mark: int | None = None
    next_id: int = 1
    plans: "dict[int, LivePlan]" = field(default_factory=dict)
    opened_at: int | None = None
    cash: int = 0
    trade_cash: int = 0
    closed_trades: list[ClosedTrade] = field(default_factory=list)

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
        """`order` filled or cancelled: it leaves the book, and its plan with its last leg."""
        order.state = state
        self.orders.remove(order)
        entry = order.leg_of
        if entry is not None and not any(other.leg_of == entry for other in self.orders):
            self.plans.pop(entry, None)

    def take(self, lots: int, ts: int) -> None:
        """A fill of `lots`, positive bought, at `ts`: the position moves by them, and a fill that
        opens a position, from flat or by reversing one, sets `opened_at`."""
        before = self.position
        self.position += lots
        if self.position == 0:
            self.opened_at = None
        elif before * self.position <= 0:
            self.opened_at = ts

    def booked(self, cash: int, ts: int, flat_after: bool) -> None:
        """A fill booked at `ts`, its value and fee moving the cash by `cash`, and the trade it
        belongs to with it: the fill that leaves the position flat closes the trade (§20)."""
        self.cash += cash
        self.trade_cash += cash
        if flat_after:
            self.closed_trades.append(ClosedTrade(closed_at=ts, pnl=self.trade_cash))
            self.trade_cash = 0

    def live_order(self, order_id: int | None) -> WorkingOrder | None:
        """The live order `order_id`, if there is one."""
        return next((order for order in self.orders if order.id == order_id), None)

    def plans_in_order(self) -> list["LivePlan"]:
        """The live plans, by their entries' ids."""
        return [self.plans[entry] for entry in sorted(self.plans)]

    def copied(self) -> "Book":
        """A copy to replay a bar on (F-BAR-05), its orders and its plans copied, and the
        rules of its plans, which are frozen, shared, so that the replay leaves this book as it
        was."""
        plans = {entry: plan.copied() for entry, plan in self.plans.items()}
        orders = [replace(order) for order in self.orders]
        copied = Book(orders, self.position, self.mark, self.next_id, plans, self.opened_at)
        copied.cash, copied.trade_cash = self.cash, self.trade_cash
        return copied

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id - 1
