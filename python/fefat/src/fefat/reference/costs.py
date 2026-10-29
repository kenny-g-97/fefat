"""A run's fee table in the reference engine (`docs/spec/fill-semantics.md` §14, step 2.9): each
schedule in force from its date until the next one's, the first also before its date, which the
run warns of (F-FEE-01), as a scenario states it, one fee in force on every date or a dated table;
and the fee of one fill, by the rules of `fefat.reference.money`."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Self

from pydantic import Field, model_validator

from fefat.market.fees import CryptoFee, FeeTable, FuturesFee
from fefat.market.schema import FrozenModel
from fefat.reference.ledger import Liquidity
from fefat.reference.money import f_fee_01, f_fee_02
from fefat.reference.tape import FundingRate
from fefat.reference.units import day_number, instant_text


class DatedFuturesFee(FuturesFee):
    """A futures fee per contract per side, in force from `effective_from` (F-FEE-01)."""

    effective_from: date


class DatedCryptoFee(CryptoFee):
    """A crypto fee in basis points, in force from `effective_from` (F-FEE-01, F-FEE-02)."""

    effective_from: date


class DatedFees(FrozenModel):
    """A scenario's dated fee table: its kind and its schedules, in the order of their dates,
    each in force from its date until the next one's (F-FEE-01)."""

    kind: Literal["futures", "crypto"]
    schedules: tuple[DatedFuturesFee | DatedCryptoFee, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _of_its_kind_in_date_order(self) -> Self:
        kinds = sorted({schedule.kind for schedule in self.schedules} - {self.kind})
        if kinds:
            raise ValueError(
                f"Expected every schedule of a {self.kind} fee table to price {self.kind} fills, "
                f"got {', '.join(kinds)} ones."
            )
        dates = [schedule.effective_from for schedule in self.schedules]
        if any(later <= earlier for earlier, later in itertools.pairwise(dates)):
            raise ValueError(
                "Expected the schedules in the order of their dates, each date once, got "
                f"{', '.join(map(str, dates))}."
            )
        return self


@dataclass(frozen=True, slots=True)
class RunFees:
    """The fee table a run prices its fills with (F-FEE-01): each fee in force from its date,
    in days since 1970-01-01, until the next one's, the first also before its date."""

    schedules: tuple[tuple[int, FuturesFee | CryptoFee], ...]

    @classmethod
    def of(cls, fees: FuturesFee | CryptoFee | DatedFees) -> "RunFees":
        """A scenario's fees: its dated table, or one fee in force on every date."""
        if isinstance(fees, DatedFees):
            dated = ((day_number(schedule.effective_from), schedule) for schedule in fees.schedules)
            return cls(tuple(dated))
        return cls(((day_number(date.min), fees),))

    @classmethod
    def of_table(cls, table: FeeTable, root: str) -> "RunFees":
        """The schedules of a named fee table (`fefat.market.fees`) for `root`, each from its
        date, as a run prices its fills with them (F-FEE-01); a schedule without `root` is
        refused, since no default would price its dates."""
        unpriced = [
            str(schedule.effective_from)
            for schedule in table.schedules
            if root not in schedule.fees
        ]
        if unpriced:
            raise ValueError(
                f"Expected {table.name} to price {root} in every schedule, got none from "
                f"{', '.join(unpriced)}."
            )
        dated = (
            (day_number(schedule.effective_from), schedule.fees[root])
            for schedule in table.schedules
        )
        return cls(tuple(dated))

    def in_force(self, trade_date: int) -> tuple[FuturesFee | CryptoFee, bool]:
        """The fee in force on `trade_date`, in days since 1970-01-01, and whether it is the
        first schedule's, taken before its date, which the run warns of (F-FEE-01)."""
        in_force = [fee for effective_from, fee in self.schedules if effective_from <= trade_date]
        if in_force:
            return in_force[-1], False
        return self.schedules[0][1], True


def fee_of(
    fees: RunFees | None,
    trade_date: int,
    value: Fraction,
    quantity: Decimal,
    liquidity: Liquidity,
) -> tuple[Fraction, bool]:
    """The exact fee of a fill of `quantity` in the instrument's units worth `value`, on
    `trade_date`, in days since 1970-01-01, before it is rounded (F-FEE-03), and whether the fee
    table's first schedule priced it before its date: a futures fee per contract per side
    (F-FEE-01), a crypto fee in basis points of the value (F-FEE-02), and none without a fee
    table."""
    if fees is None:
        return Fraction(0), False
    fee, extended = fees.in_force(trade_date)
    if isinstance(fee, FuturesFee):
        return f_fee_01(fee, quantity), extended
    return f_fee_02(fee, value, liquidity), extended


def funding_in_order(rates: Sequence[FundingRate]) -> None:
    """A run's funding times in order, each once, as the Rust engine takes them (F-FND-01): a
    time out of order or repeated is refused rather than sorted or paid twice."""
    times = [rate.ts for rate in rates]
    if any(later <= earlier for earlier, later in itertools.pairwise(times)):
        listed = ", ".join(instant_text(at) for at in times)
        raise ValueError(f"Expected the funding times in order, each once, got {listed}.")
