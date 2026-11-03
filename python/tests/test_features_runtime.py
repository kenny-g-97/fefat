"""The feature runtime of step 3.2 (`02-engine-and-data.md` §6, D-71), on bars built by hand and
through `ff.features.compute` on the fixtures: features evaluated in the order their
dependencies give, a higher timeframe's bar seen from its close and never in progress, another
instrument's bars joined as of each close with their staleness, and each feature's warm-up
carried through the graph and read from before the window."""

import dataclasses
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.features import (
    DatasetInput,
    FeatureInput,
    InstrumentInput,
    TimeframeInput,
    TradesInput,
)
from fefat.features.examples import atr, rsi
from fefat.features.runtime import FeatureGraph, Grid
from fefat.market import instruments
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import sessions_of
from fefat.market.schema import Timeframe
from notebook_runs import store_with

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


@ff.feature(inputs=[TradesInput()], outputs={"delta": "other"})
def delta(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")


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
            {"swing": swing()},
            "Expected the feature step that swing reads among the features given, once with its "
            "parameters, got none: give it a slot, such as step(...).",
        ),
        (
            {"fast": rsi(n=7), "slow": rsi(n=14), "stretched": stretched()},
            "Expected the feature rsi that stretched reads among the features given, once with "
            "its parameters, got",
        ),
        (
            {"delta": delta()},
            "Expected inputs the runtime evaluates, got the trades input of feature delta, whose "
            "prints by bucket wait for step 3.6.",
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


def test_bars_a_feature_reads_but_not_given_are_refused() -> None:
    graph = FeatureGraph.of({"nq": nq_close()}, "ES", FIVE)

    with pytest.raises(ValueError, match="Expected the bars of NQ 5m that nq_close reads, got"):
        graph.evaluate({graph.signal_grid: bars([1, 2], 5)})


def test_the_lead_in_counts_back_the_sessions_that_hold_a_warmup(tmp_path: Path) -> None:
    # ES's session holds 276 five-minute buckets, so ATR(14)'s 140 bars before a Monday lie in
    # the Friday before it, ATR(30)'s 300 reach the Thursday, and no warm-up reads none.
    sessions = sessions_of(instruments.get("ES").session_calendar(), tmp_path)
    monday = date(2026, 3, 9)

    def lead_in(slots: dict[str, ff.features.FeatureSpec]) -> date:
        return FeatureGraph.of(slots, "ES", FIVE).lead_in(sessions, monday)

    assert lead_in({"atr": atr(n=14)}) == date(2026, 3, 6)
    assert lead_in({"atr": atr(n=30)}) == date(2026, 3, 5)
    assert lead_in({"close_15m": close_15m()}) == date(2026, 3, 6)
    assert lead_in({}) == monday


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
    # Done means 3: ATR(14) needs 140 bars and the chain 3, so a window from 2026-03-09 reads
    # them from the Friday before; a window from 03-06 has no session before it with a front,
    # so its first rows have no ATR, null and never NaN.
    store_with("ohlcv-1m")
    slots = {**CHAIN, "atr": atr(n=14)}
    columns = ["step", "swing", "blend", "atr"]

    monday = ff.features.compute(slots, "ES", "5m", "2026-03-09", "2026-03-09").collect()
    friday = ff.features.compute(slots, "ES", "5m", "2026-03-06", "2026-03-09").collect()

    assert monday.height == 276
    assert monday.select(pl.col(columns).null_count()).row(0) == (0, 0, 0, 0)
    assert friday.select(pl.col("atr").is_nan().sum()).item() == 0
    assert friday.select(pl.col("atr").null_count()).item() == 140
    assert friday.filter(pl.col("trade_date") == date(2026, 3, 9)).equals(monday)


def test_a_fifteen_minute_rsi_on_five_minute_bars_changes_only_at_its_closes() -> None:
    # The step's check on the fixtures: RSI(14) of the 15-minute bars, read on the 5-minute grid,
    # is the value of the last 15-minute bar closed by each row's close.
    store_with("ohlcv-1m")
    slots = {"rsi": rsi(n=14), "rsi_15m": rsi_15m()}

    computed = ff.features.compute(slots, "ES", "5m", "2026-03-09", "2026-03-09").collect()

    fifteen = ff.market.load("ES", "15m", "2026-03-05", "2026-03-09")
    own = rsi(n=14).evaluate(fifteen).collect()
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
    slots = {"rsi": rsi(n=14), "rsi_15m": rsi_15m()}
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
