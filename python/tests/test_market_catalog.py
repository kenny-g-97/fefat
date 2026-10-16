import sys
from datetime import date

import pytest

import fefat.market
from fefat.market.api import catalog
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.catalog import CATALOG, RollRule, parse_catalog
from fefat.market.instruments import STATIC_TABLE
from fefat.market.sources import SOURCE_GUIDE

ONE_PRODUCT = """\
version: 1
products:
  - root: MES
    calendar: cme-equity-index
    roll_rule: volume
    schemas: [trades, ohlcv-1m]
    history_from: 2019-05-06
    sources: [databento, kibot]
"""


def test_the_catalog_holds_the_four_micro_futures_with_files_on_this_pc() -> None:
    # D-38: the first catalog is MES, MNQ, MCL, and MGC.
    assert CATALOG.version == 1
    assert CATALOG.roots() == ("MES", "MNQ", "MCL", "MGC")


def test_each_product_names_an_instrument_of_the_table_and_its_built_in_calendar() -> None:
    for product in CATALOG.products:
        instrument = STATIC_TABLE.get(product.root)

        assert product.calendar is instrument.calendar_id
        assert product.calendar in BUILT_IN


def test_each_product_rolls_on_volume_and_recommends_databento_first() -> None:
    for product in CATALOG.products:
        assert product.roll_rule is RollRule.VOLUME
        assert product.sources[0] == "databento"
        assert all(SOURCE_GUIDE.source(source) for source in product.sources)


def test_each_product_s_history_starts_at_its_launch() -> None:
    assert {product.root: product.history_from for product in CATALOG.products} == {
        "MES": date(2019, 5, 6),
        "MNQ": date(2019, 5, 6),
        "MCL": date(2021, 7, 12),
        "MGC": date(2010, 10, 4),
    }
    for product in CATALOG.products:
        assert product.history_from == STATIC_TABLE.first_trade_date(product.root)


def test_a_product_is_found_by_its_root() -> None:
    mes = CATALOG.product("MES")

    assert mes is not None
    assert "ohlcv-1m" in [str(schema) for schema in mes.schemas]
    assert CATALOG.product("ES") is None


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (("root: MES", "root: MYM"), "Expected a root of the instrument table"),
        (
            ("calendar: cme-equity-index", "calendar: cme-energy"),
            "Expected the calendar of MES, cme-equity-index, got cme-energy",
        ),
        (
            ("history_from: 2019-05-06", "history_from: 2019-05-03"),
            "Expected the history of MES from 2019-05-06, when it began trading, or later, "
            "got 2019-05-03",
        ),
        (("[databento, kibot]", "[databento, nowhere]"), "Expected a source of the guide"),
        (("roll_rule: volume", "roll_rule: settlement"), "Input should be 'volume'"),
        (("[trades, ohlcv-1m]", "[quotes]"), "Expected a schema name"),
        (("version: 1", "version: 0"), "Input should be greater than or equal to 1"),
        (("calendar: cme-equity-index", "calendar: cme-equity"), "Input should be 'cme-equity"),
    ],
)
def test_a_catalog_that_breaks_a_rule_is_refused(change: tuple[str, str], refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        parse_catalog(ONE_PRODUCT.replace(*change))


def test_a_catalog_listing_a_product_twice_is_refused() -> None:
    twice = ONE_PRODUCT + ONE_PRODUCT.split("products:\n", 1)[1]

    with pytest.raises(
        ValueError, match="Expected each product listed once, got MES more than once"
    ):
        parse_catalog(twice)


def test_a_catalog_written_as_its_schema_is_read() -> None:
    read = parse_catalog(ONE_PRODUCT)

    assert read.roots() == ("MES",)


def test_the_catalog_package_leaves_ff_market_catalog_the_function() -> None:
    # `fefat.market.catalog` names both the package of catalog.yaml and the data API's
    # function; import the package's names with `from fefat.market.catalog import ...`.
    assert fefat.market.catalog is catalog
    assert sys.modules["fefat.market.catalog"].CATALOG is CATALOG
