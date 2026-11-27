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


def short_breakdown() -> ff.SignalStrategy:
    """The breakout turned over: short under the lowest close of the hour before, its stop at
    one and a half ATRs over the entry, its target at 2 R."""
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={
            "lowest": close.rolling_min(12).shift(1),
            "atr": (pl.col("high") - pl.col("low")).rolling_mean(14),
        },
        long_entry=pl.lit(False),
        short_entry=close < pl.col("lowest"),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(atr=1.5),
            targets=[ff.Target(r=2)],
            sizing=ff.Fixed(1),
        ),
    )


def backtest(config: RunConfig | None = None, strategy: ff.SignalStrategy | None = None) -> Run:
    with pytest.warns(UserWarning, match="F-FEE-01"):
        return ff.backtest.run(atr_breakout() if strategy is None else strategy, START, END, config)


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
    # The execution as the spec's model holds it (step 5.9's step review: parsed, not read as
    # a document whose fields a default could hide).
    execution = ff.Execution(
        entry=ff.Market(),
        stop=ff.Stop(atr=1.5),
        targets=[ff.Target(atr=3, feature="wide_atr"), ff.Target(r=2)],
        trailing=ff.Trailing(atr=2),
        sizing=ff.Fixed(1),
    )
    plain = ff.Execution(
        entry=ff.Market(),
        stop=ff.Stop(ticks=8),
        targets=[ff.Target(ticks=16)],
        trailing=ff.Trailing(column=True),
        sizing=ff.Fixed(1),
    )
    percent = ff.Execution(entry=ff.Market(), stop=ff.Stop(percent=1), sizing=ff.Fixed(1))

    assert distance_features(execution) == ("atr", "wide_atr")
    assert distance_features(plain) == ()
    assert distance_features(percent) == ()


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


def test_a_trade_from_a_windows_first_open_to_past_its_last_close_shows_on_it() -> None:
    # Step 5.9's code review: a fill on a bar stamped at a window's first open lies on the bar
    # before it, and a print at its last close on the bar after it (F-BAR-06), so a trade from
    # such an edge to past the other end shows on the window as one that spans it.
    on_minutes = backtest(RunConfig(fidelity=Timeframe.parse("1m")))
    on_prints = backtest()
    for run, edge in ((on_minutes, "entry"), (on_prints, "exit")):
        long_enough = pl.col("exit_ts") - pl.col("entry_ts") > 2 * MINUTE
        trade = run.trades.with_row_index("trade").filter(long_enough).row(0, named=True)
        entered, left = trade["entry_ts"], trade["exit_ts"]
        bars = pl.DataFrame(
            {
                "ts_open": [entered if edge == "entry" else entered + MINUTE],
                "ts_close": [left - MINUTE if edge == "entry" else left],
            }
        )

        window = review_window(run, bars)

        assert trade["trade"] in window.trades.get_column("trade").to_list(), edge
        fills = window.fills.filter(pl.col("trade") == trade["trade"])
        assert fills.get_column("bar_open").is_null().all(), edge


def test_a_window_without_bars_still_names_the_strategys_features() -> None:
    # Step 5.9's code review: a page of no bars, as a window of a weekend gives, names each of
    # the strategy's features with no values, so that a chart joining it to its other windows
    # keeps their panes.
    run = backtest()
    bars = signal_bars("2026-03-06", "2026-03-06").clear()

    window = review_window(run, bars)

    assert window.features.columns == ["ts_close", "highest", "atr"]
    assert window.features.is_empty()
    assert window.trades.is_empty()


def test_a_short_trades_stop_first_stands_its_initial_risk_over_its_entry() -> None:
    # Step 5.9's step review: the other runs here are long, so the short side of the stop's
    # first level had no test.
    run = backtest(strategy=short_breakdown())

    window = review_window(run, signal_bars(START, END))

    assert window.trades.height > 0
    for trade in window.trades.iter_rows(named=True):
        assert trade["side"] == "short"
        assert trade["stop_first"] == trade["entry_price"] + trade["initial_risk_ticks"] * TICK


def test_a_column_stops_first_level_is_its_column_at_the_decision() -> None:
    # Step 5.9's ponytail review: the engine keeps a trade's initial risk at a tick at least
    # (F-RND-02), while a column stop stands at its column wherever the entry fills, so a stop
    # the entry filled at or past stood at its column, not a tick from the fill. This one sits
    # three ticks over each long's signal close.
    close = pl.col("close")
    over_the_close = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"highest": close.rolling_max(12).shift(1)},
        long_entry=close > pl.col("highest"),
        short_entry=pl.lit(False),
        stop_price=close + 3 * TICK,
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(column=True), sizing=ff.Fixed(1)),
    )
    run = backtest(strategy=over_the_close)

    window = review_window(run, signal_bars(START, END))

    decided = run.signals.select(entry_decision="ts_close", column="stop_price")
    levels = window.trades.join(decided, on="entry_decision", how="left")
    assert levels.height > 0
    assert levels.get_column("stop_first").to_list() == levels.get_column("column").to_list()
