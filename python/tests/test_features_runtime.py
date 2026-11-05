"""The feature runtime of step 3.2 (`02-engine-and-data.md` §6, D-71), on bars built by hand and
through `ff.features.compute` on the fixtures: features evaluated in the order their
dependencies give, a higher timeframe's bar seen from its close and never in progress, another
instrument's bars joined as of each close with their staleness, and each feature's warm-up
carried through the graph and read from before the window."""

import dataclasses
import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import (
    DatasetInput,
    FeatureInput,
    InstrumentInput,
    TimeframeInput,
    TradesInput,
)
from fefat.features.examples import atr, rsi
from fefat.features.grids import Grid, PrintsGrid, load_inputs
from fefat.features.runtime import FeatureGraph
from fefat.market import instruments
from fefat.market.api import SIGNAL_BAR_COLUMNS, series_source
from fefat.market.calendar import sessions_of
from fefat.market.schema import Timeframe
from notebook_runs import features_of_cell, store_with

MINUTE = 60_000_000_000
FIVE, FIFTEEN = Timeframe.parse("5m"), Timeframe.parse("15m")


def bars(closes: list[int], width: int, start: int = 0) -> pl.DataFrame:
    """One series of bars of `width` minutes from minute `start` on, closing at `closes`."""
    opens = [(start + width * index) * MINUTE for index in range(len(closes))]
    return pl.DataFrame(
        {
            "ts_open": opens,
            "ts_close": [opened + width * MINUTE for opened in opens],
            "close": closes,
            "close_raw": closes,
        }
    )


@ff.feature(inputs=[TimeframeInput(timeframe="15m")], outputs={"close_15m": "price"})
def close_15m(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")


@ff.feature(inputs=[InstrumentInput(root="NQ")], outputs={"level": "price", "staleness": "other"})
def nq_close(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    return {"level": pl.col("close_NQ"), "staleness": pl.col("staleness_NQ")}


@ff.feature(warmup=1, outputs={"step": "price_distance"})
def step(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") - pl.col("close").shift(1)


@ff.feature(inputs=[step], warmup=1, outputs={"swing": "price_distance"})
def swing(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("step").rolling_sum(2)


@ff.feature(inputs=[step, swing], warmup=1, outputs={"blend": "price_distance"})
def blend(bars: pl.LazyFrame) -> pl.Expr:
    return 2 * pl.col("swing") + pl.col("step")


@ff.feature(inputs=[rsi], outputs={"stretched": "ratio"})
def stretched(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("rsi") - 50


@ff.feature(outputs={"scaled": "price"})
def scaled(bars: pl.LazyFrame, factor: int) -> pl.Expr:
    return pl.col("close") * factor


@ff.feature(inputs=[scaled], outputs={"scaled_twice": "price"})
def scaled_twice(bars: pl.LazyFrame) -> pl.Expr:
    return 2 * pl.col("scaled")


SPREAD = """\
@ff.feature(
    inputs=[
        ff.features.FeatureInput(name="sma", hash="{hash}", parameters={{"n": 2}}, alias="sma_2"),
        ff.features.FeatureInput(name="sma", hash="{hash}", parameters={{"n": 3}}, alias="sma_3"),
    ],
    outputs={{"spread": "price_distance"}},
)
def spread(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("sma_2") - pl.col("sma_3")
"""
"""A feature reading one feature twice, each with the parameters its decorator binds."""
GONE = "0" * 64
"""The content hash of a feature this process never defined."""
UNDEFINED = features_of_cell(
    f"""\
@ff.feature(
    inputs=[ff.features.FeatureInput(name="gone", hash="{GONE}")],
    outputs={{"reads_gone": "price"}},
)
def reads_gone(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("gone")


@ff.feature(
    inputs=[ff.features.FeatureInput(name="gone", hash="{GONE}", parameters={{"n": 2}})],
    outputs={{"binds_gone": "price"}},
)
def binds_gone(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("gone")
"""
)
"""Two features reading one no process defined, one with the parameters it binds."""


@ff.feature(outputs={"highest_before": "price"})
def highest_before(bars: pl.LazyFrame) -> pl.LazyFrame:
    return bars.select("ts_close", highest_before=pl.col("close").cum_max().shift(1))


@ff.feature(outputs={"first_rows": "price"})
def first_rows(bars: pl.LazyFrame) -> pl.LazyFrame:
    return bars.select("ts_close", first_rows=pl.col("close")).head(2)


@ff.feature(inputs=[rsi, TimeframeInput(timeframe="15m")], outputs={"rsi_15m": "ratio"})
def rsi_15m(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("rsi")


@ff.feature(inputs=[InstrumentInput(root="BTCUSDT-PERP")], outputs={"btc_age": "other"})
def btc_age(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("staleness_BTCUSDT-PERP")


@ff.feature(inputs=[InstrumentInput(root="ES")], outputs={"es_age": "other"})
def es_age(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("staleness_ES")


@ff.feature(warmup=12, outputs={"upper": "price", "lower": "price"})
def band(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    return {"upper": pl.col("high").rolling_max(12), "lower": pl.col("low").rolling_min(12)}


@ff.feature(inputs=[TradesInput()], outputs={"delta": "count"})
def delta(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("buy_volume") - pl.col("sell_volume")


@ff.feature(inputs=[DatasetInput(name="cot")], outputs={"positioning": "other"})
def positioning(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")


def test_a_higher_timeframes_bar_is_seen_from_its_close_and_never_in_progress() -> None:
    # Done means 1: 5-minute bars of 55 minutes and 15-minute bars of an hour, the last still in
    # progress when the 5-minute bars end, which `load` holds back (D-43) but which must not show
    # even when given; a join on ts_open would show each 15-minute bar from its open.
    five = bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], 5)
    graph = FeatureGraph.of({"close_15m": close_15m()}, "ES", FIVE)
    inputs = {graph.signal_grid: five, Grid("ES", FIFTEEN): bars([12, 15, 18, 21], 15)}

    values = graph.evaluate(inputs)

    assert values["close_15m"].to_list() == [None, None, 12, 12, 12, 15, 15, 15, 18, 18, 18]
    changed = values.filter(pl.col("close_15m").ne_missing(pl.col("close_15m").shift(1)))
    assert changed["ts_close"].to_list() == [15 * MINUTE, 30 * MINUTE, 45 * MINUTE]
    for cut in five["ts_close"]:
        before = {grid: frame.filter(pl.col("ts_close") <= cut) for grid, frame in inputs.items()}
        assert graph.evaluate(before).rows() == values.filter(pl.col("ts_close") <= cut).rows()


def test_another_instruments_bars_join_as_of_each_close_with_their_staleness() -> None:
    # Done means 1: NQ's first bar closes at 10 minutes and none closes at 20, so ES's row of
    # 20 minutes reads NQ's bar of 15, five minutes stale, and its first row reads nothing.
    es = bars([100, 101, 102, 103, 104], 5)
    nq = bars([200, 201, 202, 203], 5, start=5).filter(pl.col("ts_close") != 20 * MINUTE)
    graph = FeatureGraph.of({"nq": nq_close()}, "ES", FIVE)

    values = graph.evaluate({graph.signal_grid: es, Grid("NQ", FIVE): nq})

    assert graph.grids() == (Grid("ES", FIVE), Grid("NQ", FIVE))
    assert values.columns == ["ts_close", "nq_level", "nq_staleness"]
    assert values.select("nq_level", "nq_staleness").rows() == [
        (None, None),
        (200, 0),
        (201, 0),
        (201, 5 * MINUTE),
        (203, 0),
    ]


def test_a_chain_of_three_features_runs_in_order_with_its_warmups_carried() -> None:
    # Done means 2, by hand: step is the change of the close, swing the sum of two steps, and
    # blend twice the swing plus the step, each with a warm-up of one bar after the most its
    # inputs need, so 1, 2, and 3 bars, whatever order the slots come in.
    graph = FeatureGraph.of({"blend": blend(), "swing": swing(), "step": step()}, "ES", FIVE)
    signal = bars([100, 103, 101, 106, 110, 108], 5)

    values = graph.evaluate({graph.signal_grid: signal})

    assert values.select("step", "swing", "blend").rows() == [
        (None, None, None),
        (3, None, None),
        (-2, 1, None),
        (5, 3, 11),
        (4, 9, 22),
        (-2, 2, 2),
    ]
    assert [graph.warmups[graph.slots[slot]] for slot in ("step", "swing", "blend")] == [1, 2, 3]
    assert graph.lead_in_bars() == 3


def test_a_feature_read_but_not_given_is_read_with_its_defaults() -> None:
    # BACKLOG.md, step 3.7: a feature another reads needs no slot of its own, which would give it
    # a column too; without one it is read with its defaults, as this process defined it.
    signal = bars([100, 103, 101, 106, 110, 108], 5)
    alone = FeatureGraph.of({"swing": swing()}, "ES", FIVE)
    beside = FeatureGraph.of({"swing": swing(), "step": step()}, "ES", FIVE)

    values = alone.evaluate({alone.signal_grid: signal})

    assert values.columns == ["ts_close", "swing"]
    assert values["swing"].to_list() == [None, None, 1, 3, 9, 2]
    assert values["swing"].equals(beside.evaluate({beside.signal_grid: signal})["swing"])


def test_a_feature_reads_another_with_the_parameters_it_binds_under_an_alias() -> None:
    # Step 3.7: a reader's decorator may bind the parameters of each feature it reads, which its
    # hash then covers, as a combination's does, and name the columns it reads them under, so it
    # reads one feature twice; a slot of the same feature keeps its own parameters.
    spread = features_of_cell(SPREAD.format(hash=ff.indicators.sma.hash))["spread"]
    graph = FeatureGraph.of({"spread": spread(), "sma": ff.indicators.sma(4)}, "ES", FIVE)

    values = graph.evaluate({graph.signal_grid: bars([10, 12, 14, 16, 18, 20], 5)})

    assert values.columns == ["ts_close", "spread", "sma"]
    assert values["spread"].to_list() == [None, None, 1.0, 1.0, 1.0, 1.0]
    assert values["sma"].to_list() == [None, None, None, 13.0, 15.0, 17.0]


def test_a_feature_read_on_a_higher_timeframe_is_evaluated_there() -> None:
    # swing is given once, by its slot, and evaluated on both grids: the 15-minute grid's
    # swing reads the 15-minute grid's step, never the 5-minute one's, and its warm-up of 2
    # fifteen-minute bars is 8 five-minute bars before its first value on the 5-minute grid.
    @ff.feature(inputs=[swing, TimeframeInput(timeframe="15m")], outputs={"swing_15m": "price"})
    def swing_15m(bars: pl.LazyFrame) -> pl.Expr:
        return pl.col("swing")

    slots = {"step": step(), "swing": swing(), "swing_15m": swing_15m()}
    graph = FeatureGraph.of(slots, "ES", FIVE)
    fifteen = bars([100, 103, 101, 106], 15)
    inputs = {graph.signal_grid: bars(list(range(12)), 5), Grid("ES", FIFTEEN): fifteen}

    values = graph.evaluate(inputs)

    assert values["swing_15m"].to_list() == [None] * 8 + [1, 1, 1, 3]
    assert values["step"].to_list() == [None, *[1] * 11]
    assert values["swing"].to_list() == [None, None, *[2] * 10]
    assert graph.lead_in_bars() == 8


def test_a_feature_may_return_a_frame_on_its_bars_grid_and_never_another() -> None:
    # BACKLOG.md: a feature that needs a join or a group-by returns a frame of ts_close and its
    # outputs, one row for each of its bars.
    signal = bars([5, 7, 6, 9], 5)
    graph = FeatureGraph.of({"highest_before": highest_before()}, "ES", FIVE)

    assert graph.evaluate({graph.signal_grid: signal})["highest_before"].to_list() == [
        None,
        5,
        7,
        7,
    ]
    shorter = FeatureGraph.of({"first_rows": first_rows()}, "ES", FIVE)
    with pytest.raises(ValueError, match="Expected the frame feature first_rows returns on the"):
        shorter.evaluate({shorter.signal_grid: signal})


def test_a_cycle_of_features_is_refused_with_the_features_in_it() -> None:
    # A content hash covers the hashes of the features it reads, so no two features can read
    # each other; a definition forged around its hash can.
    looped = dataclasses.replace(step, inputs=(FeatureInput(name="swing", hash=swing.hash),))

    with pytest.raises(ValueError) as refused:
        FeatureGraph.of({"step": looped(), "swing": swing()}, "ES", FIVE)

    assert re.fullmatch(
        r"Expected the features to form a graph without cycles, got a cycle: "
        r"(step -> swing -> step|swing -> step -> swing)\.",
        str(refused.value),
    )


@pytest.mark.parametrize(
    ("slots", "refusal"),
    [
        (
            {"scaled_twice": scaled_twice()},
            "Expected the feature scaled that scaled_twice reads among the features given, once "
            "with its parameters, got none, and no default of factor: give it a slot, such as "
            "scaled(...).",
        ),
        (
            {"reads_gone": UNDEFINED["reads_gone"]()},
            "Expected the feature gone that reads_gone reads among the features given, once with "
            "its parameters, got none: give it a slot, such as gone(...).",
        ),
        (
            {"binds_gone": UNDEFINED["binds_gone"]()},
            "Expected the feature gone that binds_gone reads, 000000000000, defined in this "
            "process, got none: define it, or read it from the library with "
            "ff.features.ref('gone', version=...).",
        ),
        (
            {"fast": rsi(n=7), "slow": rsi(n=14), "stretched": stretched()},
            "Expected the feature rsi that stretched reads among the features given, once with "
            "its parameters, got",
        ),
        (
            {"positioning": positioning()},
            "Expected inputs the runtime evaluates, got the dataset input cot of feature "
            "positioning, reserved for Phase 10.",
        ),
        (
            {"nq": nq_close(), "nq_level": step()},
            "Expected the features' columns apart from each other's and from the bars' columns, "
            "got nq_level.",
        ),
        (
            {"close": step()},
            "Expected the features' columns apart from each other's and from the bars' columns, "
            "got close.",
        ),
    ],
)
def test_a_graph_the_runtime_cannot_evaluate_is_refused(
    slots: dict[str, ff.features.FeatureSpec], refusal: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(refusal)):
        FeatureGraph.of(slots, "ES", FIVE)


def test_another_instruments_bars_that_are_not_one_series_of_raw_prices_are_refused() -> None:
    # The leakage audit of the step: a back-adjusted import's prices hold the gaps of every later
    # roll (D-09, D-49), and contracts stacked one after another read a later close as the bar
    # before, so another instrument's bars are held to what the reader's own are held to.
    es = bars([100, 101, 102], 5)
    adjusted = bars([180, 181, 182], 5).with_columns(close_raw=pl.lit(None, pl.Int64))
    stacked = pl.concat([bars([180, 181], 5), bars([170, 171], 5)])
    graph = FeatureGraph.of({"nq": nq_close()}, "ES", FIVE)

    with pytest.raises(ValueError, match="for NQ that feature nq_close reads, got a back-adj"):
        graph.evaluate({graph.signal_grid: es, Grid("NQ", FIVE): adjusted})
    with pytest.raises(ValueError, match="Expected the bars of NQ that feature nq_close reads as"):
        graph.evaluate({graph.signal_grid: es, Grid("NQ", FIVE): stacked})


def test_bars_a_feature_reads_but_not_given_are_refused() -> None:
    graph = FeatureGraph.of({"nq": nq_close()}, "ES", FIVE)

    with pytest.raises(ValueError, match="Expected the bars of NQ 5m that nq_close reads, got"):
        graph.evaluate({graph.signal_grid: bars([1, 2], 5)})


def test_a_feature_reads_the_prints_of_each_of_its_buckets_by_side() -> None:
    # Step 3.6: the trades input joins each bucket's volumes by side on the row of its close, 0
    # in a bucket without prints of a date whose prints are held, and null where none are in
    # hand, as on a trade date without prints; and it is refused where it is not given.
    five = bars([10, 11, 12, 13], 5)
    graph = FeatureGraph.of({"delta": delta()}, "ES", FIVE)
    prints = pl.DataFrame(
        {
            "ts_close": [5 * MINUTE, 10 * MINUTE, 15 * MINUTE],
            "buy_volume": [3, 0, 2],
            "sell_volume": [1, 0, 5],
            "unknown_side_volume": [4, 0, 0],
        }
    )

    values = graph.evaluate({graph.signal_grid: five, PrintsGrid("ES", FIVE): prints})

    assert graph.grids() == (Grid("ES", FIVE), PrintsGrid("ES", FIVE))
    assert values["delta"].to_list() == [2, 0, -3, None]
    expected = "Expected the prints by side of ES 5m that delta reads, got bars of ES 5m"
    with pytest.raises(ValueError, match=re.escape(expected)):
        graph.evaluate({graph.signal_grid: five})


def test_a_trades_input_without_trades_warns_that_its_volumes_are_null() -> None:
    # The ponytail review: a provider holding bars alone gives a trades input no prints, so its
    # volumes are null on every row, which a computation, and so a run's record, warns of.
    store_with("ohlcv-1m")

    with pytest.warns(UserWarning, match="synthetic holds no trades of ES: the trades input of"):
        computed = ff.features.compute({"delta": delta()}, "ES", "5m", "2026-03-06", "2026-03-09")

    values = computed.collect()
    assert values.get_column("delta").null_count() == values.height > 0


def test_another_instrument_is_read_from_the_signal_instruments_provider_where_it_holds_it() -> (
    None
):
    # BACKLOG.md, step 3.7: a root two providers hold, neither the catalog's recommended source,
    # was refused with a request to name a provider that nothing could pass; the signal
    # instrument's provider is read where it holds the root, by every path that reads it.
    store_with("ohlcv-1m")
    data_dir = resolve_paths(os.environ).data_dir
    shutil.copytree(data_dir / "synthetic", data_dir / "imported")
    window = ("2026-03-06", "2026-03-09")
    graph = FeatureGraph.of({"btc_age": btc_age()}, "ES", FIVE)

    computed = ff.features.compute(
        {"btc_age": btc_age()}, "ES", "5m", *window, provider="synthetic"
    )
    loaded = load_inputs(graph, (date(2026, 3, 6), date(2026, 3, 9)), provider="synthetic")
    report = ff.features.validate(btc_age(), "ES", "5m", *window, provider="synthetic", seed=3)

    assert computed.collect().get_column("btc_age").drop_nulls().len() > 0
    assert not loaded[Grid("BTCUSDT-PERP", FIVE)].is_empty()
    assert report.provider == "synthetic"


def test_compute_and_validate_read_the_prints_by_side_of_the_fixtures() -> None:
    # Step 3.6: the feature cache and the leak detector load the trades input as a run does,
    # each date's prints of its front, and cut it at each instant as they cut the bars.
    store_with("trades", "ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")

    computed = ff.features.compute({"delta": delta()}, "ES", "5m", *window).collect()
    report = ff.features.validate(delta(), "ES", "5m", *window, seed=3)

    volumes = series_source("ES").side_volumes(FIVE, (date(2026, 3, 6), date(2026, 3, 9)))
    by_hand = volumes.select("ts_close", delta=pl.col("buy_volume") - pl.col("sell_volume"))
    assert computed.select("ts_close", "delta").equals(by_hand)
    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0


def test_the_lead_in_counts_back_the_sessions_that_hold_a_warmup(tmp_path: Path) -> None:
    # ES's session holds 276 five-minute buckets, so ATR(11)'s 275 bars before a Monday lie in
    # the Friday before it, ATR(14)'s 350 reach the Thursday, and no warm-up reads none.
    sessions = sessions_of(instruments.get("ES").session_calendar(), tmp_path)
    monday = date(2026, 3, 9)

    def lead_in(slots: dict[str, ff.features.FeatureSpec]) -> date:
        return FeatureGraph.of(slots, "ES", FIVE).lead_in(sessions, monday)

    assert lead_in({"atr": atr(n=11)}) == date(2026, 3, 6)
    assert lead_in({"atr": atr(n=14)}) == date(2026, 3, 5)
    assert lead_in({"close_15m": close_15m()}) == date(2026, 3, 6)
    assert lead_in({}) == monday


def test_the_lead_in_stops_a_week_into_the_session_table(tmp_path: Path) -> None:
    # The Phase 3 exit's reviews: the lead-in raised once a warm-up reached past the session
    # table's first date, 2010-01-01, so a daily EMA(200), 2,600 sessions, could not be computed
    # from before 2020; it stops a week in, where a load still reads the session before.
    sessions = sessions_of(instruments.get("ES").session_calendar(), tmp_path)
    graph = FeatureGraph.of({"trend": ff.indicators.ema(200)}, "ES", Timeframe.parse("1d"))

    assert graph.lead_in(sessions, date(2015, 6, 1)) == date(2010, 1, 8)
    assert graph.lead_in(sessions, date(2026, 3, 9)) > date(2015, 1, 1)


CHAIN = {"step": step(), "swing": swing(), "blend": blend()}
"""The chain of three features, each with a warm-up of one bar after its inputs'."""


def test_compute_gives_the_bars_of_the_window_with_a_column_for_each_slot() -> None:
    store_with("ohlcv-1m")

    computed = ff.features.compute(CHAIN, "ES", "5m", "2026-03-09", "2026-03-09").collect()

    assert computed.columns == [*SIGNAL_BAR_COLUMNS, "step", "swing", "blend"]
    assert computed.get_column("trade_date").unique().to_list() == [date(2026, 3, 9)]
    window = ff.market.load("ES", "5m", "2026-03-09", "2026-03-09").collect()
    assert computed.select(SIGNAL_BAR_COLUMNS.names()).equals(window)


def test_compute_of_a_chain_of_three_features_gives_the_values_worked_out_directly() -> None:
    # Done means 2: the step, the sum of two steps, and twice that plus the step, worked out
    # with Polars over the bars of the session before the window and the window itself.
    store_with("ohlcv-1m")

    computed = ff.features.compute(CHAIN, "ES", "5m", "2026-03-09", "2026-03-09").collect()

    change = pl.col("close") - pl.col("close").shift(1)
    bars = ff.market.load("ES", "5m", "2026-03-06", "2026-03-09").collect()
    by_hand = bars.select(
        "trade_date",
        step=change,
        swing=change.rolling_sum(2),
        blend=2 * change.rolling_sum(2) + change,
    ).filter(pl.col("trade_date") == date(2026, 3, 9))
    assert computed.select("step", "swing", "blend").equals(by_hand.drop("trade_date"))


def test_warmups_carried_through_the_graph_leave_no_null_or_nan_in_the_window() -> None:
    # Done means 3: ATR(11) needs 275 bars and the chain 3, so a window from 2026-03-09 reads
    # them from the Friday before; a window from 03-06 has no session before it with a front,
    # so its first rows have no ATR, null and never NaN.
    store_with("ohlcv-1m")
    slots = {**CHAIN, "atr": atr(n=11)}
    columns = ["step", "swing", "blend", "atr"]

    monday = ff.features.compute(slots, "ES", "5m", "2026-03-09", "2026-03-09").collect()
    friday = ff.features.compute(slots, "ES", "5m", "2026-03-06", "2026-03-09").collect()

    assert monday.height == 276
    assert monday.select(pl.col(columns).null_count()).row(0) == (0, 0, 0, 0)
    assert friday.select(pl.col("atr").is_nan().sum()).item() == 0
    assert friday.select(pl.col("atr").null_count()).item() == 275
    assert friday.filter(pl.col("trade_date") == date(2026, 3, 9)).equals(monday)


def test_a_fifteen_minute_rsi_on_five_minute_bars_changes_only_at_its_closes() -> None:
    # The step's check on the fixtures: RSI(7) of the 15-minute bars, read on the 5-minute grid,
    # is the value of the last 15-minute bar closed by each row's close.
    store_with("ohlcv-1m")
    slots = {"rsi": rsi(n=7), "rsi_15m": rsi_15m()}

    computed = ff.features.compute(slots, "ES", "5m", "2026-03-09", "2026-03-09").collect()

    fifteen = ff.market.load("ES", "15m", "2026-03-05", "2026-03-09")
    own = rsi(n=7).evaluate(fifteen).collect()
    expected = own.select("ts_close", rsi_15m=pl.when(~pl.col("warmup")).then(pl.col("rsi")))
    joined = computed.select("ts_close").join_asof(expected, on="ts_close", strategy="backward")
    assert computed.get_column("rsi_15m").equals(joined.get_column("rsi_15m"))
    assert computed.get_column("rsi_15m").drop_nulls().len() > 0
    after_the_first = pl.int_range(pl.len()) > 0
    previous = pl.col("rsi_15m").shift(1)
    changes = computed.filter(pl.col("rsi_15m").ne_missing(previous), after_the_first)
    assert (changes.get_column("ts_close") % (15 * MINUTE) == 0).all()


def test_another_calendars_instrument_is_null_before_its_first_bar_then_stale() -> None:
    # BTCUSDT-PERP trades on UTC days and the fixtures hold its Saturday, 2026-03-07, alone:
    # ES's session of 03-06 closes before BTC's first bar, and ES's session of 03-09 reads BTC's
    # last bar, which closed at the end of that Saturday.
    store_with("ohlcv-1m")

    computed = ff.features.compute(
        {"btc_age": btc_age()}, "ES", "5m", "2026-03-06", "2026-03-09"
    ).collect()

    by_day = computed.group_by("trade_date").agg(
        pl.col("btc_age").null_count().alias("nulls"),
        (pl.col("ts_close") - pl.col("btc_age")).unique().alias("closes_read"),
    )
    saturday_ends = 1_772_928_000_000_000_000
    assert by_day.sort("trade_date").rows() == [
        (date(2026, 3, 6), 276, [None]),
        (date(2026, 3, 9), 0, [saturday_ends]),
    ]


def test_a_run_reads_its_strategys_features_as_compute_gives_them() -> None:
    # D-71: a feature previewed alone and the same feature inside a run see the same bars, read
    # from as far before the window, so they give the same values.
    store_with("ohlcv-1m")
    slots = {"rsi": rsi(n=7), "rsi_15m": rsi_15m()}
    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features=slots,
        long_entry=pl.col("rsi_15m") < 50,
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)),
    )

    run = ff.backtest.run(strategy, "2026-03-09", "2026-03-09")

    computed = ff.features.compute(slots, "ES", "5m", "2026-03-09", "2026-03-09").collect()
    columns = ["ts_close", "rsi", "rsi_15m"]
    assert run.signals.select(columns).equals(computed.select(columns))
    assert run.signals.get_column("rsi").null_count() == 0


def test_another_calendars_bars_are_the_same_in_a_window_ending_on_a_date_and_one_past_it() -> None:
    # The leakage audit of the step: bitcoin's trade date 2026-03-08 is the UTC day, and ES's
    # session of 03-09 opens at 22:00 UTC that day, so its rows from 22:05 read ES's bars of
    # 03-09, which a window ending on 03-08 once left unread, reading ES's Friday instead.
    store_with("ohlcv-1m")
    graph = FeatureGraph.of({"es_age": es_age()}, "BTCUSDT-PERP", FIVE)
    sunday_evening = int(datetime(2026, 3, 8, 22, tzinfo=UTC).timestamp()) // 60
    btc = bars([1] * 24, 5, start=sunday_evening)

    sunday = date(2026, 3, 8)
    ending = graph.evaluate({graph.signal_grid: btc, **load_inputs(graph, (sunday, sunday))})
    past = load_inputs(graph, (date(2026, 3, 8), date(2026, 3, 9)))
    running_past = graph.evaluate({graph.signal_grid: btc, **past})

    assert ending.equals(running_past)
    assert ending.get_column("es_age").to_list() == [0] * 24


def test_cutting_every_input_at_an_instant_leaves_every_earlier_value_as_it_was() -> None:
    # D-12 on the fixtures: the 5-minute and 15-minute bars of ES and bitcoin's bars cut at
    # instants through 2026-03-05 to 03-09, each at its own closes, give every row before the
    # cut the values the whole range gives.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    slots = {"rsi": rsi(n=7), "rsi_15m": rsi_15m(), "btc_age": btc_age(), **CHAIN}
    graph = FeatureGraph.of(slots, "ES", FIVE)
    dates = (date(2026, 3, 5), date(2026, 3, 9))
    signal = ff.market.load("ES", "5m", *dates).collect()
    inputs = {graph.signal_grid: signal, **load_inputs(graph, dates)}
    whole = graph.evaluate(inputs)
    closes = signal.get_column("ts_close")

    for cut in [*closes.gather_every(7).to_list(), closes.max()]:
        before = {grid: frame.filter(pl.col("ts_close") <= cut) for grid, frame in inputs.items()}
        assert graph.evaluate(before).equals(whole.filter(pl.col("ts_close") <= cut)), cut


def test_a_run_keeps_a_column_for_each_output_of_a_feature_at_each_entry() -> None:
    # The code review: a slot of a feature of several outputs fills `<slot>_<output>` columns,
    # which the run's trades carry at entry and its record names, where the slot's name alone
    # was read and the run could not be saved.
    store_with("ohlcv-1m")
    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"band": band()},
        long_entry=pl.col("close") >= pl.col("band_upper"),
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)),
    )

    run = ff.backtest.run(strategy, "2026-03-06", "2026-03-09")

    assert run.trades.height > 0
    assert {"band_upper_at_entry", "band_lower_at_entry"} <= set(run.trades.columns)
    assert run.record.strategy.features == ("band_upper", "band_lower")


def test_load_inputs_of_a_graph_reading_its_signal_grid_alone_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The code review: a notebook's strategy whose features read the signal grid alone opens no
    # store to load the other grids it does not read.
    def refused(*_: object, **__: object) -> object:
        raise AssertionError("Expected nothing read, got the store opened")

    monkeypatch.setattr("fefat.features.grids.series_source", refused)
    graph = FeatureGraph.of({"step": step()}, "ES", FIVE)

    assert load_inputs(graph, (date(2026, 3, 6), date(2026, 3, 9))) == {}


OTHER_STEP = """\
@ff.feature(warmup=1, outputs={"step": "price_distance"})
def step(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").diff()
"""
"""Another version of `step`, as a cell run again after an edit defines it."""


def test_a_feature_read_with_its_defaults_beside_a_slot_of_another_version_is_refused() -> None:
    # The ponytail review: a reader defined before its dependency's cell ran again reads the
    # old version, which a slot of the new one beside it would hide.
    edited = features_of_cell(OTHER_STEP)["step"]
    refusal = (
        f"Expected the feature step that swing reads, {step.hash[:12]}, got another step in a "
        f"slot, {edited.hash[:12]}"
    )

    with pytest.raises(ValueError, match=re.escape(refusal)):
        FeatureGraph.of({"swing": swing(), "step": edited()}, "ES", FIVE)
