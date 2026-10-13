import re
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

from fefat.market.contracts import (
    SYMBOLOGY_COLUMNS,
    Contract,
    ContractResolver,
    IdentitySource,
    expiry_month,
    is_outright,
)
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import YearMonth
from fefat.market.schema import parse_schema_name, polars_schema

DEFINITIONS_COLUMNS = polars_schema(parse_schema_name("definitions"))
NO_DEFINITIONS = pl.DataFrame(schema=DEFINITIONS_COLUMNS)
NO_SYMBOLOGY = pl.DataFrame(schema=SYMBOLOGY_COLUMNS)


def nanoseconds(moment: datetime) -> int:
    return int(moment.timestamp()) * 1_000_000_000


def definition(
    raw_symbol: str,
    instrument_id: int,
    *,
    asset: str,
    listed: datetime,
    expires: datetime,
    maturity: tuple[int | None, int | None],
    instrument_class: str = "F",
) -> dict[str, Any]:
    return {
        "ts_recv": nanoseconds(listed),
        "ts_event": nanoseconds(listed),
        "instrument_id": instrument_id,
        "raw_symbol": raw_symbol,
        "asset": asset,
        "exchange": "XCME",
        "currency": "USD",
        "instrument_class": instrument_class,
        "security_type": "FUT",
        "min_price_increment": 250_000_000,
        "display_factor": 1_000_000_000,
        "unit_of_measure": "IPNT",
        "unit_of_measure_qty": 50_000_000_000,
        "expiration": nanoseconds(expires),
        "activation": nanoseconds(listed),
        "maturity_year": maturity[0],
        "maturity_month": maturity[1],
    }


def esz6_of_2016(instrument_id: int) -> dict[str, Any]:
    return definition(
        "ESZ6",
        instrument_id,
        asset="ES",
        listed=datetime(2015, 9, 18, 21, tzinfo=UTC),
        expires=datetime(2016, 12, 16, 14, 30, tzinfo=UTC),
        maturity=(2016, 12),
    )


def esz6_of_2026(instrument_id: int) -> dict[str, Any]:
    return definition(
        "ESZ6",
        instrument_id,
        asset="ES",
        listed=datetime(2025, 9, 19, 21, tzinfo=UTC),
        expires=datetime(2026, 12, 18, 14, 30, tzinfo=UTC),
        maturity=(2026, 12),
    )


def definition_frame(*rows: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=DEFINITIONS_COLUMNS)


def symbology_frame(*intervals: tuple[str, int, date, date]) -> pl.DataFrame:
    return pl.DataFrame(list(intervals), schema=SYMBOLOGY_COLUMNS, orient="row")


def resolver_of(
    definitions: pl.DataFrame = NO_DEFINITIONS, symbology: pl.DataFrame = NO_SYMBOLOGY
) -> ContractResolver:
    return ContractResolver(definitions=definitions, symbology=symbology, instruments=STATIC_TABLE)


MGCG1_TWICE = symbology_frame(
    ("MGCG1", 5001, date(2010, 9, 12), date(2011, 2, 24)),
    ("MGCG1", 5002, date(2020, 8, 30), date(2021, 2, 25)),
)


@pytest.mark.parametrize("id_in_2026", [4242, 42])
def test_esz6_in_2016_and_2026_are_two_contracts_by_instrument_id_and_day(id_in_2026: int) -> None:
    contracts = resolver_of(definition_frame(esz6_of_2016(42), esz6_of_2026(id_in_2026)))

    of_2016 = contracts.by_instrument_id(42, date(2016, 6, 1))
    of_2026 = contracts.by_instrument_id(id_in_2026, date(2026, 6, 1))

    assert of_2016 == Contract(
        root="ES",
        expiry=YearMonth(year=2016, month=12),
        first_trade_date=date(2015, 9, 18),
        last_trade_date=date(2016, 12, 16),
        raw_symbols=("ESZ6",),
        identity_source=IdentitySource.DEFINITIONS,
    )
    assert (str(of_2016), str(of_2026)) == ("ESZ2016", "ESZ2026")
    assert of_2026.identity_source is IdentitySource.DEFINITIONS


@pytest.mark.parametrize(
    ("on", "label", "source"),
    [
        (date(2016, 6, 1), "ESZ2016", IdentitySource.DEFINITIONS),
        (date(2026, 6, 1), "ESZ2026", IdentitySource.DEFINITIONS),
        (date(2020, 1, 2), "ESZ2026", IdentitySource.STATIC_TABLE),
    ],
)
def test_esz6_by_symbol_and_day_is_the_contract_alive_that_day(
    on: date, label: str, source: IdentitySource
) -> None:
    contracts = resolver_of(definition_frame(esz6_of_2016(42), esz6_of_2026(4242)))

    contract = contracts.by_symbol("ESZ6", on)

    assert (str(contract), contract.identity_source) == (label, source)


def test_a_definition_answers_until_its_expiration_day() -> None:
    contracts = resolver_of(definition_frame(esz6_of_2016(42)))

    assert str(contracts.by_instrument_id(42, date(2016, 12, 16))) == "ESZ2016"
    with pytest.raises(ValueError, match="covering instrument_id 42 on 2016-12-17"):
        contracts.by_instrument_id(42, date(2016, 12, 17))


def test_two_instruments_alive_for_one_symbol_on_one_day_are_refused() -> None:
    twice = resolver_of(definition_frame(esz6_of_2016(42), esz6_of_2016(43)))

    with pytest.raises(ValueError, match=re.escape("got the instrument_ids 42, 43.")):
        twice.by_symbol("ESZ6", date(2016, 6, 1))


def test_a_spread_is_refused_by_instrument_id_and_by_symbol() -> None:
    spread = definition(
        "ESZ6-ESH7",
        77,
        asset="ES",
        listed=datetime(2015, 12, 18, 21, tzinfo=UTC),
        expires=datetime(2016, 12, 16, 14, 30, tzinfo=UTC),
        maturity=(2016, 12),
        instrument_class="S",
    )
    contracts = resolver_of(definition_frame(spread))

    with pytest.raises(ValueError, match="Expected an outright future"):
        contracts.by_instrument_id(77, date(2016, 6, 1))
    with pytest.raises(ValueError, match="Expected an outright symbol"):
        contracts.by_symbol("ESZ6-ESH7", date(2016, 6, 1))


def test_a_definition_without_a_maturity_is_refused_with_its_instrument_id() -> None:
    unstated = definition(
        "ESZ6",
        42,
        asset="ES",
        listed=datetime(2015, 9, 18, 21, tzinfo=UTC),
        expires=datetime(2016, 12, 16, 14, 30, tzinfo=UTC),
        maturity=(None, None),
    )
    expected = (
        "Expected the definition of instrument_id 42 (ESZ6) to state maturity_year, "
        "maturity_month, got null."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolver_of(definition_frame(unstated)).by_instrument_id(42, date(2016, 6, 1))


def test_clf7_belongs_to_january_2017_by_maturity_and_by_inference() -> None:
    clf7 = definition(
        "CLF7",
        7,
        asset="CL",
        listed=datetime(2010, 6, 6, tzinfo=UTC),
        expires=datetime(2016, 12, 20, 19, 30, tzinfo=UTC),
        maturity=(2017, 1),
    )
    by_definition = resolver_of(definition_frame(clf7))
    by_symbology = resolver_of(
        symbology=symbology_frame(("CLF7", 7, date(2010, 6, 6), date(2016, 12, 21)))
    )

    assert str(by_definition.by_instrument_id(7, date(2016, 6, 1))) == "CLF2017"
    assert str(by_symbology.by_instrument_id(7, date(2016, 6, 1))) == "CLF2017"


@pytest.mark.parametrize(
    ("instrument_id", "on", "expected"),
    [
        (
            5001,
            date(2011, 1, 3),
            Contract(
                root="MGC",
                expiry=YearMonth(year=2011, month=2),
                first_trade_date=date(2010, 9, 12),
                last_trade_date=date(2011, 2, 23),
                raw_symbols=("MGCG1",),
                identity_source=IdentitySource.SYMBOLOGY,
            ),
        ),
        (
            5002,
            date(2021, 1, 4),
            Contract(
                root="MGC",
                expiry=YearMonth(year=2021, month=2),
                first_trade_date=date(2020, 8, 30),
                last_trade_date=date(2021, 2, 24),
                raw_symbols=("MGCG1",),
                identity_source=IdentitySource.SYMBOLOGY,
            ),
        ),
    ],
)
def test_symbology_resolves_a_reused_symbol_by_its_interval(
    instrument_id: int, on: date, expected: Contract
) -> None:
    contracts = resolver_of(symbology=MGCG1_TWICE)

    assert contracts.by_instrument_id(instrument_id, on) == expected
    assert contracts.by_symbol("MGCG1", on) == expected


def test_an_interval_excludes_its_end_date() -> None:
    contracts = resolver_of(symbology=MGCG1_TWICE)

    assert str(contracts.by_instrument_id(5001, date(2011, 2, 23))) == "MGCG2011"
    with pytest.raises(ValueError, match="covering instrument_id 5001 on 2011-02-24"):
        contracts.by_instrument_id(5001, date(2011, 2, 24))


def test_two_intervals_covering_one_day_are_refused() -> None:
    overlapping = symbology_frame(
        ("MGCG1", 5001, date(2010, 9, 12), date(2011, 2, 24)),
        ("MGCZ0", 5001, date(2010, 12, 1), date(2010, 12, 30)),
    )

    with pytest.raises(ValueError, match="Expected one symbology interval covering 2010-12-01"):
        resolver_of(symbology=overlapping).by_instrument_id(5001, date(2010, 12, 1))


@pytest.mark.parametrize(
    ("raw_symbol", "first_seen", "last_seen", "expected"),
    [
        ("ESZ6", date(2015, 9, 18), date(2016, 12, 16), YearMonth(year=2016, month=12)),
        ("CLZ6", date(2016, 11, 22), date(2026, 9, 22), YearMonth(year=2026, month=12)),
        ("MGCZ5", date(2024, 1, 2), date(2026, 1, 1), YearMonth(year=2025, month=12)),
        ("MGCG1", date(2010, 9, 12), date(2011, 2, 23), YearMonth(year=2011, month=2)),
        ("CLF7", date(2016, 1, 4), date(2016, 12, 20), YearMonth(year=2017, month=1)),
        ("ESZ6", date(2016, 6, 1), date(2016, 6, 1), YearMonth(year=2016, month=12)),
        ("ESZ6", date(2026, 6, 1), date(2026, 6, 1), YearMonth(year=2026, month=12)),
    ],
)
def test_expiry_month_takes_the_first_decade_the_dates_allow(
    raw_symbol: str, first_seen: date, last_seen: date, expected: YearMonth
) -> None:
    assert expiry_month(raw_symbol, first_seen, last_seen) == expected


def test_expiry_month_refuses_a_spread() -> None:
    expected = "Expected an outright symbol <root><month code><year digit>, got 'MCLF2-MCLG2'."

    with pytest.raises(ValueError, match=re.escape(expected)):
        expiry_month("MCLF2-MCLG2", date(2012, 1, 3), date(2012, 1, 3))


@pytest.mark.parametrize(
    ("raw_symbol", "outright"),
    [
        ("ESZ6", True),
        ("MESH0", True),
        ("MGCG1", True),
        ("6EZ6", True),
        ("MCLF2-MCLG2", False),
        ("MCL:SA 03M F2", False),
        ("UD:1V: GN 0211848263", False),
        ("ESZ26", False),
    ],
)
def test_outrights_are_told_apart_from_spreads_and_strategies(
    raw_symbol: str, outright: bool
) -> None:
    assert is_outright(raw_symbol) is outright


@pytest.mark.parametrize(
    ("on", "expiry"),
    [
        (date(2016, 6, 1), YearMonth(year=2016, month=12)),
        (date(2026, 6, 1), YearMonth(year=2026, month=12)),
    ],
)
def test_without_definitions_or_symbology_a_symbol_resolves_from_the_static_table_and_says_so(
    on: date, expiry: YearMonth
) -> None:
    assert resolver_of().by_symbol("ESZ6", on) == Contract(
        root="ES",
        expiry=expiry,
        first_trade_date=None,
        last_trade_date=None,
        raw_symbols=("ESZ6",),
        identity_source=IdentitySource.STATIC_TABLE,
    )


def test_a_symbol_before_its_products_first_trade_date_is_refused() -> None:
    expected = "Expected a date on or after 2021-07-12, when MCL began trading, got 2012-12-16."

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolver_of().by_symbol("MCLF3", date(2012, 12, 16))


def test_a_symbol_of_a_root_outside_the_instrument_table_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected a root of the instrument table"):
        resolver_of().by_symbol("6EZ6", date(2026, 6, 1))


def test_an_instrument_id_is_refused_when_nothing_covers_it_and_says_what_is_loaded() -> None:
    expected = (
        "Expected definitions or symbology covering instrument_id 1001 on 2026-03-05, got none "
        "among the 0 definition records and 0 symbology intervals loaded."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        resolver_of().by_instrument_id(1001, date(2026, 3, 5))


@pytest.mark.parametrize(
    ("root", "expiry", "raw_symbol", "label"),
    [
        ("ES", YearMonth(year=2016, month=12), "ESZ6", "ESZ2016"),
        ("MGC", YearMonth(year=2021, month=2), "MGCG1", "MGCG2021"),
        ("CL", YearMonth(year=2017, month=1), "CLF7", "CLF2017"),
    ],
)
def test_a_contract_is_written_root_month_code_and_year(
    root: str, expiry: YearMonth, raw_symbol: str, label: str
) -> None:
    contract = Contract(
        root=root,
        expiry=expiry,
        first_trade_date=None,
        last_trade_date=None,
        raw_symbols=(raw_symbol,),
        identity_source=IdentitySource.STATIC_TABLE,
    )

    assert str(contract) == label


def test_frames_with_other_columns_are_refused() -> None:
    other = pl.DataFrame({"instrument_id": [1]}, schema={"instrument_id": pl.UInt32})

    with pytest.raises(ValueError, match=r"Expected the columns .* in the definitions"):
        ContractResolver(definitions=other, symbology=NO_SYMBOLOGY, instruments=STATIC_TABLE)
    with pytest.raises(ValueError, match=r"Expected the columns .* in the symbology"):
        ContractResolver(definitions=NO_DEFINITIONS, symbology=other, instruments=STATIC_TABLE)
