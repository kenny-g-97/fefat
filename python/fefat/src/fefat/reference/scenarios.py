"""Fill scenarios: the hand-computable cases that specify how the engines fill orders (D-10).

A scenario is one YAML file in `fixtures/scenarios/`, named by its id (`S-fill-012.yaml`): a
tape (`fefat.reference.tape`), an instrument, and the fills, marks, and funding payments the
rules of `docs/spec/fill-semantics.md` give, with the identifiers of the rules it exercises. An
order scenario (`Scenario`) places orders at given instants (`fefat.reference.orders`); a template
scenario (`TemplateScenario`, step 2.3) gives a `StrategySpec` and the rows of its signal frame
(`fefat.reference.signal_rows`), which the reference engine runs through its template
(`fefat.reference.template`). `fixtures/scenarios/README.md` documents the format. Its values
are held in the units both engines count in (`fefat.reference.units`), so that their fills
compare as integers:

    load_scenario(Path("fixtures/scenarios/S-fill-012.yaml")).expected.fills[0].price
    # 4_990_250_000_000, written "4990.25"
"""

import re
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Self

import polars as pl
import yaml
from pydantic import (
    BeforeValidator,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from fefat.market import instruments
from fefat.market.fees import Fee
from fefat.market.fidelity import Fidelity
from fefat.market.instruments import Instrument, InstrumentKind
from fefat.market.schema import FrozenModel
from fefat.reference.costs import DatedFees, RunFees
from fefat.reference.ledger import FillFlag
from fefat.reference.orders import OpenPosition, Order, OrderId, OrderRole, oco_groups
from fefat.reference.rolls import RollRow, f_rol_01
from fefat.reference.settings import RunSettings, default_slippage_ticks
from fefat.reference.signal_rows import SignalRow, signal_frame
from fefat.reference.tape import FundingRate, Tape, check_tape, parse_tape
from fefat.reference.units import (
    PRICE_DECIMALS,
    InlineInstrument,
    Instant,
    Money,
    Price,
    Quantity,
    instant_text,
    price_text,
)
from fefat.strategy.spec import FixedSize, StrategySpec

RuleId = Annotated[str, Field(pattern=r"^F-[A-Z]{3}-[0-9]{2}$")]
"""A rule of the fill specification, such as F-STP-03."""

_RULE_DEFINITION = re.compile(r"^\*\*(F-[A-Z]{3}-[0-9]{2})\*\*", re.MULTILINE)


def _instrument(value: object) -> object:
    """A root's text as the instrument table's version of it."""
    # shortcut: a root's newest version; look it up by the tape's date once a spec changes.
    return instruments.get(value) if isinstance(value, str) else value


ScenarioInstrument = Annotated[Instrument | InlineInstrument, BeforeValidator(_instrument)]


class ExpectedFill(FrozenModel):
    """A fill the rules give: the order it fills, when, at what price, the rule that priced it
    (F-TAG-01), its flags, in a scenario with fees its fee, and, where the scenario states them,
    its quantity in the instrument's units, which a template's targets and sizes decide, its
    role, which records a template's exit reason or a roll's (F-TAG-01), and the contract it is
    of, which a roll changes (F-ROL-01)."""

    order: OrderId
    ts: Instant
    price: Price
    rule: RuleId
    flags: tuple[FillFlag, ...] = ()
    fee: Money | None = None
    quantity: Quantity | None = None
    role: OrderRole | None = None
    contract: str | None = None


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


class ScenarioBase(FrozenModel):
    """What every scenario holds, as `fixtures/scenarios/README.md` describes it: its tape, the
    instrument, settings, and costs it runs with, the position held when the tape starts, the
    rolls of a future's front, and what the rules give; each kind adds what decides its
    orders."""

    id: Annotated[str, Field(pattern=r"^S-[a-z]+-[0-9]{3}$")]
    title: str = Field(min_length=1)
    fidelity: Fidelity
    instrument: ScenarioInstrument
    settings: RunSettings
    fees: Fee | DatedFees | None = None
    position: OpenPosition | None = None
    tape: Tape
    funding: tuple[FundingRate, ...] = ()
    rolls: tuple[RollRow, ...] = ()
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
        ticks = default_slippage_ticks(raw.get("fidelity")).model_dump()
        return {**raw, "settings": {**settings, "slippage_ticks": ticks}}

    @field_validator("tape", mode="before")
    @classmethod
    def _records_of_the_fidelity(cls, raw: object, validation: ValidationInfo) -> object:
        """The tape read as the records its fidelity names; without a valid fidelity, the
        fidelity's own error says why."""
        fidelity = validation.data.get("fidelity")
        if fidelity is None:
            return raw
        return parse_tape(fidelity, raw)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_tape(self.fidelity, self.tape)
        f_rol_01(self.rolls, self.opening_contract())
        self._check_prices_on_the_tick()
        self._check_quantities_on_the_lot_step()
        self._check_costs_fit_the_instrument()
        self._check_expected()
        self._check_its_own()
        return self

    def opening_contract(self) -> str:
        """The contract the run starts on: the first roll's contract rolled from, and without
        rolls the scenario's id, the label the engines give its one contract."""
        return self.rolls[0].rolled_from if self.rolls else self.id

    def contracts(self) -> tuple[str, ...]:
        """The contracts the run trades, in order (F-ROL-01)."""
        return (self.opening_contract(), *(roll.contract for roll in self.rolls))

    def run_fees(self) -> RunFees | None:
        """The fee table the run prices its fills with (F-FEE-01), none without fees."""
        return None if self.fees is None else RunFees.of(self.fees)

    def _own_prices(self) -> Iterator[int]:
        """The prices that what decides this kind of scenario's orders names."""
        yield from ()

    def _own_quantities(self) -> list[Decimal]:
        """The quantities that this kind of scenario's orders name."""
        return []

    def _check_its_own(self) -> None:
        """The checks of this kind of scenario."""

    def _check_contracts(self) -> None:
        """A contract on every fill or on none, each one the run trades (F-ROL-01)."""
        stated = [fill.contract for fill in self.expected.fills if fill.contract is not None]
        if stated and len(stated) != len(self.expected.fills):
            raise ValueError(
                f"Expected a contract on every fill of {self.id} or on none, got one on "
                f"{len(stated)} of {len(self.expected.fills)}."
            )
        unknown = sorted(set(stated) - set(self.contracts()))
        if unknown:
            raise ValueError(
                f"Expected each fill of {self.id} on one of its contracts "
                f"{list(self.contracts())}, got {unknown}."
            )

    def _prices(self) -> Iterator[int]:
        for record in self.tape:
            yield from record.prices()
        yield from self._own_prices()
        if self.position is not None:
            yield self.position.price
        yield from (fill.price for fill in self.expected.fills)
        yield from (mark.price for mark in self.expected.marks)
        yield from (roll.gap for roll in self.rolls)

    def _check_prices_on_the_tick(self) -> None:
        tick = self.instrument.tick_size.scaleb(PRICE_DECIMALS)
        off = [price_text(price) for price in self._prices() if price % tick != 0]
        if off:
            raise ValueError(
                f"Expected every price of {self.id} on the tick of {self.instrument.tick_size}, "
                f"got {', '.join(off)}."
            )

    def _check_quantities_on_the_lot_step(self) -> None:
        quantities = self._own_quantities()
        if self.position is not None:
            quantities.append(self.position.quantity)
        quantities += [fill.quantity for fill in self.expected.fills if fill.quantity is not None]
        lot_step = self.instrument.lot_step
        off = [str(quantity) for quantity in quantities if quantity % lot_step != 0]
        if off:
            raise ValueError(
                f"Expected every quantity of {self.id} on the lot step of {lot_step}, "
                f"got {', '.join(off)}."
            )

    def _check_costs_fit_the_instrument(self) -> None:
        if not isinstance(self.instrument, Instrument):
            return
        root, kind = self.instrument.root, self.instrument.kind
        futures = kind is InstrumentKind.FUTURES
        if self.fees is not None and (self.fees.kind == "futures") != futures:
            raise ValueError(
                f"Expected {'futures' if futures else 'crypto'} fees for {root}, a {kind} "
                f"instrument, got {self.fees.kind} fees."
            )
        if self.rolls and not futures:
            raise ValueError(
                f"Expected rolls on a future only, got them on {root}, a {kind} instrument."
            )
        if self.funding and kind is not InstrumentKind.PERPETUAL:
            raise ValueError(
                f"Expected funding rates on a perpetual only, got them on {root}, a {kind} "
                "instrument."
            )

    def _check_expected(self) -> None:
        """Each fill priced by a rule the scenario cites, with a fee exactly when it has fees,
        each order filled once at most (F-QTY-01), and each payment at a funding time."""
        for fill in self.expected.fills:
            if fill.rule not in self.rules:
                raise ValueError(
                    f"Expected each fill's rule among those {self.id} cites, got {fill.rule}."
                )
            if (fill.fee is None) != (self.fees is None):
                raise ValueError(
                    f"Expected a fee on each fill of {self.id} exactly when it has fees, got "
                    f"order {fill.order}'s fill {'without' if fill.fee is None else 'with'} one."
                )
        stated = [fill.quantity is not None for fill in self.expected.fills]
        if any(stated) and not all(stated):
            raise ValueError(
                f"Expected a quantity on every fill of {self.id} or on none, got one on "
                f"{sum(stated)} of {len(stated)}."
            )
        roles = [fill.role is not None for fill in self.expected.fills]
        if any(roles) and not all(roles):
            raise ValueError(
                f"Expected a role on every fill of {self.id} or on none, got one on "
                f"{sum(roles)} of {len(roles)}."
            )
        self._check_contracts()
        filled = Counter(fill.order for fill in self.expected.fills)
        again = sorted(order for order, fills in filled.items() if fills > 1)
        if again:
            raise ValueError(
                f"Expected each order of {self.id} to fill once at most, got {again} again."
            )
        times = sorted({rate.ts for rate in self.funding})
        unpaid = [payment.ts for payment in self.expected.funding if payment.ts not in times]
        if unpaid:
            raise ValueError(
                f"Expected each funding payment of {self.id} at one of its funding times "
                f"{[instant_text(time) for time in times]}, got "
                f"{[instant_text(time) for time in unpaid]}."
            )


class Scenario(ScenarioBase):
    """An order scenario: the orders placed at given decision instants, with their OCO groups
    and brackets, and the fills the rules give them."""

    orders: tuple[Order, ...] = Field(min_length=1)

    def _own_prices(self) -> Iterator[int]:
        for order in self.orders:
            yield from order.prices()

    def _own_quantities(self) -> list[Decimal]:
        return [order.quantity for order in self.orders]

    def _check_its_own(self) -> None:
        self._check_orders()
        self._check_fills_are_of_its_orders()
        self._check_fills_are_possible()

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

    def highest_id(self) -> int:
        """The highest id the scenario names, after which the engine gives its own orders, a
        roll's legs, theirs (F-ROL-02)."""
        return max(order_id for order in self.orders for order_id in order.ids())

    def _check_fills_are_of_its_orders(self) -> None:
        """Each fill of one of its orders, or with rolls of a leg the engine gives an id after
        theirs (F-ROL-02)."""
        ids = sorted(order_id for order in self.orders for order_id in order.ids())
        for fill in self.expected.fills:
            if fill.order not in ids and not (self.rolls and fill.order > self.highest_id()):
                raise ValueError(
                    f"Expected each fill of {self.id} to fill one of its orders {ids}, "
                    f"got order {fill.order}."
                )

    def _check_fills_are_possible(self) -> None:
        """One order of an OCO group fills at most (F-OCO-01), and a bracket's leg only once its
        entry has filled (F-OCO-02)."""
        filled = {fill.order for fill in self.expected.fills}
        for group in oco_groups(self.orders):
            if len(group & filled) > 1:
                raise ValueError(
                    f"Expected one fill at most in each OCO group of {self.id} (F-OCO-01), got "
                    f"orders {sorted(group & filled)}."
                )
        times = {fill.order: fill.ts for fill in self.expected.fills}
        for order in self.orders:
            for leg in set(order.ids()[1:]) & times.keys():
                if order.id not in times or times[leg] < times[order.id]:
                    raise ValueError(
                        f"Expected bracket leg {leg} of {self.id} to fill after its entry, order "
                        f"{order.id}, fills (F-OCO-02)."
                    )


class TemplateScenario(ScenarioBase):
    """A template scenario (step 2.3): a `StrategySpec` and the rows of its signal frame, which
    the reference engine runs through its template (`fefat.reference.template`); the orders the
    template places take the ids the engine gives them, from 1 in the order they are placed."""

    strategy: StrategySpec
    signals: tuple[SignalRow, ...] = Field(min_length=1)

    def _own_prices(self) -> Iterator[int]:
        for row in self.signals:
            yield from row.prices()

    def _own_quantities(self) -> list[Decimal]:
        sizing = self.strategy.execution.sizing
        return [Decimal(repr(sizing.units))] if isinstance(sizing, FixedSize) else []

    def _check_its_own(self) -> None:
        if not isinstance(self.instrument, Instrument):
            return
        if self.strategy.instrument != self.instrument.root:
            raise ValueError(
                f"Expected the strategy of {self.id} to trade its instrument "
                f"{self.instrument.root}, got {self.strategy.instrument}."
            )

    def signal_frame(self) -> pl.DataFrame:
        """The signal frame of its rows, at raw prices (`fefat.reference.signal_rows`)."""
        return signal_frame(self.signals)


AnyScenario = Scenario | TemplateScenario
"""A scenario of either kind."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML's safe loader, refusing a key given twice in one mapping, of which YAML would keep
    the last without a word."""


def _mapping_of_unique_keys(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    keys = [loader.construct_object(key, deep=True) for key, _ in node.value]
    repeated = sorted({str(key) for key in keys if keys.count(key) > 1})
    if repeated:
        raise yaml.constructor.ConstructorError(
            None,
            None,
            f"Expected each key once in a mapping, got {repeated} again",
            node.start_mark,
        )
    return loader.construct_mapping(node, deep=True)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_of_unique_keys
)


def load_scenario(path: Path) -> AnyScenario:
    """The scenario in one YAML file, which is named by its id: `S-fill-012.yaml`. A scenario
    that gives a `strategy` is a template scenario, any other an order scenario."""
    text = path.read_text(encoding="utf-8")
    try:
        written = yaml.load(text, Loader=_UniqueKeyLoader)
        kind = TemplateScenario if isinstance(written, dict) and "strategy" in written else Scenario
        scenario = kind.model_validate(written)
    except (ValidationError, yaml.YAMLError) as error:
        raise ValueError(f"Expected {path.name} to hold a fill scenario, got: {error}") from error
    if path.name != f"{scenario.id}.yaml":
        raise ValueError(f"Expected {path.name} to be named by its id, {scenario.id}.yaml.")
    return scenario


def load_scenarios(folder: Path) -> tuple[AnyScenario, ...]:
    """Every scenario in `folder`, in the order of their ids."""
    return tuple(load_scenario(path) for path in sorted(folder.glob("*.yaml")))


def specified_rules(specification: str) -> tuple[str, ...]:
    """The identifiers of the rules a fill specification defines, in its order: each rule's
    paragraph opens with its identifier in bold, `**F-STP-03**`."""
    return tuple(_RULE_DEFINITION.findall(specification))
