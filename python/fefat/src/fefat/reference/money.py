"""The money rules of the reference engine (`docs/spec/fill-semantics.md` §14, F-FEE and F-FND):
a futures fill's charge per contract per side, a crypto fill's basis points, the rounding of every
amount against the trader, and a perpetual's funding, each a small function named after its
identifier, as in `fefat.reference.engine`, which books them."""

import math
from decimal import Decimal
from fractions import Fraction

from fefat.market.fees import CryptoFee, FuturesFee
from fefat.reference.ledger import Liquidity
from fefat.reference.units import InstrumentParameters, exact_money


def f_fee_01(fee: FuturesFee, quantity: Decimal) -> Fraction:
    """A futures fill pays the charge per contract per side of the schedule in force."""
    return exact_money(fee.per_contract_side * quantity)


def f_fee_02(fee: CryptoFee, value: Fraction, liquidity: Liquidity) -> Fraction:
    """A crypto fill pays basis points of its value: the maker rate for a limit that rested, the
    taker rate for every other fill."""
    rate = fee.maker_bps if liquidity is Liquidity.MAKER else fee.taker_bps
    return abs(value) * Fraction(rate) / 10_000


def f_fee_03(cash_change: Fraction, what: str) -> int:
    """An exact amount is booked to the micro-unit toward minus infinity of the cash, so what the
    trader pays rounds up and what it receives down; past 64 bits it is an error."""
    booked = math.floor(cash_change)
    if not -(2**63) <= booked < 2**63:
        raise ValueError(f"Expected {what} within 64 bits of micro-units, got {booked}.")
    return booked


def f_fnd_01(position: int, mark: int, instrument: InstrumentParameters, rate: Decimal) -> Fraction:
    """At a funding time an open position pays signed quantity x mark x point value x rate, so a
    long pays a positive rate and a short receives it: returned as the change to the cash."""
    return -instrument.value(mark, position) * Fraction(rate)
