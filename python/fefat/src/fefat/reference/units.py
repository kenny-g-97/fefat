"""Values as fill scenarios write them and as the engines count them (Phase 2's conventions).

A price is a decimal in quotes, held as an int64 count of 1e-9 units of the quote currency
(ADR-0019): "4990.25" is 4_990_250_000_000. Money is a decimal in quotes, held as micro-units
of its currency; an instant is a UTC time in quotes, held as nanoseconds since the Unix epoch;
and a quantity counts the instrument's units. YAML reads an unquoted `4990.25` as a binary
fraction and `14:30:00` as the number 52200, so only quoted text is accepted.
"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator

from fefat.market.instruments import Instrument
from fefat.market.schema import FrozenModel

PRICE_DECIMALS = 9
"""Prices count 1e-9 units of the quote currency."""
MONEY_DECIMALS = 6
"""Money counts micro-units of its currency."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
"""The Unix epoch; adding to it works for every instant, where Windows' fromtimestamp refuses
those well before 1970."""
_DECIMAL_TEXT = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?")
_INSTANT_TEXT = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?Z"
)


def _scaled(text: object, decimals: int, what: str) -> int:
    """`text`, a decimal in quotes with at most `decimals` places, as a count of 10**-decimals."""
    found = _DECIMAL_TEXT.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        raise ValueError(
            f'Expected {what} written in quotes as a decimal, such as "4990.25", got {text!r}.'
        )
    fraction = found[3] or ""
    if len(fraction) > decimals:
        raise ValueError(f"Expected {what} with at most {decimals} decimal places, got {text!r}.")
    magnitude = int(found[2]) * 10**decimals + int(fraction.ljust(decimals, "0"))
    return -magnitude if found[1] else magnitude


def price_units(text: object) -> int:
    """A price written as a decimal in quotes, as a count of 1e-9 units: "4990.25" is
    4_990_250_000_000. A number YAML read unquoted, or more than nine places, is refused."""
    return _scaled(text, PRICE_DECIMALS, "a price")


def money_units(text: object) -> int:
    """An amount of money written as a decimal in quotes, as a count of micro-units of its
    currency: "2.50" is 2_500_000."""
    return _scaled(text, MONEY_DECIMALS, "an amount of money")


def instant_nanoseconds(text: object) -> int:
    """An instant written in quotes as a UTC time, "2026-03-06T14:30:00.100Z", as nanoseconds
    since the Unix epoch."""
    found = _INSTANT_TEXT.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        raise ValueError(
            "Expected an instant written in quotes as a UTC time, such as "
            f'"2026-03-06T14:30:00.100Z", got {text!r}.'
        )
    try:
        seconds = int(datetime.fromisoformat(found[1]).replace(tzinfo=UTC).timestamp())
    except ValueError:
        raise ValueError(f"Expected an instant on a real date and time, got {text!r}.") from None
    return seconds * 1_000_000_000 + int((found[2] or "").ljust(9, "0"))


def price_text(units: int) -> str:
    """A price in 1e-9 units as the decimal it is written as, such as 4990.25."""
    return format(Decimal(units).scaleb(-PRICE_DECIMALS).normalize(), "f")


def instant_text(nanoseconds: int) -> str:
    """An instant in nanoseconds as the UTC time it is written as, such as 2026-03-06T14:30:00.1Z."""
    seconds, fraction = divmod(nanoseconds, 1_000_000_000)
    clock = (_EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{clock}.{fraction:09d}".rstrip("0").rstrip(".") + "Z"


def utc_date(nanoseconds: int) -> date:
    """The UTC date of an instant in nanoseconds."""
    return (_EPOCH + timedelta(microseconds=nanoseconds // 1_000)).date()


def money_text(units: int) -> str:
    """An amount in micro-units as the decimal it is written as, such as -0.084514."""
    return format(Decimal(units).scaleb(-MONEY_DECIMALS), "f")


def exact_money(amount: Decimal) -> Fraction:
    """An amount of money as an exact count of micro-units, before it is rounded (F-FEE-03)."""
    return Fraction(amount) * 10**MONEY_DECIMALS


def lots_of(quantity: Decimal, lot_step: Decimal) -> int:
    """A quantity in the instrument's units as a count of its lots, the dataset's size unit:
    0.013 BTC is 13 lots of 0.001 BTC."""
    lots = quantity / lot_step
    if lots != lots.to_integral_value():
        raise ValueError(f"Expected a quantity in whole lots of {lot_step}, got {quantity}.")
    return int(lots)


def _quoted_decimal(text: object) -> Decimal:
    if not isinstance(text, str) or _DECIMAL_TEXT.fullmatch(text) is None:
        raise ValueError(f'Expected a decimal written in quotes, such as "0.25", got {text!r}.')
    return Decimal(text)


def _quantity(value: object) -> Decimal:
    """A quantity in the instrument's units: a whole number, or a decimal in quotes."""
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value) is not None:
        return Decimal(value)
    raise ValueError(
        'Expected a quantity as a whole number or a decimal in quotes, such as "0.013", '
        f"got {value!r}."
    )


Price = Annotated[int, BeforeValidator(price_units)]
"""A price, written as a decimal in quotes and held as a count of 1e-9 units."""
Money = Annotated[int, BeforeValidator(money_units)]
"""An amount of money, written as a decimal in quotes and held as a count of micro-units."""
Instant = Annotated[int, BeforeValidator(instant_nanoseconds)]
"""An instant, written in quotes as a UTC time and held as nanoseconds since the Unix epoch."""
QuotedDecimal = Annotated[Decimal, BeforeValidator(_quoted_decimal)]
"""A decimal written in quotes, such as a funding rate, "0.0001"."""
PositiveDecimal = Annotated[QuotedDecimal, Field(gt=0)]
Quantity = Annotated[Decimal, BeforeValidator(_quantity), Field(gt=0)]
"""A quantity in the instrument's units: contracts for futures, the base asset for crypto."""


class InlineInstrument(FrozenModel):
    """A product the instrument table lacks, given by its tick size, point value, and lot
    step. It names no calendar, so it trades around the clock: its scenarios hold no breaks."""

    tick_size: PositiveDecimal
    point_value: PositiveDecimal
    lot_step: PositiveDecimal

    @model_validator(mode="after")
    def _tick_in_price_units(self) -> Self:
        if self.tick_size.scaleb(PRICE_DECIMALS) % 1 != 0:
            raise ValueError(
                "Expected a tick size in whole 1e-9 units, nine decimal places at most, "
                f"got {self.tick_size}."
            )
        return self


class InstrumentParameters(FrozenModel):
    """An instrument's specification in the units both engines count in (D-51): its tick in
    1e-9 units of price, the money one lot gains or loses per point in micro-units, and its lot
    step, the dataset's size unit."""

    tick: int = Field(gt=0)
    money_per_point: int = Field(gt=0)
    lot_step: Decimal = Field(gt=0)

    def value(self, price: int, lots: int) -> Fraction:
        """What `lots` are worth at `price`, exactly, in micro-units: negative for a short."""
        return Fraction(price * lots * self.money_per_point, 10**PRICE_DECIMALS)


def instrument_parameters(instrument: Instrument | InlineInstrument) -> InstrumentParameters:
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
