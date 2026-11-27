"""The one home of the conversions from decimals to the engines' units (step 2.10, BACKLOG's
"One converter from decimals to engine units"): the reference engine and `ff.backtest` read the
same instrument parameters."""

from decimal import Decimal

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.engine_units import (
    PRICE_SCALE,
    InstrumentParameters,
    instrument_parameters,
    micro_units,
    money_in_units,
    money_text,
    price_in_units,
    price_text,
)
from fefat.reference import units


def test_an_instrument_becomes_the_engines_integers() -> None:
    assert instrument_parameters(instruments.get("ES")) == InstrumentParameters(
        tick=250_000_000, money_per_point=50_000_000, lot_step=Decimal(1)
    )
    assert instrument_parameters(instruments.get("BTCUSDT-PERP")).money_per_point == 1_000


def test_the_reference_engine_reads_the_same_conversion() -> None:
    assert units.instrument_parameters is instrument_parameters
    assert units.InstrumentParameters is InstrumentParameters
    assert units.price_text is price_text


def test_prices_and_money_are_written_as_their_decimals() -> None:
    assert PRICE_SCALE == 1_000_000_000
    assert price_text(4_990_250_000_000) == "4990.25"
    assert price_text(-250_000_000) == "-0.25"
    assert money_text(-84_514) == "-0.084514"


def test_a_price_column_reads_in_the_instruments_units_as_the_float_nearest_its_decimal() -> None:
    # Step 5.1: the API sends prices in the instrument's units, which no client scales again.
    held = [4_990_250_000_000, -250_000_000, 76_430_000_000, 1]

    prices = pl.DataFrame({"close": held}).select(price_in_units("close")).to_series().to_list()

    assert prices == [float(price_text(units)) for units in held]
    assert prices[:3] == [4990.25, -0.25, 76.43]


def test_every_price_of_a_long_column_is_the_float_nearest_its_decimal() -> None:
    # Step 5.9 (BACKLOG's "`price_in_units` a bit off the nearest float"): the trade review's
    # contract test holds the chart's prices to the fills ledger, and a multiplication by the
    # scale's inverse put two prices in five a bit off on a tick of 0.1.
    held = [5_000_000_000_000 + tick * 100_000_000 for tick in range(4_000)]

    prices = pl.DataFrame({"close": held}).select(price_in_units("close")).to_series().to_list()

    assert prices == [float(price_text(units)) for units in held]


def test_a_missing_price_stays_missing() -> None:
    held = pl.Series("stop_price", [4_990_250_000_000, None], dtype=pl.Int64)

    prices = held.to_frame().select(price_in_units("stop_price")).to_series()

    assert prices.dtype == pl.Float64
    assert prices.to_list() == [4990.25, None]


def test_money_reads_in_the_currency_as_the_float_nearest_its_decimal() -> None:
    # Step 5.7: the points a chart draws go out as numbers, which no client scales again.
    held = [51_250_500_000, -84_514, 1, 0]

    amounts = money_in_units(pl.Series("equity", held, dtype=pl.Int64))

    assert list(amounts) == [float(money_text(units)) for units in held]
    assert amounts[:2] == (51250.5, -0.084514)


def test_an_amount_finer_than_a_micro_unit_is_refused() -> None:
    assert micro_units(Decimal(50_000)) == 50_000_000_000
    with pytest.raises(ValueError, match=r"Expected an amount in whole micro-units, got 1.0000005"):
        micro_units(Decimal("1.0000005"))
