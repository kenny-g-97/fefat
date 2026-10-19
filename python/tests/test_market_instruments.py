import re
from datetime import date
from decimal import Decimal

import pytest

import fefat as ff
from fefat.market.calendar_definition import CalendarId
from fefat.market.instruments import (
    STATIC_TABLE,
    Currency,
    Instrument,
    InstrumentKind,
    InstrumentTable,
)
from fefat.market.last_trade_rules import ThirdFriday

ES_SPECIFICATION = "https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html"


def es_version(tick_size: str, valid_from: date, valid_to: date | None) -> Instrument:
    return Instrument(
        root="ES",
        kind=InstrumentKind.FUTURES,
        tick_size=Decimal(tick_size),
        point_value=Decimal(50),
        lot_step=Decimal(1),
        currency=Currency.USD,
        calendar=CalendarId.CME_EQUITY_INDEX,
        last_trade_rule=ThirdFriday(),
        valid_from=valid_from,
        valid_to=valid_to,
        sources=(ES_SPECIFICATION,),
    )


A_TICK_CHANGE = InstrumentTable(
    versions=(
        es_version("0.25", date(2024, 1, 2), None),
        es_version("0.50", date(1997, 9, 9), date(2024, 1, 2)),
    )
)


@pytest.mark.parametrize(
    ("root", "kind", "tick_size", "point_value", "lot_step"),
    [
        ("ES", InstrumentKind.FUTURES, "0.25", "50", "1"),
        ("NQ", InstrumentKind.FUTURES, "0.25", "20", "1"),
        ("CL", InstrumentKind.FUTURES, "0.01", "1000", "1"),
        ("GC", InstrumentKind.FUTURES, "0.10", "100", "1"),
        ("MES", InstrumentKind.FUTURES, "0.25", "5", "1"),
        ("MNQ", InstrumentKind.FUTURES, "0.25", "2", "1"),
        ("MCL", InstrumentKind.FUTURES, "0.01", "100", "1"),
        ("MGC", InstrumentKind.FUTURES, "0.10", "10", "1"),
        ("BTCUSDT", InstrumentKind.SPOT, "0.01", "1", "0.00001"),
        ("ETHUSDT", InstrumentKind.SPOT, "0.01", "1", "0.0001"),
        ("BTCUSDT-PERP", InstrumentKind.PERPETUAL, "0.10", "1", "0.001"),
        ("ETHUSDT-PERP", InstrumentKind.PERPETUAL, "0.01", "1", "0.001"),
    ],
)
def test_ff_instruments_get_gives_each_products_specification(
    root: str, kind: InstrumentKind, tick_size: str, point_value: str, lot_step: str
) -> None:
    instrument = ff.instruments.get(root)

    assert instrument.kind is kind
    assert instrument.tick_size == Decimal(tick_size)
    assert instrument.point_value == Decimal(point_value)
    assert instrument.lot_step == Decimal(lot_step)


def test_the_static_table_seeds_the_twelve_products_each_with_https_sources() -> None:
    assert STATIC_TABLE.roots() == (
        "BTCUSDT",
        "BTCUSDT-PERP",
        "CL",
        "ES",
        "ETHUSDT",
        "ETHUSDT-PERP",
        "GC",
        "MCL",
        "MES",
        "MGC",
        "MNQ",
        "NQ",
    )
    for version in STATIC_TABLE.versions:
        assert version.sources, version.root
        assert all(source.startswith("https://") for source in version.sources), version.root


@pytest.mark.parametrize(
    ("on", "tick_size"),
    [
        (date(1997, 9, 9), "0.50"),
        (date(2024, 1, 1), "0.50"),
        (date(2024, 1, 2), "0.25"),
        (date(2030, 6, 3), "0.25"),
    ],
)
def test_get_picks_the_version_in_force_on_a_date(on: date, tick_size: str) -> None:
    assert A_TICK_CHANGE.get("ES", on).tick_size == Decimal(tick_size)


def test_get_without_a_date_gives_the_newest_version() -> None:
    assert A_TICK_CHANGE.get("ES").tick_size == Decimal("0.25")


def test_a_date_before_a_products_first_trade_date_is_refused_with_that_date() -> None:
    expected = "Expected a date on or after 2019-05-06, when MES began trading, got 2018-12-31."

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.instruments.get("MES", date(2018, 12, 31))


def test_a_date_after_a_products_last_version_ends_is_refused() -> None:
    delisted = InstrumentTable(versions=(es_version("0.25", date(1997, 9, 9), date(2030, 1, 1)),))

    with pytest.raises(ValueError, match="Expected a date when a version of ES was in force"):
        delisted.get("ES", date(2030, 1, 1))


def test_an_unknown_root_is_refused_with_the_roots_of_the_table() -> None:
    with pytest.raises(ValueError, match=re.escape("(BTCUSDT, BTCUSDT-PERP, CL, ES, ETHUSDT")):
        ff.instruments.get("ZN")


@pytest.mark.parametrize(
    "versions",
    [
        (
            es_version("0.50", date(1997, 9, 9), date(2024, 1, 3)),
            es_version("0.25", date(2024, 1, 2), None),
        ),
        (
            es_version("0.50", date(1997, 9, 9), None),
            es_version("0.25", date(2024, 1, 2), None),
        ),
    ],
)
def test_versions_of_one_root_that_overlap_are_refused(versions: tuple[Instrument, ...]) -> None:
    with pytest.raises(ValueError, match="Expected each version of ES to end"):
        InstrumentTable(versions=versions)


def test_a_version_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected ES's valid_to after its valid_from"):
        es_version("0.25", date(2024, 1, 2), date(2024, 1, 2))


def test_a_currency_fefat_does_not_know_is_refused() -> None:
    in_lowercase = {**es_version("0.25", date(1997, 9, 9), None).model_dump(), "currency": "usd"}

    with pytest.raises(ValueError, match="currency"):
        Instrument.model_validate(in_lowercase)


def test_a_calendar_that_names_no_built_in_calendar_is_refused() -> None:
    misspelled = {
        **es_version("0.25", date(1997, 9, 9), None).model_dump(),
        "calendar": "cme-equities",
    }

    with pytest.raises(ValueError, match="calendar"):
        Instrument.model_validate(misspelled)


def test_the_first_trade_date_is_the_start_of_a_roots_first_version() -> None:
    assert A_TICK_CHANGE.first_trade_date("ES") == date(1997, 9, 9)
    assert ff.instruments.STATIC_TABLE.first_trade_date("MCL") == date(2021, 7, 12)


def test_the_first_trade_date_of_an_unknown_root_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected a root of the instrument table"):
        STATIC_TABLE.first_trade_date("ZN")
