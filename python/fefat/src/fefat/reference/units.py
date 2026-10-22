"""Values as fill scenarios write them and as the engines count them (Phase 2's conventions).

A price is a decimal in quotes, held as an int64 count of 1e-9 units of the quote currency
(ADR-0019): "4990.25" is 4_990_250_000_000. Money is a decimal in quotes, held as micro-units
of its currency; an instant is a UTC time in quotes, held as nanoseconds since the Unix epoch;
and a quantity counts the instrument's units. YAML reads an unquoted `4990.25` as a binary
fraction and `14:30:00` as the number 52200, so only quoted text is accepted.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field

PRICE_DECIMALS = 9
"""Prices count 1e-9 units of the quote currency."""
MONEY_DECIMALS = 6
"""Money counts micro-units of its currency."""

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
    clock = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{clock}.{fraction:09d}".rstrip("0").rstrip(".") + "Z"


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
