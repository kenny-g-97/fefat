"""Instrument specifications: how a product's price and quantity move and what a move is
worth, dated so that a change applies from its day (`02-engine-and-data.md` §1.2).

An instrument is keyed by its root: the exchange's product code for futures (`ES`), the
venue's symbol for crypto spot (`BTCUSDT`), and that symbol with `-PERP` for a perpetual
(`BTCUSDT-PERP`). Quantities count contracts for futures and the base asset for crypto (BTC
for `BTCUSDT`), in steps of `lot_step`; `point_value` is what one unit of quantity gains, in
`currency`, when the price rises by 1. Each version holds from `valid_from` until the day
before `valid_to` (open-ended without one), and a root's first version starts on the
product's first trade date. A futures product's contracts end by its `last_trade_rule`
(`fefat.market.last_trade_rules`). `get("ES")` reads the static table below, where each version
names its sources. The contracts of a futures root are `fefat.market.contracts`; what a run
pays per trade is `fefat.market.fees`, since a run names its fee table.
"""

import itertools
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from fefat.market.calendar import SessionTable
from fefat.market.calendar_definition import CalendarId
from fefat.market.last_trade_rules import (
    BusinessDaysBeforeThe25th,
    LastTradeRule,
    ThirdFriday,
    ThirdLastBusinessDay,
)
from fefat.market.layout import FolderName, YearMonth
from fefat.market.schema import FrozenModel


class InstrumentKind(StrEnum):
    """What trades: a dated futures contract, a perpetual swap, or the asset itself."""

    FUTURES = "futures"
    PERPETUAL = "perpetual"
    SPOT = "spot"


class Currency(StrEnum):
    """The currency of an instrument's prices and of what a point is worth."""

    USD = "USD"
    USDT = "USDT"


class Instrument(FrozenModel):
    """One version of a product's specification, in force from `valid_from` until the day
    before `valid_to`. `calendar_id` names its session calendar, one of the built-in
    calendars of `fefat.market.builtin_calendars`; a futures product's contracts end by its
    `last_trade_rule`, and spot pairs and perpetuals, which never expire, have none."""

    root: FolderName
    kind: InstrumentKind
    tick_size: Decimal = Field(gt=0)
    point_value: Decimal = Field(gt=0)
    lot_step: Decimal = Field(gt=0)
    currency: Currency
    calendar_id: CalendarId
    last_trade_rule: LastTradeRule | None
    valid_from: date
    valid_to: date | None
    sources: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError(
                f"Expected {self.root}'s valid_to after its valid_from {self.valid_from}, "
                f"got {self.valid_to}."
            )
        return self

    @model_validator(mode="after")
    def _futures_end_by_a_rule(self) -> Self:
        futures = self.kind is InstrumentKind.FUTURES
        if futures == (self.last_trade_rule is not None):
            return self
        expected = "a last trade rule" if futures else "no last trade rule"
        raise ValueError(
            f"Expected {expected} for the {self.kind} {self.root}, got {self.last_trade_rule!r}."
        )

    def in_force_on(self, day: date) -> bool:
        """Whether this version applies on `day`."""
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)

    def last_trade_date(self, contract_month: YearMonth, sessions: SessionTable) -> date:
        """The last trade date of the contract of `contract_month`, by the product's rule, in
        the sessions of its calendar."""
        if self.last_trade_rule is None:
            raise ValueError(
                f"Expected a futures product, whose contracts end by a rule, got the {self.kind} "
                f"{self.root}, which never expires."
            )
        return self.last_trade_rule.last_trade_date(contract_month, sessions)


class InstrumentTable(FrozenModel):
    """Every version of every instrument; the versions of one root never overlap."""

    versions: tuple[Instrument, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _versions_of_a_root_do_not_overlap(self) -> Self:
        ordered = sorted(self.versions, key=lambda version: (version.root, version.valid_from))
        for earlier, later in itertools.pairwise(ordered):
            overlaps = earlier.valid_to is None or earlier.valid_to > later.valid_from
            if earlier.root == later.root and overlaps:
                raise ValueError(
                    f"Expected each version of {earlier.root} to end on or before the next "
                    f"starts, got one from {earlier.valid_from} with valid_to "
                    f"{earlier.valid_to} and the next from {later.valid_from}."
                )
        return self

    def roots(self) -> tuple[str, ...]:
        """The roots of the table, sorted."""
        return tuple(sorted({version.root for version in self.versions}))

    def first_trade_date(self, root: str) -> date:
        """The day `root` began trading: the start of its first version."""
        return self._versions_of(root)[0].valid_from

    def get(self, root: str, on: date | None = None) -> Instrument:
        """The version of `root` in force on `on`, or its newest version without a date."""
        versions = self._versions_of(root)
        if on is None:
            return versions[-1]
        in_force = [version for version in versions if version.in_force_on(on)]
        if in_force:
            return in_force[0]
        first_trade_date = versions[0].valid_from
        if on < first_trade_date:
            raise ValueError(
                f"Expected a date on or after {first_trade_date}, when {root} began trading, "
                f"got {on}."
            )
        raise ValueError(
            f"Expected a date when a version of {root} was in force, got {on}, outside all of them."
        )

    def _versions_of(self, root: str) -> list[Instrument]:
        """The versions of `root`, oldest first; an unknown root is refused."""
        versions = sorted(
            (version for version in self.versions if version.root == root),
            key=lambda version: version.valid_from,
        )
        if not versions:
            raise ValueError(
                f"Expected a root of the instrument table ({', '.join(self.roots())}), "
                f"got {root!r}."
            )
        return versions


def _cme_futures(
    root: str,
    tick_size: str,
    point_value: str,
    calendar_id: CalendarId,
    last_trade_rule: LastTradeRule,
    first_trade_date: date,
    sources: tuple[str, ...],
) -> Instrument:
    return Instrument(
        root=root,
        kind=InstrumentKind.FUTURES,
        tick_size=Decimal(tick_size),
        point_value=Decimal(point_value),
        lot_step=Decimal(1),
        currency=Currency.USD,
        calendar_id=calendar_id,
        last_trade_rule=last_trade_rule,
        valid_from=first_trade_date,
        valid_to=None,
        sources=sources,
    )


def _binance(
    root: str,
    kind: InstrumentKind,
    tick_size: str,
    lot_step: str,
    first_trade_date: date,
    sources: tuple[str, ...],
) -> Instrument:
    return Instrument(
        root=root,
        kind=kind,
        tick_size=Decimal(tick_size),
        point_value=Decimal(1),
        lot_step=Decimal(lot_step),
        currency=Currency.USDT,
        calendar_id=CalendarId.CRYPTO_24X7,
        last_trade_rule=None,
        valid_from=first_trade_date,
        valid_to=None,
        sources=sources,
    )


_CME_SPECIFICATIONS = "https://www.cmegroup.com/markets"
_MICRO_E_MINI_LAUNCH = (
    "https://www.cmegroup.com/media-room/press-releases/2019/5/07/"
    "micro_e-mini_futuresmakebigimpressiononfirstdayoftrading.html"
)
_MICRO_E_MINI_FAQ = (
    "https://www.cmegroup.com/articles/faqs/"
    "micro-e-mini-equity-index-futures-frequently-asked-questions.html"
)
_BINANCE_SPOT_SYMBOLS = "https://api.binance.com/api/v3/exchangeInfo"
_BINANCE_SPOT_KLINES = "https://data.binance.vision/?prefix=data/spot/monthly/klines"
_BINANCE_PERPETUAL_SYMBOLS = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# shortcut: one version per product, today's specification from its first trade date; add
# older versions where a tick size or lot step changed when data of those years is imported.
STATIC_TABLE = InstrumentTable(
    versions=(
        _cme_futures(
            "ES",
            "0.25",
            "50",
            CalendarId.CME_EQUITY_INDEX,
            ThirdFriday(),
            date(1997, 9, 9),
            sources=(
                f"{_CME_SPECIFICATIONS}/equities/sp/e-mini-sandp500.contractSpecs.html",
                "https://www.cmegroup.com/education/articles-and-reports/"
                "the-origins-of-the-e-mini-sp-500.html",
                "https://mondovisione.com/media-and-resources/news/"
                "cme-celebrates-10th-anniversary-of-globexsup-sup-electronic-trading-on-heels-of--2011124/",
            ),
        ),
        _cme_futures(
            "NQ",
            "0.25",
            "20",
            CalendarId.CME_EQUITY_INDEX,
            ThirdFriday(),
            date(1999, 6, 21),
            sources=(
                f"{_CME_SPECIFICATIONS}/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html",
                "https://www.cmegroup.com/openmarkets/equity-index/2024/"
                "The-Growth-of-Tech-and-25-Years-of-Nasdaq-Futures.html",
                "https://mondovisione.com/media-and-resources/news/"
                "cme-nasdaq-mark-five-years-of-growth-in-emini-nasdaq100-futures-2011124/",
            ),
        ),
        _cme_futures(
            "CL",
            "0.01",
            "1000",
            CalendarId.CME_ENERGY,
            BusinessDaysBeforeThe25th(business_days=3),
            date(1983, 3, 30),
            sources=(
                f"{_CME_SPECIFICATIONS}/energy/crude-oil/light-sweet-crude.contractSpecs.html",
                "https://www.tradingview.com/chart/CL1!/"
                "vMhz9nKG-Special-Report-Celebrating-40-Years-of-Crude-Oil-Futures/",
                "https://www.institutionalinvestor.com/article/2bstpyy7coeu0g78sunsw/innovation/"
                "how-wti-became-the-most-important-commodity-contract-on-the-planet",
            ),
        ),
        _cme_futures(
            "GC",
            "0.10",
            "100",
            CalendarId.CME_METALS,
            ThirdLastBusinessDay(),
            date(1974, 12, 31),
            sources=(
                f"{_CME_SPECIFICATIONS}/metals/precious/gold.contractSpecs.html",
                "https://www.cmegroup.com/education/modules/files/metals_sales_brochure.pdf",
            ),
        ),
        _cme_futures(
            "MES",
            "0.25",
            "5",
            CalendarId.CME_EQUITY_INDEX,
            ThirdFriday(),
            date(2019, 5, 6),
            sources=(
                f"{_CME_SPECIFICATIONS}/equities/sp/micro-e-mini-sandp-500.contractSpecs.html",
                _MICRO_E_MINI_LAUNCH,
                _MICRO_E_MINI_FAQ,
            ),
        ),
        _cme_futures(
            "MNQ",
            "0.25",
            "2",
            CalendarId.CME_EQUITY_INDEX,
            ThirdFriday(),
            date(2019, 5, 6),
            sources=(
                f"{_CME_SPECIFICATIONS}/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html",
                _MICRO_E_MINI_LAUNCH,
                _MICRO_E_MINI_FAQ,
            ),
        ),
        _cme_futures(
            "MCL",
            "0.01",
            "100",
            CalendarId.CME_ENERGY,
            BusinessDaysBeforeThe25th(business_days=4),
            date(2021, 7, 12),
            sources=(
                f"{_CME_SPECIFICATIONS}/energy/crude-oil/micro-wti-crude-oil.contractSpecs.html",
                "https://www.cmegroup.com/education/articles-and-reports/"
                "micro-wti-crude-oil-futures-faq.html",
                "https://www.cftc.gov/filings/ptc/ptc060721nymexdcm001.pdf",
            ),
        ),
        _cme_futures(
            "MGC",
            "0.10",
            "10",
            CalendarId.CME_METALS,
            ThirdLastBusinessDay(),
            date(2010, 10, 4),
            sources=(
                f"{_CME_SPECIFICATIONS}/metals/precious/e-micro-gold.contractSpecs.html",
                "https://www.cmegroup.com/media-room/press-releases/2010/9/09/"
                "cme_group_announceslaunchofe-microgoldcontracts.html",
                "https://www.cmegroup.com/rulebook/COMEX/1a/120.pdf",
            ),
        ),
        _binance(
            "BTCUSDT",
            InstrumentKind.SPOT,
            "0.01",
            "0.00001",
            date(2017, 8, 17),
            sources=(f"{_BINANCE_SPOT_SYMBOLS}?symbol=BTCUSDT", f"{_BINANCE_SPOT_KLINES}/BTCUSDT/"),
        ),
        _binance(
            "ETHUSDT",
            InstrumentKind.SPOT,
            "0.01",
            "0.0001",
            date(2017, 8, 17),
            sources=(f"{_BINANCE_SPOT_SYMBOLS}?symbol=ETHUSDT", f"{_BINANCE_SPOT_KLINES}/ETHUSDT/"),
        ),
        _binance(
            "BTCUSDT-PERP",
            InstrumentKind.PERPETUAL,
            "0.10",
            "0.001",
            date(2019, 9, 8),
            sources=(_BINANCE_PERPETUAL_SYMBOLS,),
        ),
        _binance(
            "ETHUSDT-PERP",
            InstrumentKind.PERPETUAL,
            "0.01",
            "0.001",
            date(2019, 11, 27),
            sources=(_BINANCE_PERPETUAL_SYMBOLS,),
        ),
    )
)
"""The products FEFAT knows, CME's futures and their micros with Binance's spot and
perpetual pairs, each version with the specification and first trade date its sources state
(Binance's perpetuals: the `onboardDate` of `exchangeInfo`)."""


def get(root: str, on: date | None = None) -> Instrument:
    """The specification of `root` in force on `on`, or its newest without a date, from the
    static table: `get("ES").tick_size` is 0.25 and `get("ES").point_value` 50."""
    return STATIC_TABLE.get(root, on)
