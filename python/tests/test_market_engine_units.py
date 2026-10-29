"""The one home of the conversions from decimals to the engines' units (step 2.10, BACKLOG's
"One converter from decimals to engine units"): the reference engine and `ff.backtest` read the
same instrument parameters."""

from decimal import Decimal

import pytest

from fefat.market import instruments
from fefat.market.engine_units import (
    PRICE_SCALE,
    InstrumentParameters,
    instrument_parameters,
    micro_units,
    money_text,
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


def test_an_amount_finer_than_a_micro_unit_is_refused() -> None:
    assert micro_units(Decimal(50_000)) == 50_000_000_000
    with pytest.raises(ValueError, match=r"Expected an amount in whole micro-units, got 1.0000005"):
        micro_units(Decimal("1.0000005"))
