"""Fee tables: what a run pays per trade, by date (`02-engine-and-data.md` §1.2 and §3).

A fee table is named for a broker, a prop firm, or a venue, and a run names one. It holds
schedules, each in force from its `effective_from` until the next one starts, and each
prices instrument roots (`fefat.market.instruments`): a futures contract per side in US
dollars, every charge summed, and crypto in basis points of the traded value, maker for an
order that rests on the book and taker for one that takes liquidity. A schedule starts on
the first day its fees are known to apply, so a date before a table's first schedule is
refused rather than priced with fees nobody published:

    lookup("retail-default", "ES", date(2026, 10, 13)).per_contract_side  # Decimal("2.87")
"""

import itertools
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fefat.market.layout import FolderName
from fefat.market.schema import FrozenModel


class FuturesFee(FrozenModel):
    """What one futures contract costs per side, in US dollars: exchange and clearing,
    regulatory, and broker charges, summed."""

    kind: Literal["futures"] = "futures"
    per_contract_side: Decimal = Field(ge=0)


class CryptoFee(FrozenModel):
    """What a crypto trade costs, in basis points of its value: `maker_bps` for an order that
    rests on the book, `taker_bps` for one that takes liquidity (negative for a rebate)."""

    kind: Literal["crypto"] = "crypto"
    maker_bps: Decimal
    taker_bps: Decimal


Fee = Annotated[FuturesFee | CryptoFee, Field(discriminator="kind")]
"""A fee as a model field: a futures or a crypto fee, told apart by `kind`."""


class FeeSchedule(FrozenModel):
    """The fee of each instrument root, in force from `effective_from` until the table's next
    schedule. It compares by value but cannot be hashed, since its fees are a mapping."""

    effective_from: date
    sources: tuple[str, ...] = Field(min_length=1)
    fees: Mapping[FolderName, Fee] = Field(min_length=1)


class FeeTable(FrozenModel):
    """A broker's, a prop firm's, or a venue's fees over time; a run names one by `name`."""

    name: str = Field(min_length=1)
    schedules: tuple[FeeSchedule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _schedules_take_effect_in_order(self) -> Self:
        dates = [schedule.effective_from for schedule in self.schedules]
        if any(later <= earlier for earlier, later in itertools.pairwise(dates)):
            raise ValueError(
                f"Expected the schedules of {self.name} in order of their effective dates, "
                f"each date once, got {', '.join(map(str, dates))}."
            )
        return self

    def lookup(self, root: str, on: date) -> FuturesFee | CryptoFee:
        """The fee of `root` in the schedule in force on `on`."""
        in_force = [schedule for schedule in self.schedules if schedule.effective_from <= on]
        if not in_force:
            raise ValueError(
                f"Expected a schedule of {self.name} in force on {on}, got the first from "
                f"{self.schedules[0].effective_from}."
            )
        schedule = in_force[-1]
        if root not in schedule.fees:
            raise ValueError(
                f"Expected a root priced by {self.name} from {schedule.effective_from} "
                f"({', '.join(sorted(schedule.fees))}), got {root!r}."
            )
        return schedule.fees[root]


_CME_EXCHANGE_FEES_FROM_2026_07_20 = {
    "ES": "1.38",
    "NQ": "1.38",
    "CL": "1.50",
    "GC": "1.65",
    "MES": "0.35",
    "MNQ": "0.35",
    "MCL": "0.50",
    "MGC": "0.70",
}
_CME_EXCHANGE_FEES_FROM_2026_10_01 = {**_CME_EXCHANGE_FEES_FROM_2026_07_20, "MCL": "0.60"}
_CME_AND_NFA_FEE_CHANGES = (
    (date(2026, 7, 20), _CME_EXCHANGE_FEES_FROM_2026_07_20, "0.01"),
    (date(2026, 10, 1), _CME_EXCHANGE_FEES_FROM_2026_10_01, "0.01"),
    (date(2027, 7, 1), _CME_EXCHANGE_FEES_FROM_2026_10_01, "0.02"),
)
"""When CME's non-member exchange and clearing fees or NFA's assessment changed, with the fees
per side from then: metals rose on 2026-07-20, MCL on 2026-10-01, and NFA's fee doubles on
2027-07-01."""

_CME_FEE_SOURCES = (
    "https://www.cmegroup.com/company/clearing-fees/fee-finder.html",
    "https://help.topstep.com/en/articles/8284213-topstepx-commissions-and-fees",
    "https://www.tradestation.com/pricing/exchange-execution-and-clearing-fees/",
    "https://www.nfa.futures.org/faqs/members/nfa-assessment-fees.html",
)


def _by_size(standard: str, micro: str) -> dict[str, str]:
    """A charge per root: one for the standard contracts and one for the micros."""
    return {root: standard for root in ("ES", "NQ", "CL", "GC")} | {
        root: micro for root in ("MES", "MNQ", "MCL", "MGC")
    }


def _futures_table(
    name: str, commission: Mapping[str, str], broker_clearing: str, sources: tuple[str, ...]
) -> FeeTable:
    """A table with a schedule from each change of CME's or NFA's fees, charging per contract
    per side CME's fee, NFA's assessment, the broker's clearing fee, and its commission."""
    return FeeTable(
        name=name,
        schedules=tuple(
            FeeSchedule(
                effective_from=effective_from,
                sources=sources,
                fees={
                    root: FuturesFee(
                        per_contract_side=Decimal(exchange_fee)
                        + Decimal(nfa_fee)
                        + Decimal(broker_clearing)
                        + Decimal(commission[root])
                    )
                    for root, exchange_fee in exchange_fees.items()
                },
            )
            for effective_from, exchange_fees, nfa_fee in _CME_AND_NFA_FEE_CHANGES
        ),
    )


RETAIL_DEFAULT = _futures_table(
    "retail-default",
    commission=_by_size(standard="1.29", micro="0.39"),
    broker_clearing="0.19",
    sources=(
        "https://ninjatrader.com/pricing/commissions/",
        "https://ninjatrader.com/futures/blogs/how-much-does-ninjatrader-cost",
        *_CME_FEE_SOURCES,
    ),
)
"""A generic retail broker, priced as NinjaTrader's free plan: a commission of $1.29 per side
for a standard contract and $0.39 for a micro, and its clearing fee of $0.19."""

PROP_TOPSTEP = _futures_table(
    "prop-topstep",
    commission=_by_size(standard="0.50", micro="0.25"),
    broker_clearing="0",
    sources=_CME_FEE_SOURCES,
)
"""Topstep's accounts on TopstepX: a commission of $0.50 per side for a standard contract and
$0.25 for a micro, with the exchange and NFA fees passed on. The other prop firms' tables
arrive with their rule sets."""

BINANCE_DEFAULT = FeeTable(
    name="binance-default",
    schedules=(
        FeeSchedule(
            effective_from=date(2026, 5, 1),
            sources=(
                "https://www.binance.com/en/support/articles/360033544231",
                "https://www.binance.com/en/fee/trading",
            ),
            fees={
                "BTCUSDT-PERP": CryptoFee(maker_bps=Decimal(2), taker_bps=Decimal(5)),
                "ETHUSDT-PERP": CryptoFee(maker_bps=Decimal(2), taker_bps=Decimal(5)),
                "BTCUSDT": CryptoFee(maker_bps=Decimal(10), taker_bps=Decimal(10)),
                "ETHUSDT": CryptoFee(maker_bps=Decimal(10), taker_bps=Decimal(10)),
            },
        ),
    ),
)
"""Binance for a regular user (VIP 0) paying without BNB: USD-M perpetuals 0.02 % maker and
0.05 % taker, spot 0.1 % either way."""

TABLES: Mapping[str, FeeTable] = {
    table.name: table for table in (RETAIL_DEFAULT, PROP_TOPSTEP, BINANCE_DEFAULT)
}
"""The fee tables a run can name."""


def lookup(table_name: str, root: str, on: date) -> FuturesFee | CryptoFee:
    """The fee of `root` on `on` in the table a run names: `lookup("retail-default", "ES",
    on).per_contract_side` is what one ES contract costs per side."""
    if table_name not in TABLES:
        raise ValueError(f"Expected a fee table ({', '.join(sorted(TABLES))}), got {table_name!r}.")
    return TABLES[table_name].lookup(root, on)
