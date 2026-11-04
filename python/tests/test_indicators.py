"""`fefat.indicators` beside its goldens (step 3.5): the module docstring's table names every
indicator with its parameters and outputs (Done means 3); levels are prices and distances price
distances, in the bars' 1e-9 units, so that `ff.Stop(atr=1.5)` reads `atr(14)` (the amendment);
a price worked out from features rounds down or up to the tick and so passes F-RND-01 as a
column price; and a division by zero, where TA-Lib gives 0 or 50, gives null."""

import re
import warnings

import polars as pl
import pytest

import fefat as ff
from fefat.features import FeatureDef, FeatureSpec, OutputKind
from fefat.strategy.exits import StopRule
from notebook_runs import store_with

TICK = 250_000_000
"""ES's tick in the bars' 1e-9 units of price."""
DEFINITIONS = [
    definition
    for name in ff.indicators.__all__
    if isinstance(definition := getattr(ff.indicators, name), FeatureDef)
]


def call_text(spec: FeatureSpec) -> str:
    parameters = ", ".join(f"{name}={value!r}" for name, value in dict(spec.parameters).items())
    return f"{spec.definition.name}({parameters})"


def test_the_module_docstring_has_a_row_for_each_indicator_with_its_parameters() -> None:
    # Done means 3: each indicator's row writes its call with its defaults, its outputs, and
    # their kinds.
    rows = [line for line in (ff.indicators.__doc__ or "").splitlines() if line.startswith("| ")]

    assert len(DEFINITIONS) == 17
    for definition in DEFINITIONS:
        call = f"`{call_text(definition())}`"
        row = next((row for row in rows if call in row), None)
        assert row is not None, f"Expected a row of the table for {call}, got none"
        for output, kind in definition.outputs.items():
            assert f"`{output}`" in row, f"{call}: {output} missing from its row"
            assert kind.value in row, f"{call}: the kind {kind} missing from its row"


def test_levels_are_prices_and_distances_are_price_distances() -> None:
    # The amendment: moving averages, bands, and channels are levels, ATR, the true range, and
    # the standard deviation distances, both in the bars' 1e-9 units of price.
    kinds = {
        f"{each.name}.{output}": kind
        for each in DEFINITIONS
        for output, kind in each.outputs.items()
    }
    levels = ["sma.sma", "ema.ema", "wma.wma", "keltner.middle", "keltner.upper", "keltner.lower"]
    levels += [
        f"{band}.{line}"
        for band in ("bollinger", "donchian")
        for line in ("middle", "upper", "lower")
    ]
    distances = ["atr.atr", "true_range.true_range", "standard_deviation.standard_deviation"]

    assert {kinds[output] for output in levels} == {OutputKind.PRICE}
    assert {kinds[output] for output in distances} == {OutputKind.PRICE_DISTANCE}


def rising(stop: StopRule, stop_price: pl.Expr | None = None) -> ff.SignalStrategy:
    """A long on every rising 5-minute bar of ES with `stop`, and the indicators' ATR(11), whose
    275 bars of warm-up fit in the fixtures' one session before 2026-03-09."""
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"atr": ff.indicators.atr(11)},
        long_entry=pl.col("close") > pl.col("open"),
        short_entry=pl.lit(False),
        stop_price=stop_price,
        execution=ff.Execution(entry=ff.Market(), stop=stop, sizing=ff.Fixed(1)),
    )


def test_a_stop_of_atrs_reads_the_indicators_atr_in_the_bars_units() -> None:
    # The amendment: ff.Stop(atr=1.5) reads ff.indicators.atr as the template reads an ATR
    # worked out from load's frame, above a tick, so no run warns of one below it.
    store_with("ohlcv-1m")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run = ff.backtest.run(rising(stop=ff.Stop(atr=1.5)), "2026-03-09", "2026-03-09")

    assert run.signals.get_column("atr").null_count() == 0
    assert run.trades.height > 0
    assert (run.trades["atr_at_entry"] > TICK).all()
    assert not [str(w.message) for w in caught if "below one tick" in str(w.message)]


def test_a_stop_at_the_low_less_half_an_atr_runs_once_rounded_down_to_the_tick() -> None:
    # The amendment: F-RND-01 refuses a column price off the tick, so the stop at the bar's low
    # less half an ATR is refused until the indicators' rounding puts it on the tick.
    store_with("ohlcv-1m")
    stop = pl.col("low") - pl.col("atr") / 2
    window = ("2026-03-09", "2026-03-09")

    with pytest.raises(ValueError, match=re.escape("Expected stop_price in whole 1e-9 units")):
        ff.backtest.run(rising(stop=ff.Stop(column=True), stop_price=stop), *window)
    rounded = ff.indicators.round_down_to_tick(stop, "ES")
    run = ff.backtest.run(rising(stop=ff.Stop(column=True), stop_price=rounded), *window)

    entries = run.signals.filter(pl.col("long_entry"))
    assert run.trades.height > 0
    assert entries.get_column("stop_price").dtype == pl.Int64
    assert (entries.get_column("stop_price") % TICK == 0).all()


def test_a_price_rounds_down_or_up_to_the_tick_and_a_price_on_it_stays() -> None:
    # A float a hair below or above a tick, as arithmetic leaves it, stays on that tick.
    on_tick = 4_500 * 1_000_000_000 + 3 * TICK
    prices = pl.DataFrame({"price": [on_tick - 0.0004, on_tick + 0.0004, on_tick + 1.0, None]})

    rounded = prices.select(
        down=ff.indicators.round_down_to_tick(pl.col("price"), "ES"),
        up=ff.indicators.round_up_to_tick(pl.col("price"), "ES"),
    )

    assert rounded.schema == pl.Schema({"down": pl.Int64, "up": pl.Int64})
    assert rounded.get_column("down").to_list() == [on_tick, on_tick, on_tick, None]
    assert rounded.get_column("up").to_list() == [on_tick, on_tick, on_tick + TICK, None]


FLAT = pl.DataFrame(
    {
        "ts_close": range(1, 101),
        "open": [5_000 * TICK] * 100,
        "high": [5_000 * TICK] * 100,
        "low": [5_000 * TICK] * 100,
        "close": [5_000 * TICK] * 100,
        "volume": pl.Series([0] * 100, dtype=pl.UInt64),
    }
)
"""A market that has not moved: every bar flat at one price."""


@pytest.mark.parametrize(
    ("spec", "output"),
    [
        (ff.indicators.rsi(14), "rsi"),
        (ff.indicators.stochastic(), "percent_k"),
        (ff.indicators.adx(), "plus_di"),
        (ff.indicators.adx(), "adx"),
        (ff.indicators.z_score(), "z_score"),
        (ff.indicators.bollinger(), "percent_b"),
    ],
    ids=lambda each: each if isinstance(each, str) else call_text(each),
)
def test_a_division_by_zero_gives_null_where_talib_gives_0_or_50(
    spec: FeatureSpec, output: str
) -> None:
    values = spec.evaluate(FLAT).collect().get_column(output)

    assert values.null_count() == FLAT.height


def test_a_macd_whose_fast_period_is_not_below_its_slow_one_is_refused() -> None:
    refusal = "Expected the fast period of macd below its slow one, got fast=26 and slow=12."

    with pytest.raises(ValueError, match=re.escape(refusal)):
        ff.indicators.macd(26, 12).evaluate(FLAT)
