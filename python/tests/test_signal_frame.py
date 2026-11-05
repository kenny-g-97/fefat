"""Step 2.3's signal frame: `SignalStrategy.signals(bars)` evaluates a strategy's features and
signals over `load`'s frame into the frame the engine reads, aligned to the signal bars' closes,
with its prices as raw prices of each row's contract (D-09), and `validated_signal_frame` refuses
a frame that breaks the contract (types, nulls, NaN, alignment)."""

import re
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from fefat.market.api import SIGNAL_BAR_COLUMNS, load
from fefat.reference.units import instant_nanoseconds, price_units
from fefat.strategy import (
    Execution,
    Fixed,
    Limit,
    Market,
    SignalStrategy,
    Stop,
    Target,
    validated_signal_frame,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MES_TICK = 250_000_000
FIVE_MINUTES = 300_000_000_000
FIRST_CLOSE = instant_nanoseconds("2026-03-06T14:35:00Z")


@pytest.fixture
def fixtures_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository's fixtures as the data folder, which `load` only reads."""
    monkeypatch.setenv("FEFAT_DATA_DIR", str(FIXTURES))


def signal_bars(*closes: str, offset: str = "10.00", contract: str = "MESM2026") -> pl.DataFrame:
    """`load`'s frame of 5-minute bars closing every five minutes from 14:35 UTC on 2026-03-06,
    one per close of `closes`, adjusted by `offset` points above `contract`'s raw prices."""
    adjusted = [price_units(close) for close in closes]
    shift = price_units(offset)
    count = len(closes)
    rows: dict[str, list[Any]] = {
        "ts_open": [FIRST_CLOSE + (n - 1) * FIVE_MINUTES for n in range(count)],
        "ts_close": [FIRST_CLOSE + n * FIVE_MINUTES for n in range(count)],
        "trade_date": [date(2026, 3, 6)] * count,
        "instrument_id": [1] * count,
        "open": adjusted,
        "high": adjusted,
        "low": adjusted,
        "close": adjusted,
        "volume": [10] * count,
        "trade_count": [3] * count,
        "vwap": [None] * count,
        "contract": [contract] * count,
        "close_raw": [price - shift for price in adjusted],
        "adj_offset": [shift] * count,
        "roll_flag": [False] * count,
        "zero_volume": [False] * count,
    }
    return pl.DataFrame(rows, schema=SIGNAL_BAR_COLUMNS)


def strategy(**fields: Any) -> SignalStrategy:
    """MES on 5-minute bars, buying when the close rises above the mean of the last two closes,
    with its stop at the frame's `stop_price`; `fields` replace its own."""
    own = {
        "instrument": "MES",
        "timeframe": "5m",
        "features": {"mean": pl.col("close").rolling_mean(2)},
        "long_entry": pl.col("close") > pl.col("mean"),
        "short_entry": pl.lit(False),
        "execution": Execution(
            entry=Market(), stop=Stop(column=True), targets=[Target(ticks=24)], sizing=Fixed(1)
        ),
    }
    return SignalStrategy.model_validate({**own, **fields})


def test_the_frame_carries_the_bars_columns_the_features_and_the_signals() -> None:
    bars = signal_bars("5000.00", "5001.00", "5000.50")

    frame = strategy(stop_price=pl.col("close") - 12 * MES_TICK).signals(bars).collect()

    assert frame.columns == [
        "ts_close",
        "trade_date",
        "contract",
        "adj_offset",
        "mean",
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "stop_price",
    ]
    assert frame.get_column("ts_close").to_list() == bars.get_column("ts_close").to_list()
    assert frame.get_column("long_entry").to_list() == [False, True, False]
    assert frame.get_column("long_exit").to_list() == [False] * 3


def test_its_prices_are_raw_prices_of_the_rows_contract() -> None:
    bars = signal_bars("5000.00", "5001.00", offset="10.00")

    frame = strategy(stop_price=pl.col("close") - 12 * MES_TICK).signals(bars).collect()

    raw_stops = [price_units("4987.00"), price_units("4988.00")]
    assert frame.get_column("stop_price").to_list() == raw_stops


def test_a_price_of_whole_units_as_a_float_is_read_as_an_integer() -> None:
    whole_float = pl.col("close").cast(pl.Float64) - 3e9

    frame = strategy(stop_price=whole_float).signals(signal_bars("5000.00")).collect()

    assert frame.schema["stop_price"] == pl.Int64
    assert frame.item(0, "stop_price") == price_units("4987.00")


@pytest.mark.parametrize("price", [pl.col("close") - 0.5, pl.col("close") / 0.0])
def test_a_price_off_whole_units_is_refused(price: pl.Expr) -> None:
    with pytest.raises(ValueError, match=r"Expected stop_price in whole 1e-9 units") as refused:
        strategy(stop_price=price).signals(signal_bars("5000.00"))

    # The security review of the Phase 3 exit: the refusal quotes no price, which can be licensed
    # data (D-21).
    assert not re.search(r"\d{7,}", str(refused.value)), refused.value


def test_a_null_signal_is_no_signal_and_a_null_wake_wakes() -> None:
    warming_up = strategy(wake=pl.col("mean") > 0)

    frame = warming_up.signals(signal_bars("5000.00", "5001.00")).collect()

    assert frame.get_column("long_entry").to_list() == [False, True]
    assert frame.get_column("wake").to_list() == [True, True]


def test_a_back_adjusted_import_is_refused() -> None:
    bars = signal_bars("5000.00").with_columns(
        close_raw=pl.lit(None, dtype=pl.Int64), adj_offset=pl.lit(None, dtype=pl.Int64)
    )

    with pytest.raises(ValueError, match="Expected a series with raw prices, got a back-adjusted"):
        strategy().signals(bars)


def test_both_entry_signals_on_a_bar_are_refused_under_a_market_entry() -> None:
    both = strategy(short_entry=pl.col("close") > 0)

    with pytest.raises(ValueError, match="Expected one of long_entry and short_entry per bar"):
        both.signals(signal_bars("5000.00", "5001.00"))


def test_both_entry_signals_on_a_bar_are_a_pair_under_a_limit_entry() -> None:
    pair = strategy(
        short_entry=pl.col("close") > 0,
        execution=Execution(entry=Limit(offset_ticks=2), sizing=Fixed(1)),
    )

    frame = pair.signals(signal_bars("5000.00", "5001.00")).collect()

    assert frame.select(pl.col("long_entry") & pl.col("short_entry")).to_series().to_list() == [
        False,
        True,
    ]


def test_a_nan_in_a_feature_is_refused() -> None:
    zero_by_zero = pl.col("volume").cast(pl.Float64) * 0.0 / 0.0
    nan = strategy(features={"mean": pl.col("close").rolling_mean(2), "ratio": zero_by_zero})

    with pytest.raises(ValueError, match="Expected no NaN in the signal frame's ratio"):
        nan.signals(signal_bars("5000.00"))


def test_a_strategys_features_cannot_be_changed_once_it_is_built() -> None:
    built = strategy()

    assert isinstance(built.features, MappingProxyType)
    assert list(built.features) == ["mean"]


def test_a_feature_named_like_a_column_of_the_frame_is_refused() -> None:
    with pytest.raises(ValidationError, match="Expected feature names apart from"):
        strategy(features={"long_entry": pl.col("close") > 0})


def test_the_bars_of_several_contracts_at_once_are_refused() -> None:
    bars = pl.concat([signal_bars("5000.00"), signal_bars("4990.00", contract="MESH2026")])

    with pytest.raises(
        ValueError, match="Expected the signal frame's ts_close strictly increasing"
    ):
        strategy().signals(bars)


@pytest.mark.usefixtures("fixtures_as_data")
def test_the_fixtures_spliced_es_bars_give_raw_prices_on_both_sides_of_the_roll() -> None:
    bars = load("ES", "5m", "2026-03-05", "2026-03-09", fidelity="1m")
    stop_under_the_close = pl.col("close") - 12 * MES_TICK

    frame = strategy(instrument="ES", stop_price=stop_under_the_close).signals(bars).collect()

    raw = bars.collect().select(raw_stop=pl.col("close_raw") - 12 * MES_TICK, offset="adj_offset")
    assert frame.get_column("stop_price").to_list() == raw.get_column("raw_stop").to_list()
    assert raw.get_column("offset").n_unique() == 2


def a_signal_frame(**columns: list[Any]) -> pl.DataFrame:
    """Two rows of a signal frame without signals, with `columns` added or replaced."""
    rows: dict[str, list[Any]] = {
        "ts_close": [FIRST_CLOSE, FIRST_CLOSE + FIVE_MINUTES],
        "trade_date": [date(2026, 3, 6)] * 2,
        "contract": ["MESM2026"] * 2,
        "adj_offset": [0, 0],
        "long_entry": [False, False],
        "short_entry": [False, False],
        "long_exit": [False, False],
        "short_exit": [False, False],
    }
    return pl.DataFrame({**rows, **columns})


def test_a_frame_of_the_contract_passes_with_its_feature_columns() -> None:
    prices = [price_units("5000.00"), None]
    frame = a_signal_frame(atr=[1.5, 2.0], stop_price=prices, size_mult=[None, 2.0])

    assert validated_signal_frame(frame) is frame


@pytest.mark.parametrize(
    ("frame", "refusal"),
    [
        (
            a_signal_frame().drop("long_exit"),
            "Expected the signal frame's long_exit as Boolean, got none",
        ),
        (
            a_signal_frame(stop_price=[1.0, 2.0]),
            "Expected the signal frame's stop_price as Int64, got Float64",
        ),
        (
            a_signal_frame(long_entry=[True, None]),
            "Expected no null in the signal frame's long_entry",
        ),
        (a_signal_frame(wake=[None, True]), "Expected no null in the signal frame's wake"),
        (
            a_signal_frame(long_entry=[True, False], size_mult=[None, 2.0]),
            "on every bar with an entry signal, got null on 1 bar",
        ),
        (
            a_signal_frame(long_entry=[True, False], size_mult=[float("inf"), 2.0]),
            "Expected size_mult, a finite number above zero, on every bar with an entry signal, got inf",
        ),
        (
            a_signal_frame(short_entry=[False, True], size_mult=[2.0, 0.0]),
            "on every bar with an entry signal, got 0.0 on 1 bar",
        ),
        (
            a_signal_frame(size_mult=[1.0, float("nan")]),
            "Expected no NaN in the signal frame's size_mult",
        ),
        (
            a_signal_frame(ts_close=[FIRST_CLOSE, FIRST_CLOSE]),
            "Expected the signal frame's ts_close strictly",
        ),
    ],
)
def test_a_frame_that_breaks_the_contract_is_refused(frame: pl.DataFrame, refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        validated_signal_frame(frame)
