"""Relative volume, realised volatility, and cumulative delta of step 3.6, by hand (Done means 1):
relative volume reads only the sessions before a bar's own (Done means 2), and cumulative delta
equals a direct computation on the fixtures' ES prints (Done means 3), null through a session
whose prints carry no side and on a trade date without prints."""

import math
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.features.grids import PrintsGrid
from fefat.features.runtime import FeatureGraph
from fefat.market.schema import Timeframe
from notebook_runs import SYNTHETIC, store_with
from session_bars import FIVE_MINUTES, chicago, frame, traded, values_of

FIVE = Timeframe.parse("5m")
FRIDAY, MONDAY, TUESDAY = date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)
VOLUMES = [(10, 20), (30, 40), (50, 60), (70, 80), (90, 100)]
"""The volumes of five sessions' bars opening at 08:30 and 08:35 Chicago."""


def sessions_of_volume(volumes: list[tuple[int, int]]) -> pl.DataFrame:
    """A session for each pair of `volumes`, of two bars at 08:30 and 08:35 Chicago, on the trade
    dates of 2026-03-04 to 03-10, across the clock change of 03-08, after which 08:30 Chicago is
    13:30 UTC, no longer 14:30: a bar's time of day is Chicago's, never UTC's."""
    days = [date(2026, 3, day) for day in (4, 5, 6, 9, 10)]
    return frame(
        *(
            traded(day, clock, 100, volume)
            for day, pair in zip(days, volumes, strict=True)
            for clock, volume in zip(["08:30", "08:35"], pair, strict=True)
        )
    )


def test_relative_volume_divides_by_the_mean_at_its_time_of_day_over_the_sessions_before() -> None:
    # Over two sessions: the third session's bar of 08:30 against the first two's, 50 / 20, and
    # so on, each time of day apart; the first two sessions are its warm-up.
    spec = ff.indicators.relative_volume(sessions=2)

    computed = values_of(spec, sessions_of_volume(VOLUMES), "relative_volume")

    assert computed[4:] == pytest.approx([50 / 20, 60 / 30, 70 / 40, 80 / 50, 90 / 60, 100 / 70])
    assert spec.warmup_sessions == 2


def test_relative_volume_reads_only_the_sessions_before_its_own() -> None:
    # Done means 2: a session's own volume never enters its mean, nor a later session's, so a
    # louder last session changes its own values through their volume alone, and none before.
    spec = ff.indicators.relative_volume(sessions=2)
    quiet = values_of(spec, sessions_of_volume(VOLUMES), "relative_volume")
    loud = values_of(spec, sessions_of_volume([*VOLUMES[:4], (900, 1000)]), "relative_volume")

    assert loud[:8] == quiet[:8]
    assert loud[8:] == pytest.approx([900 / 60, 1000 / 70])


def test_realised_volatility_is_the_root_of_the_sum_of_squared_log_returns() -> None:
    clocks = ["08:00", "08:05", "08:10", "08:15"]
    bars = frame(
        *(
            traded(FRIDAY, clock, price)
            for clock, price in zip(clocks, [100, 110, 99, 99], strict=True)
        )
    )
    up, down = math.log(110 / 100), math.log(99 / 110)

    computed = values_of(ff.indicators.realised_volatility(n=2), bars, "realised_volatility")

    assert computed == [None, None, pytest.approx(math.hypot(up, down)), pytest.approx(-down)]


def test_realised_volatility_is_null_where_a_close_is_not_above_zero() -> None:
    # A spliced crude oil can close at or below zero, whose returns have no logarithm.
    clocks = ["08:00", "08:05", "08:10"]
    bars = frame(
        *(traded(FRIDAY, clock, price) for clock, price in zip(clocks, [100, 0, 100], strict=True))
    )

    computed = values_of(ff.indicators.realised_volatility(n=1), bars, "realised_volatility")

    assert computed == [None, None, None]


def test_cumulative_delta_counts_sided_prints_and_is_null_where_no_side_is_known() -> None:
    # Friday's first bucket holds prints of no side alone, its second 3 bought and 1 sold, its
    # third none, and its fourth 2 bought and 4 sold; Monday's prints carry no side, as IBKR's
    # do; Tuesday has no prints in hand.
    clocks = ["08:00", "08:05", "08:10", "08:15"]
    rows = [traded(FRIDAY, clock, 10) for clock in clocks]
    rows += [traded(MONDAY, clock, 10) for clock in clocks[:3]] + [traded(TUESDAY, "08:00", 10)]
    bars = frame(*rows)
    sides = [(0, 0, 5), (3, 1, 0), (0, 0, 0), (2, 4, 0), (0, 0, 4), (0, 0, 0), (0, 0, 6)]
    prints = pl.DataFrame(
        sides, schema=["buy_volume", "sell_volume", "unknown_side_volume"], orient="row"
    ).with_columns(ts_close=bars.get_column("ts_close").head(len(sides)))
    graph = FeatureGraph.of({"flow": ff.indicators.cumulative_delta()}, "ES", FIVE)

    values = graph.evaluate({graph.signal_grid: bars, PrintsGrid("ES", FIVE): prints})

    assert values.get_column("flow_delta").to_list() == [None, 2, 0, -2, *[None] * 4]
    assert values.get_column("flow_cumulative_delta").to_list() == [None, 2, 2, 0, *[None] * 4]


def test_cumulative_delta_equals_a_direct_computation_on_the_fixtures_es_trades() -> None:
    # Done means 3: on 2026-03-06, ESH2026's prints of the session, read from the fixture's file
    # in place, bucketed by five minutes from the open by their ts_recv, buys less sells: the
    # print received 400 ms after the close lies in no bucket, and the opening print, of no side,
    # in the first, which still has a value.
    store_with("trades", "ohlcv-1m")
    flow = {"flow": ff.indicators.cumulative_delta()}

    computed = ff.features.compute(flow, "ES", "5m", "2026-03-06", "2026-03-06").collect()

    path = Path("trades/root=ES/contract=ESH2026/date=2026-03-06/part.parquet")
    prints = pl.read_parquet(SYNTHETIC / path)
    opened, closed = chicago(date(2026, 3, 5), "17:00"), chicago(FRIDAY, "16:00")
    size = pl.col("size").cast(pl.Int64)
    signed = pl.when(pl.col("side") == "B").then(size).when(pl.col("side") == "A").then(-size)
    sums = (
        prints.filter(pl.col("ts_recv") < closed)
        .group_by(bucket=(pl.col("ts_recv") - opened) // FIVE_MINUTES)
        .agg(delta=signed.fill_null(0).sum())
    )
    buckets = pl.DataFrame({"bucket": range((closed - opened) // FIVE_MINUTES)})
    by_hand = buckets.join(sums, on="bucket", how="left").sort("bucket").fill_null(0)
    assert computed.height == by_hand.height == 276
    assert prints.filter(pl.col("side") == "N").height == 1
    assert computed.get_column("flow_delta").to_list() == by_hand.get_column("delta").to_list()
    cumulative = by_hand.get_column("delta").cum_sum().to_list()
    assert computed.get_column("flow_cumulative_delta").to_list() == cumulative
