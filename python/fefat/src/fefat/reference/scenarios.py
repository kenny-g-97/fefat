"""Fill scenarios: the hand-computable cases that specify how the engines fill orders (D-10).

A scenario is one YAML file in `fixtures/scenarios/`, named by its id (`S-fill-012.yaml`): a
tape (`fefat.reference.tape`), an instrument, the orders placed at given instants, and the
fills, marks, and funding payments the rules of `docs/spec/fill-semantics.md` give, with the
identifiers of the rules it exercises; `fixtures/scenarios/README.md` documents the format.
Its values are held in the units both engines count in (`fefat.reference.units`), so that
their fills compare as integers:

    load_scenario(Path("fixtures/scenarios/S-fill-012.yaml")).expected.fills[0].price
    # 4_990_250_000_000, written "4990.25"
"""

import re
from collections import Counter
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BeforeValidator, Field, ValidationError, model_validator

from fefat.market import instruments
from fefat.market.fees import Fee
from fefat.market.instruments import Instrument
from fefat.market.schema import FrozenModel
from fefat.reference.tape import Fidelity, Tape, TickFidelity, check_tape
from fefat.reference.units import (
    PRICE_DECIMALS,
    Instant,
    Money,
    PositiveDecimal,
    Price,
    Quantity,
    QuotedDecimal,
    price_text,
)

DEFAULT_LATENCY_MS = 100
"""How long after the decision that placed it an order becomes active (F-ACT-01, D-51)."""

OrderId = Annotated[int, Field(ge=1)]
RuleId = Annotated[str, Field(pattern=r"^F-[A-Z]{3}-[0-9]{2}$")]
"""A rule of the fill specification, such as F-STP-03."""

_RULE_DEFINITION = re.compile(r"^\*\*(F-[A-Z]{3}-[0-9]{2})\*\*", re.MULTILINE)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class LimitFill(StrEnum):
    """When a limit fills: once the market trades through its price (F-LMT-01, the default)
    or once it touches it (F-LMT-02)."""

    THROUGH = "through"
    TOUCH = "touch"


class FillFlag(StrEnum):
    """What a fill is flagged with: a bar's fills that depend on the order of its extremes
    (F-BAR-05), or a size above the quote's on TBBO (F-QTY-01)."""

    AMBIGUOUS = "ambiguous"
    SIZE_EXCEEDED = "size_exceeded"


class InlineInstrument(FrozenModel):
    """A product the instrument table lacks, given by its tick size, point value, and lot
    step. It names no calendar, so it trades around the clock: its scenarios hold no breaks."""

    tick_size: PositiveDecimal
    point_value: PositiveDecimal
    lot_step: PositiveDecimal


def _instrument(value: object) -> object:
    """A root's text as the instrument table's version of it."""
    # shortcut: a root's newest version; look it up by the tape's date once a spec changes.
    return instruments.get(value) if isinstance(value, str) else value


ScenarioInstrument = Annotated[Instrument | InlineInstrument, BeforeValidator(_instrument)]


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


class OpenPosition(FrozenModel):
    """A position held when the tape starts: its side, quantity, and average entry price."""

    side: PositionSide
    quantity: Quantity
    price: Price


class FundingRate(FrozenModel):
    """A perpetual's funding rate, paid at `ts` (F-FND-01): "0.0001" is 0.01 %."""

    ts: Instant
    rate: QuotedDecimal


class SlippageTicks(FrozenModel):
    """Ticks by which market and stop-market fills are worse than their reference (F-SLP-01)."""

    market: int = Field(ge=0)
    stop: int = Field(ge=0)


class ScenarioSettings(FrozenModel):
    """The run settings a scenario fills under (F-ACT-01, F-SLP-01, F-LMT-01, F-LMT-02)."""

    latency_ms: int = Field(default=DEFAULT_LATENCY_MS, ge=0)
    slippage_ticks: SlippageTicks
    limit_fill: LimitFill = LimitFill.THROUGH


class ExpectedFill(FrozenModel):
    """A fill the rules give: the order it fills, when, at what price, the rule that priced it
    (F-TAG-01), its flags, and, in a scenario with fees, its fee."""

    order: OrderId
    ts: Instant
    price: Price
    rule: RuleId
    flags: tuple[FillFlag, ...] = ()
    fee: Money | None = None


class ExpectedMark(FrozenModel):
    """The price the open position is marked at once every event at `ts` is done (F-MRK-01)."""

    ts: Instant
    price: Price


class ExpectedFunding(FrozenModel):
    """A funding payment at `ts`, as the change to the trader's cash: positive when received."""

    ts: Instant
    amount: Money


class Expected(FrozenModel):
    """What the rules give on the tape: its fills (none is `fills: []`), marks, and funding."""

    fills: tuple[ExpectedFill, ...]
    marks: tuple[ExpectedMark, ...] = ()
    funding: tuple[ExpectedFunding, ...] = ()


class Scenario(FrozenModel):
    """One fill scenario, as `fixtures/scenarios/README.md` describes it."""

    id: Annotated[str, Field(pattern=r"^S-[a-z]+-[0-9]{3}$")]
    title: str = Field(min_length=1)
    fidelity: Fidelity
    instrument: ScenarioInstrument
    settings: ScenarioSettings
    fees: Fee | None = None
    position: OpenPosition | None = None
    tape: Tape
    funding: tuple[FundingRate, ...] = ()
    orders: tuple[Order, ...] = Field(min_length=1)
    expected: Expected
    rules: tuple[RuleId, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _settings_default_to_the_specification(cls, raw: object) -> object:
        """A scenario that states no slippage fills with the specification's default for its
        fidelity: none on TBBO, which fills at the quote, one tick on every other (F-SLP-01)."""
        if not isinstance(raw, dict):
            return raw
        settings = raw.get("settings", {})
        if not isinstance(settings, dict) or "slippage_ticks" in settings:
            return raw
        ticks = 0 if raw.get("fidelity") == TickFidelity.TBBO else 1
        return {**raw, "settings": {**settings, "slippage_ticks": {"market": ticks, "stop": ticks}}}

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_tape(self.fidelity, self.tape)
        self._check_prices_on_the_tick()
        self._check_quantities_on_the_lot_step()
        self._check_orders()
        self._check_expected()
        return self

    def _prices(self) -> Iterator[int]:
        for record in self.tape:
            yield from record.prices()
        for order in self.orders:
            yield from order.prices()
        if self.position is not None:
            yield self.position.price
        yield from (fill.price for fill in self.expected.fills)
        yield from (mark.price for mark in self.expected.marks)

    def _check_prices_on_the_tick(self) -> None:
        tick = self.instrument.tick_size.scaleb(PRICE_DECIMALS)
        off = [price_text(price) for price in self._prices() if price % tick != 0]
        if off:
            raise ValueError(
                f"Expected every price of {self.id} on the tick of {self.instrument.tick_size}, "
                f"got {', '.join(off)}."
            )

    def _check_quantities_on_the_lot_step(self) -> None:
        quantities = [order.quantity for order in self.orders]
        if self.position is not None:
            quantities.append(self.position.quantity)
        lot_step = self.instrument.lot_step
        off = [str(quantity) for quantity in quantities if quantity % lot_step != 0]
        if off:
            raise ValueError(
                f"Expected every quantity of {self.id} on the lot step of {lot_step}, "
                f"got {', '.join(off)}."
            )

    def _check_orders(self) -> None:
        ids = Counter(order_id for order in self.orders for order_id in order.ids())
        repeated = sorted(order_id for order_id, uses in ids.items() if uses > 1)
        if repeated:
            raise ValueError(f"Expected each order id of {self.id} once, got {repeated} again.")
        groups = Counter(order.oco for order in self.orders if order.oco is not None)
        alone = sorted(group for group, size in groups.items() if size < 2)
        if alone:
            raise ValueError(
                f"Expected two orders or more in each OCO group of {self.id}, got one in {alone}."
            )

    def _check_expected(self) -> None:
        ids = sorted(order_id for order in self.orders for order_id in order.ids())
        for fill in self.expected.fills:
            if fill.order not in ids:
                raise ValueError(
                    f"Expected each fill of {self.id} to fill one of its orders {ids}, "
                    f"got order {fill.order}."
                )
            if fill.rule not in self.rules:
                raise ValueError(
                    f"Expected each fill's rule among those {self.id} cites, got {fill.rule}."
                )
            if (fill.fee is None) != (self.fees is None):
                raise ValueError(
                    f"Expected a fee on each fill of {self.id} exactly when it has fees, got "
                    f"order {fill.order}'s fill {'without' if fill.fee is None else 'with'} one."
                )
        times = {rate.ts for rate in self.funding}
        if any(payment.ts not in times for payment in self.expected.funding):
            raise ValueError(f"Expected each funding payment of {self.id} at a funding time.")


def load_scenario(path: Path) -> Scenario:
    """The scenario in one YAML file, which is named by its id: `S-fill-012.yaml`."""
    try:
        scenario = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError) as error:
        raise ValueError(f"Expected {path.name} to hold a fill scenario, got: {error}") from error
    if path.name != f"{scenario.id}.yaml":
        raise ValueError(f"Expected {path.name} to be named by its id, {scenario.id}.yaml.")
    return scenario


def load_scenarios(folder: Path) -> tuple[Scenario, ...]:
    """Every scenario in `folder`, in the order of their ids."""
    return tuple(load_scenario(path) for path in sorted(folder.glob("*.yaml")))


def specified_rules(specification: str) -> tuple[str, ...]:
    """The identifiers of the rules a fill specification defines, in its order: each rule's
    paragraph opens with its identifier in bold, `**F-STP-03**`."""
    return tuple(_RULE_DEFINITION.findall(specification))
