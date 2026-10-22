"""The orders of a fill scenario: market, stop-market, and limit orders placed at decision
instants, with OCO groups and brackets, and the position held when the tape starts
(`docs/spec/fill-semantics.md`, F-ACT-01, F-OCO-01, and F-OCO-02)."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fefat.market.schema import FrozenModel
from fefat.reference.units import Instant, Price, Quantity, price_text

OrderId = Annotated[int, Field(ge=1)]


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


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
