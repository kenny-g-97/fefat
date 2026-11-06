"""One fidelity type for the scenarios, the engines, the cache, and `load` (step 2.2, D-51):
`tbbo`, `trades`, or bars of a timeframe, spelled as the scenarios spell it."""

from pathlib import Path

import pytest
from polars.testing import assert_frame_equal

import fefat as ff
from fefat.market.api import datasets, load
from fefat.market.fidelity import TickFidelity, parse_fidelity
from fefat.market.schema import Timeframe, TimeUnit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def fixtures_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository's fixtures as the data folder, which `load` only reads, inside the
    checkout, which the variable allows (`fefat.config`, step 4.1)."""
    monkeypatch.setenv("FEFAT_DATA_DIR", str(FIXTURES))
    monkeypatch.setenv("FEFAT_ALLOW_DATA_DIR_IN_GIT_TREE", "1")


@pytest.mark.parametrize("text", ["tbbo", "trades", "1s", "1m", "5m", "1d"])
def test_a_fidelity_reads_and_writes_as_the_scenarios_spell_it(text: str) -> None:
    assert str(parse_fidelity(text)) == text


def test_a_fidelity_is_tick_data_or_bars_of_a_timeframe() -> None:
    assert parse_fidelity("trades") is TickFidelity.TRADES
    assert parse_fidelity("1m") == Timeframe(count=1, unit=TimeUnit.MINUTE)
    assert parse_fidelity(TickFidelity.TBBO) is TickFidelity.TBBO


@pytest.mark.parametrize("text", ["tick", "auto", "", "1x", 5])
def test_a_text_that_names_no_fidelity_is_refused(text: object) -> None:
    with pytest.raises(ValueError, match="Expected a fidelity: tbbo, trades, or a bar timeframe"):
        parse_fidelity(text)


def test_the_sdk_offers_the_fidelity_type_as_ff_market() -> None:
    assert ff.market.TickFidelity is TickFidelity
    assert ff.market.parse_fidelity is parse_fidelity


@pytest.mark.usefixtures("fixtures_as_data")
def test_load_takes_the_fidelity_type_or_its_text_and_by_default_the_finest_data() -> None:
    named = load("ES", "1m", "2026-03-06", "2026-03-06", fidelity=TickFidelity.TRADES).collect()
    written = load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="trades").collect()
    finest = load("ES", "1m", "2026-03-06", "2026-03-06").collect()

    assert_frame_equal(named, written)
    assert_frame_equal(named, finest)


@pytest.mark.usefixtures("fixtures_as_data")
def test_load_refuses_the_old_spelling_of_trades() -> None:
    with pytest.raises(ValueError, match="Expected a fidelity: tbbo, trades"):
        load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="tick")


@pytest.mark.usefixtures("fixtures_as_data")
def test_load_says_it_builds_no_bars_from_tbbo_yet() -> None:
    with pytest.raises(ValueError, match="load does not build bars from TBBO yet"):
        load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="tbbo")


@pytest.mark.usefixtures("fixtures_as_data")
def test_the_catalog_names_the_fidelity_of_trades_as_the_scenarios_do() -> None:
    trades = datasets().filter(schema="trades")

    assert trades.get_column("fidelity").unique().to_list() == ["trades"]
