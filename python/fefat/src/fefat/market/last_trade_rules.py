"""The last trade date of a futures contract, the trade date on which its trading ends, by its
product's rule (`02-engine-and-data.md` §1.5, step 1.7).

A rule counts business days as the trade dates of the product's session calendar
(`fefat.market.calendar`), so a holiday, which has no trade date, is never one. The products
of `fefat.market.instruments` follow three rules, from their exchanges' rulebooks:

- `ThirdFriday`: equity index futures (ES, NQ, MES, MNQ) expire against the index's opening
  value on the third Friday of their month, so they end on it, or on the trade date before it
  when it has none, as on Juneteenth, Friday 2026-06-19.
- `BusinessDaysBeforeThe25th`: crude oil (CL) ends 3 business days before the 25th of the month
  before its month, or 4 when the 25th is no business day, which is 3 before the last business
  day on or before the 25th; Micro WTI (MCL) ends one business day before crude oil, 4 before.
- `ThirdLastBusinessDay`: gold (GC, MGC) ends on the third-last business day of its month.

    instruments.get("MES").last_trade_date(YearMonth(year=2026, month=6), sessions)  # 06-18
"""

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import Field

from fefat.market.calendar import SessionTable
from fefat.market.layout import YearMonth
from fefat.market.schema import FrozenModel

_FRIDAY = 4
_WEEK = timedelta(days=7)


class ThirdFriday(FrozenModel):
    """The third Friday of the contract month, or the last trade date before it when it is
    none."""

    kind: Literal["third-friday"] = "third-friday"

    def last_trade_date(self, contract_month: YearMonth, sessions: SessionTable) -> date:
        """The last trade date of the contract of `contract_month` in `sessions`."""
        first_day = _first_day(contract_month)
        first_friday = first_day + timedelta(days=(_FRIDAY - first_day.weekday()) % 7)
        third_friday = first_friday + 2 * _WEEK
        return _trade_dates(sessions, third_friday - _WEEK, third_friday)[-1]


class BusinessDaysBeforeThe25th(FrozenModel):
    """`business_days` trade dates before the last trade date on or before the 25th of the month
    before the contract month."""

    kind: Literal["business-days-before-the-25th"] = "business-days-before-the-25th"
    business_days: int = Field(ge=1, le=10)

    def last_trade_date(self, contract_month: YearMonth, sessions: SessionTable) -> date:
        """The last trade date of the contract of `contract_month` in `sessions`."""
        the_25th = (_first_day(contract_month) - timedelta(days=1)).replace(day=25)
        return _trade_dates(sessions, the_25th - 4 * _WEEK, the_25th)[-1 - self.business_days]


class ThirdLastBusinessDay(FrozenModel):
    """The third-last trade date of the contract month."""

    kind: Literal["third-last-business-day"] = "third-last-business-day"

    def last_trade_date(self, contract_month: YearMonth, sessions: SessionTable) -> date:
        """The last trade date of the contract of `contract_month` in `sessions`."""
        first_day = _first_day(contract_month)
        last_day = (first_day + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        return _trade_dates(sessions, first_day, last_day)[-3]


LastTradeRule = Annotated[
    ThirdFriday | BusinessDaysBeforeThe25th | ThirdLastBusinessDay, Field(discriminator="kind")
]
"""How a futures product's contracts end, told apart by `kind`."""


def _first_day(month: YearMonth) -> date:
    return date(month.year, month.month, 1)


def _trade_dates(sessions: SessionTable, first: date, last: date) -> list[date]:
    """The trade dates from `first` to `last`; a stretch without one is refused."""
    trade_dates: list[date] = sessions.between(first, last).get_column("trade_date").to_list()
    if not trade_dates:
        raise ValueError(f"Expected trade dates from {first} to {last} in {sessions!r}, got none.")
    return trade_dates
