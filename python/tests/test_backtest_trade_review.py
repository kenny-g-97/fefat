"""The trade review's window of a run (step 5.9): each fill on the bar it belongs to by F-BAR-06,
every fill of the trades a window shows with their stop and target levels, and the strategy's
features at each bar's close, those its exit rules read as a distance in the instrument's
units."""

from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import Run, RunConfig, review_window
from fefat.backtest.trade_review import distance_features, fills_on_bars
from fefat.market.engine_units import PRICE_SCALE
from fefat.market.schema import Timeframe
from notebook_runs import store_with

START, END = "2026-03-05", "2026-03-09"
SECOND = 1_000_000_000
MINUTE = 60 * SECOND
TEN = int(datetime(2026, 3, 6, 10, tzinfo=UTC).timestamp()) * SECOND
TICK = 250_000_000
MARCH_6 = date(2026, 3, 6)


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")


def atr_breakout() -> ff.SignalStrategy:
    """The engine guide's breakout on ES: its stop at one and a half ATRs, its target at 2 R."""
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={
            "highest": close.rolling_max(12).shift(1),
            "atr": (pl.col("high") - pl.col("low")).rolling_mean(14),
        },
        long_entry=close > pl.col("highest"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(atr=1.5),
            targets=[ff.Target(r=2)],
            sizing=ff.Fixed(1),
        ),
    )


def backtest(config: RunConfig | None = None) -> Run:
    with pytest.warns(UserWarning, match="F-FEE-01"):
        return ff.backtest.run(atr_breakout(), START, END, config)


def signal_bars(start: str, end: str) -> pl.DataFrame:
    """The strategy's 5-minute bars from `start` to `end`, as the chart's page reads them."""
    return ff.market.load("ES", "5m", start, end).collect()


def candle(fill: dict[str, Any], bars: pl.DataFrame) -> int:
    """The open of the bar `fill` lies on, read the long way: a fill on a bar at its close, a
    print at its own instant (F-BAR-06)."""
    ts = fill["ts"]
    if fill["fidelity"] == "trades":
        holding = bars.filter(pl.col("ts_open") <= ts, pl.col("ts_close") > ts)
    else:
        holding = bars.filter(pl.col("ts_open") < ts, pl.col("ts_close") >= ts)
    return holding.item(0, "ts_open")


def test_a_fill_lies_on_the_bar_its_fidelity_places_it_on() -> None:
    # Step 5.9 (F-BAR-06, the step's "one bar late"): a fill on a bar carries that bar's close, so
    # a 1-minute bar's fill at 10:05 lies on the 5-minute bar closing then, where a print at
    # 10:05 opens the next; a fill before the first bar, after the last, or in a break lies on
    # none.
    closes = [TEN + 5 * MINUTE, TEN + 10 * MINUTE, TEN + 15 * MINUTE, TEN + 65 * MINUTE]
    bars = pl.DataFrame(
        {
            "ts_open": [TEN, TEN + 5 * MINUTE, TEN + 10 * MINUTE, TEN + 60 * MINUTE],
            "ts_close": closes,
        }
    )
    fills = pl.DataFrame(
        {
            "order": [1, 2, 3, 4, 5, 6, 7, 8],
            "ts": [
                TEN + 5 * MINUTE,
                TEN + 5 * MINUTE,
                TEN + 5 * MINUTE - 1,
                TEN + 15 * MINUTE,
                TEN,
                TEN + 30 * MINUTE,
                TEN + 60 * MINUTE,
                TEN + 65 * MINUTE,
            ],
            "fidelity": ["1m", "trades", "trades", "1m", "1m", "trades", "1m", "trades"],
        }
    )

    placed = fills_on_bars(fills, bars)

    assert placed.get_column("order").to_list() == list(range(1, 9))
    assert placed.get_column("bar_open").to_list() == [
        TEN,
        TEN + 5 * MINUTE,
        TEN,
        TEN + 10 * MINUTE,
        None,
        None,
        None,
        None,
    ]


def test_the_features_the_exit_rules_read_as_a_distance_are_those_of_atr_rules() -> None:
    spec = {
        "execution": {
            "stop": {"kind": "atr", "multiple": 1.5, "feature": "atr"},
            "targets": [
                {"price": {"kind": "atr", "multiple": 3, "feature": "wide_atr"}},
                {"price": {"kind": "r_multiple", "multiple": 2}},
            ],
            "trailing": {"by": {"kind": "atr", "multiple": 2, "feature": "atr"}},
        }
    }
    plain = {
        "execution": {
            "stop": {"kind": "ticks", "ticks": 8},
            "targets": [{"price": {"kind": "ticks", "ticks": 16}}],
            "trailing": {"by": {"kind": "column"}},
        }
    }

    assert distance_features(spec) == ("atr", "wide_atr")
    assert distance_features(plain) == ()
    assert distance_features({"execution": {"stop": {"kind": "percent", "percent": 1}}}) == ()


def test_a_window_holds_every_fill_of_its_trades_on_their_bars_with_their_levels() -> None:
    run = backtest(RunConfig(fidelity=Timeframe.parse("1m")))
    bars = signal_bars(START, END)

    window = review_window(run, bars)

    linked = (
        run.trade_paths.filter(pl.col("kind") == "fill")
        .select("trade", "order", "ts")
        .join(run.fills, on=["order", "ts"])
    )
    assert window.trades.height == run.trades.height
    assert sorted(window.fills.select("trade", "order", "ts").rows()) == sorted(
        linked.select("trade", "order", "ts").rows()
    )
    for fill in window.fills.iter_rows(named=True):
        assert fill["bar_open"] == candle(fill, bars), fill["order"]
    for trade in window.trades.iter_rows(named=True):
        # The long breakout's stop first stands its initial risk under its entry.
        assert trade["stop_first"] == trade["entry_price"] - trade["initial_risk_ticks"] * TICK
        legs = run.orders.filter(pl.col("bracket_of") == trade["entry_order"])
        stop = legs.filter(pl.col("role") == "stop").sort("id").get_column("price").to_list()
        target = legs.filter(pl.col("role") == "target_1").sort("id").get_column("price")
        assert trade["stop_last"] == stop[-1]
        assert trade["targets"] == [target.to_list()[-1]]


def test_a_window_shows_the_trades_on_its_bars_alone() -> None:
    run = backtest()
    bars = signal_bars("2026-03-06", "2026-03-06")

    window = review_window(run, bars)

    on_the_day = run.trades.with_row_index("trade").filter(pl.col("entry_trade_date") == MARCH_6)
    first, last = bars.item(0, "ts_open"), bars.item(-1, "ts_close")
    shown = set(window.trades.get_column("trade").to_list())
    assert set(on_the_day.get_column("trade").to_list()) <= shown
    for trade in window.trades.iter_rows(named=True):
        fills = window.fills.filter(pl.col("trade") == trade["trade"])
        on_the_page = fills.filter(pl.col("bar_open").is_not_null())
        assert not on_the_page.is_empty() or (
            trade["entry_ts"] < first and trade["exit_ts"] > last
        ), trade["trade"]


def test_a_feature_read_as_a_distance_is_in_the_instruments_units_and_the_rest_as_stored() -> None:
    run = backtest()
    bars = signal_bars("2026-03-06", "2026-03-06")

    window = review_window(run, bars)

    assert window.distances == ("atr",)
    assert window.left_out == ()
    features = window.features
    assert features.get_column("ts_close").to_list() == bars.get_column("ts_close").to_list()
    signals = bars.select("ts_close").join(
        run.signals.select("ts_close", "highest", "atr"), on="ts_close", how="left"
    )
    assert features.get_column("highest").to_list() == [
        None if value is None else float(value) for value in signals.get_column("highest")
    ]
    assert features.get_column("atr").to_list() == [
        None if value is None else value / PRICE_SCALE for value in signals.get_column("atr")
    ]
