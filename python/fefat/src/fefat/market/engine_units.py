"""Prices and money as the engines count them (Phase 2's conventions, D-51): a price is an int64
count of 1e-9 units of its quote currency (ADR-0019), and money an int64 count of micro-units of
its currency. An instrument's decimal tick size, point value, and lot step become the engines'
integer parameters here, once, for the reference engine and for `ff.backtest` alike (step
2.10); `fefat.reference.units` reads the scenarios' quoted decimals into the same units.

    parameters = instrument_parameters(instruments.get("ES"))
    parameters.tick  # 250_000_000, a tick of 0.25
    price_text(4_990_250_000_000)  # "4990.25"
    bars.select(price_in_units("close"))  # 4990.25, a float, as the API sends it
"""

from decimal import Decimal
from fractions import Fraction
from typing import Protocol

import polars as pl
from pydantic import Field

from fefat.market.schema import FrozenModel

PRICE_DECIMALS = 9
"""Prices count 1e-9 units of the quote currency."""
MONEY_DECIMALS = 6
"""Money counts micro-units of its currency."""
PRICE_SCALE = 10**PRICE_DECIMALS
"""The 1e-9 units in one unit of price: a tick of 0.25 is 250_000_000 of them."""


def price_text(units: int) -> str:
    """A price in 1e-9 units as the decimal it is written as, such as 4990.25."""
    return format(Decimal(units).scaleb(-PRICE_DECIMALS).normalize(), "f")


def price_in_units(column: str) -> pl.Expr:
    """The prices of `column`, in 1e-9 units, in the instrument's units, each the float nearest
    its decimal, as the API sends them (step 5.1): 4_990_250_000_000 is 4990.25."""
    return pl.col(column) / PRICE_SCALE


def money_text(units: int) -> str:
    """An amount in micro-units as the decimal it is written as, such as -0.084514."""
    return format(Decimal(units).scaleb(-MONEY_DECIMALS), "f")


def micro_units(amount: Decimal) -> int:
    """An amount of money as a count of micro-units: 50000 is 50_000_000_000; an amount finer
    than a micro-unit is refused."""
    units = amount.scaleb(MONEY_DECIMALS)
    if units != units.to_integral_value():
        raise ValueError(f"Expected an amount in whole micro-units, got {amount}.")
    return int(units)


class InstrumentSpecification(Protocol):
    """What the conversion reads of an instrument: its tick size and point value in its quote
    currency, and its lot step, the dataset's size unit."""

    @property
    def tick_size(self) -> Decimal: ...

    @property
    def point_value(self) -> Decimal: ...

    @property
    def lot_step(self) -> Decimal: ...


class InstrumentParameters(FrozenModel):
    """An instrument's specification in the units both engines count in (D-51): its tick in
    1e-9 units of price, the money one lot gains or loses per point in micro-units, and its lot
    step, the dataset's size unit."""

    tick: int = Field(gt=0)
    money_per_point: int = Field(gt=0)
    lot_step: Decimal = Field(gt=0)

    def value(self, price: int, lots: int) -> Fraction:
        """What `lots` are worth at `price`, exactly, in micro-units: negative for a short."""
        return Fraction(price * lots * self.money_per_point, PRICE_SCALE)


def instrument_parameters(instrument: InstrumentSpecification) -> InstrumentParameters:
    """The instrument's decimal tick size and point value as the engines' integers, converted
    once, here (D-51): ES's tick of 0.25 is 250_000_000 and its 50 USD a point 50_000_000
    micro-units; a perpetual's 1 USD a point on lots of 0.001 BTC is 1_000 a lot."""
    tick = instrument.tick_size.scaleb(PRICE_DECIMALS)
    money = (instrument.point_value * instrument.lot_step).scaleb(MONEY_DECIMALS)
    if tick % 1 != 0 or money % 1 != 0:
        raise ValueError(
            "Expected a tick in whole 1e-9 units and a point value in whole micro-units a lot, "
            f"got a tick of {instrument.tick_size} and {instrument.point_value} a point on lots "
            f"of {instrument.lot_step}."
        )
    return InstrumentParameters(
        tick=int(tick), money_per_point=int(money), lot_step=instrument.lot_step
    )
