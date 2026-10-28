"""The sizes of an execution template's entries as the reference engine works them out
(`docs/spec/fill-semantics.md` §28): a fixed size in whole lot steps times `size_mult` (F-SIZ-01),
the lots a notional amount buys at the entry's price (F-SIZ-02), the lots that lose a risk amount
at the stop (F-SIZ-03), and a computed size times `size_mult` rounded down, or no entry with the
reason the log gives (F-SIZ-04). Money counts micro-units, exactly until the size is rounded."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

from fefat.market.calendar import utc_text
from fefat.reference.exit_plan import ExitPlan, stop_level
from fefat.reference.orders import Side
from fefat.reference.template.limits import micro_units
from fefat.reference.units import InstrumentParameters
from fefat.strategy.spec import (
    FixedSize,
    NotionalSize,
    RiskAmountSize,
    RiskPercentSize,
    Sizing,
)


@dataclass(frozen=True, slots=True)
class NoEntry:
    """Why an entry's size places no entry, and the rule that says so."""

    why: str
    rule: str


@dataclass(frozen=True, slots=True)
class EntryPricing:
    """What an entry's size reads: its side, its price, a limit's or a stop's or for a market
    entry the mark at the decision (none before the first), its exit plan, and the equity at the
    decision in micro-units."""

    side: Side
    price: int | None
    plan: ExitPlan
    equity: int


def _exact(number: float) -> Decimal:
    return Decimal(repr(number))


# §28 Sizing
def f_siz_01(lots: int, bar: Mapping[str, Any]) -> int:
    """A fixed size of `lots`, its units in whole lot steps, times the row's `size_mult`, which
    must make whole lots, at least one, or the run is refused."""
    multiple = bar.get("size_mult")
    if multiple is None:
        return lots
    multiplied = _exact(multiple) * lots
    if multiplied != multiplied.to_integral_value() or multiplied < 1:
        raise ValueError(
            f"Expected size_mult to make whole lots, at least one, got {multiple} times {lots} "
            f"lots on the bar closing at {utc_text(bar['ts_close'])}."
        )
    return int(multiplied)


def f_siz_02(amount: int, price: int, instrument: InstrumentParameters) -> int:
    """The whole lots whose value at `price` is at most `amount` micro-units, rounded down."""
    if price <= 0:
        return 0
    return math.floor(Fraction(amount) / instrument.value(price, 1))


def f_siz_03(amount: int, price: int, stop: int, instrument: InstrumentParameters) -> int:
    """The whole lots that lose at most `amount` micro-units from `price` to `stop`, rounded
    down."""
    return math.floor(Fraction(amount) / instrument.value(abs(price - stop), 1))


def f_siz_04(lots: int, bar: Mapping[str, Any]) -> int:
    """A computed size times the row's `size_mult`, rounded down to whole lots."""
    multiple = bar.get("size_mult")
    return lots if multiple is None else math.floor(_exact(multiple) * lots)


def computed_lots(
    sizing: Sizing,
    pricing: EntryPricing,
    bar: Mapping[str, Any],
    instrument: InstrumentParameters,
) -> int | NoEntry:
    """The lots of a notional or risk size (F-SIZ-02 to F-SIZ-04), or why there are none."""
    price = pricing.price
    if price is None:
        return NoEntry("no mark to price the entry's size", "F-SIZ-04")
    if isinstance(sizing, FixedSize):
        raise ValueError(f"Expected a notional or a risk size, got {sizing}.")
    if isinstance(sizing, NotionalSize):
        lots = f_siz_02(micro_units(sizing.amount), price, instrument)
    else:
        stop = _stop_for(pricing, price, instrument.tick)
        if stop is None:
            return NoEntry("the stop_price is not below the entry's price", "F-SIZ-03")
        lots = f_siz_03(_risked(sizing, pricing.equity), price, stop, instrument)
    lots = f_siz_04(lots, bar)
    return lots if lots >= 1 else NoEntry("the size rounds to no lots", "F-SIZ-04")


def _risked(sizing: RiskAmountSize | RiskPercentSize, equity: int) -> int:
    """A risk size's amount in micro-units: its own, or `percent` % of equity rounded down."""
    if isinstance(sizing, RiskAmountSize):
        return micro_units(sizing.amount)
    return math.floor(Fraction(_exact(sizing.percent)) * equity / 100)


def _stop_for(pricing: EntryPricing, price: int, tick: int) -> int | None:
    """The stop as F-PLN-01 would place it for a fill at `price`: none when it is not on the
    losing side of `price`."""
    planned = pricing.plan.stop
    if planned is None:
        raise ValueError("Expected a stop beside a risk size (F-RND-02), got none.")
    stop = stop_level(planned.price, pricing.side, price, tick)
    losing = stop < price if pricing.side is Side.BUY else stop > price
    return stop if losing else None
