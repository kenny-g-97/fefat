import re
import sys
from datetime import date
from pathlib import Path

import pytest

import fefat.market
import fefat.market.api
import fefat.market.catalog
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.catalog import CATALOG, RollRule, load_catalog, parse_catalog
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

        assert product.calendar is instrument.calendar
        assert product.calendar in BUILT_IN


def test_each_product_rolls_on_volume_and_recommends_databento_first() -> None:
    for product in CATALOG.products:
        assert product.roll_rule is RollRule.VOLUME
        assert product.sources[0] == "databento"
        assert all(SOURCE_GUIDE.source(source) for source in product.sources)


def test_a_product_s_roll_rule_is_its_own_and_a_root_outside_the_catalog_rolls_by_volume() -> None:
    # Step 2.9: load reads the rule from the catalog; ES, which it does not list, takes D-44's.
    assert [CATALOG.roll_rule(root) for root in CATALOG.roots()] == [RollRule.VOLUME] * 4
    assert CATALOG.roll_rule("ES") is RollRule.VOLUME


def test_each_product_s_history_starts_at_its_launch() -> None:
    assert {product.root: product.history_from for product in CATALOG.products} == {
        "MES": date(2019, 5, 6),
        "MNQ": date(2019, 5, 6),
        "MCL": date(2021, 7, 12),
        "MGC": date(2010, 10, 4),
    }
    for product in CATALOG.products:
        assert product.history_from == STATIC_TABLE.first_trade_date(product.root)


def test_each_product_lists_the_schemas_of_its_sources_with_the_1_minute_bars() -> None:
    for product in CATALOG.products:
        assert "ohlcv-1m" in [str(schema) for schema in product.schemas]


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
        (
            ("[databento, kibot]", "[databento, nowhere]"),
            "Expected the sources of MES in the guide, got nowhere, which it lacks",
        ),
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


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (("calendar: cme-equity-index", "calendar: cme-energy"), "Expected the calendar of MES"),
        (("products:\n", "products: [\n"), "while parsing a flow"),
    ],
)
def test_a_catalog_file_that_breaks_a_rule_is_refused_with_its_path(
    tmp_path: Path, change: tuple[str, str], refusal: str
) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(ONE_PRODUCT.replace(*change), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=f"(?s)Expected {re.escape(str(path))} to hold the product catalog, got: .*{refusal}",
    ):
        load_catalog(path)


def test_a_catalog_written_as_its_schema_is_read() -> None:
    read = parse_catalog(ONE_PRODUCT)

    assert read.roots() == ("MES",)


def test_ff_market_catalog_is_the_package_and_datasets_the_function() -> None:
    # Step 2.10: the data API's function is `datasets`, so that no function hides the package.
    assert fefat.market.catalog is sys.modules["fefat.market.catalog"]
    assert fefat.market.catalog.CATALOG is CATALOG
    assert fefat.market.datasets is fefat.market.api.datasets
