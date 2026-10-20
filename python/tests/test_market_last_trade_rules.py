"""The last trade dates of the catalog products' contracts by their rules (step 1.7), against
the dates the exchanges' rules give: the MCL and MGC dates are those futuresspecs.com lists for
2026 and 2027."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fefat.market import instruments
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.instruments import Currency, Instrument, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.layout import YearMonth


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")


def sessions_of_root(root: str, cache: Path) -> SessionTable:
    return sessions_of(instruments.get(root).session_calendar(), cache)


@pytest.mark.parametrize(
    ("root", "year", "month", "last_trade_date"),
    [
        # The third Friday of the contract month.
        ("MES", 2026, 3, date(2026, 3, 20)),
        ("ES", 2026, 12, date(2026, 12, 18)),
        ("MNQ", 2026, 9, date(2026, 9, 18)),
        # Juneteenth, Friday 2026-06-19, the third Friday of June, has no trade date.
        ("MES", 2026, 6, date(2026, 6, 18)),
        # Four business days before the 25th of the month before: Wednesday 2026-11-25.
        ("MCL", 2026, 12, date(2026, 11, 19)),
        # The 25th is a Sunday, so four before Friday the 23rd.
        ("MCL", 2026, 11, date(2026, 10, 19)),
        # The 25th is Christmas, so four before Thursday the 24th.
        ("MCL", 2027, 1, date(2026, 12, 18)),
        # Crude oil ends one business day after its micro.
        ("CL", 2026, 12, date(2026, 11, 20)),
        # The third-last business day of the contract month.
        ("MGC", 2026, 10, date(2026, 10, 28)),
        ("MGC", 2026, 12, date(2026, 12, 29)),
        ("GC", 2027, 8, date(2027, 8, 27)),
    ],
)
def test_each_futures_product_ends_its_contracts_by_its_rule(
    cache: Path, root: str, year: int, month: int, last_trade_date: date
) -> None:
    contract_month = YearMonth(year=year, month=month)

    found = instruments.get(root).last_trade_date(contract_month, sessions_of_root(root, cache))

    assert found == last_trade_date


def test_spot_and_perpetuals_have_no_last_trade_date(cache: Path) -> None:
    sessions = sessions_of(BUILT_IN[CalendarId.CRYPTO_24X7], cache)

    for root in ("BTCUSDT", "BTCUSDT-PERP"):
        with pytest.raises(ValueError, match=f"got the .* {root}, which never expires"):
            instruments.get(root).last_trade_date(YearMonth(year=2026, month=3), sessions)


def instrument(kind: InstrumentKind, last_trade_rule: ThirdFriday | None) -> Instrument:
    return Instrument(
        root="ES",
        kind=kind,
        tick_size=Decimal("0.25"),
        point_value=Decimal(50),
        lot_step=Decimal(1),
        currency=Currency.USD,
        calendar=CalendarId.CME_EQUITY_INDEX,
        valid_from=date(1997, 9, 9),
        valid_to=None,
        last_trade_rule=last_trade_rule,
        sources=("https://www.cmegroup.com/markets",),
    )


def test_futures_need_a_last_trade_rule_and_nothing_else_has_one() -> None:
    with pytest.raises(ValueError, match="Expected a last trade rule for the futures ES"):
        instrument(InstrumentKind.FUTURES, None)
    with pytest.raises(ValueError, match="Expected no last trade rule for the spot ES"):
        instrument(InstrumentKind.SPOT, ThirdFriday())
