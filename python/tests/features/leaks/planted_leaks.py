"""Twenty-five features planted for the leak detector of step 3.4 to flag (Done means 1): each reads
ahead, or remembers more than its warm-up, in one of the ways features do, and names the checks
that must flag it, the cuts, the start check, or the lint. Each is validated on ES's 1-minute bars
of `generated_minutes.february_store`, whose quiet minutes leave the grid's buckets empty, so that
a forward as-of join of the traded bars shows its look-ahead (the step's amendment)."""

from dataclasses import dataclass
from enum import StrEnum

import polars as pl

import fefat as ff
from fefat.features import FeatureSpec


class Check(StrEnum):
    """A check of the detector that may flag a feature."""

    CUTS = "cuts"
    START = "start"
    LINT = "lint"


@dataclass(frozen=True)
class Planted:
    """A planted feature with its parameters and the checks that must flag it."""

    spec: FeatureSpec
    caught_by: frozenset[Check]


@ff.feature(outputs={"next_close": "price"})
def next_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").shift(-1)


@ff.feature(params={"n": 5}, outputs={"forward_return": "ratio"})
def forward_return(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").shift(-n) / pl.col("close") - 1


@ff.feature(outputs={"next_change": "price_distance"})
def next_change(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").diff(-1)


@ff.feature(outputs={"zscore": "ratio"})
def zscore_full_sample(bars: pl.LazyFrame) -> pl.Expr:
    return (pl.col("close") - pl.col("close").mean()) / pl.col("close").std()


@ff.feature(outputs={"scaled": "ratio"})
def minmax_full_sample(bars: pl.LazyFrame) -> pl.Expr:
    close = pl.col("close")
    return (close - close.min()) / (close.max() - close.min())


@ff.feature(outputs={"rank": "ratio"})
def rank_full_sample(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").rank()


@ff.feature(outputs={"to_last": "ratio"})
def return_to_last_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").last() / pl.col("close") - 1


@ff.feature(outputs={"centred_mean": "price"})
def centred_mean(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").rolling_mean(window_size=21, center=True)


@ff.feature(outputs={"pivot": "flag"})
def repainting_pivot(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("high") == pl.col("high").rolling_max(window_size=11, center=True)


@ff.feature(warmup=1, outputs={"swing_high": "flag"})
def swing_high_next_bar(bars: pl.LazyFrame) -> pl.Expr:
    high = pl.col("high")
    return (high > high.shift(1)) & (high > high.shift(-1))


@ff.feature(outputs={"next_up_close": "price"})
def backfilled_up_close(bars: pl.LazyFrame) -> pl.Expr:
    up = pl.col("close") > pl.col("open")
    return pl.when(up).then(pl.col("close")).fill_null(strategy="backward")


@ff.feature(outputs={"between_ups": "price"})
def interpolated_up_close(bars: pl.LazyFrame) -> pl.Expr:
    up = pl.col("close") > pl.col("open")
    return pl.when(up).then(pl.col("close")).interpolate()


@ff.feature(outputs={"bucket_high": "price"})
def bucket_high_in_progress(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("high").max().over(pl.col("ts_open") // 900_000_000_000)


@ff.feature(outputs={"bucket_high": "price"})
def bucket_high_by_open(bars: pl.LazyFrame) -> pl.LazyFrame:
    opens = pl.col("ts_open") // 900_000_000_000 * 900_000_000_000
    buckets = bars.group_by(opens.alias("ts_open")).agg(bucket_high=pl.col("high").max())
    return bars.join_asof(buckets.sort("ts_open"), on="ts_open").select("ts_close", "bucket_high")


@ff.feature(outputs={"session_mean": "price"})
def session_mean_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").mean().over("trade_date")


@ff.feature(outputs={"position": "ratio"})
def session_range_position(bars: pl.LazyFrame) -> pl.Expr:
    low, high = pl.col("low").min().over("trade_date"), pl.col("high").max().over("trade_date")
    return (pl.col("close") - low) / (high - low)


@ff.feature(outputs={"session_close": "price"})
def session_close_joined(bars: pl.LazyFrame) -> pl.LazyFrame:
    closes = bars.group_by("trade_date").agg(session_close=pl.col("close").last())
    joined = bars.join(closes, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "session_close")


@ff.feature(outputs={"vwap_to_close": "price"})
def vwap_to_session_close(bars: pl.LazyFrame) -> pl.Expr:
    weighted = pl.col("close").cast(pl.Float64) * pl.col("volume")
    volume = pl.col("volume").cast(pl.Float64)
    return weighted.cum_sum(reverse=True).over("trade_date") / volume.cum_sum(reverse=True).over(
        "trade_date"
    )


@ff.feature(outputs={"vwap_from_low": "price"})
def vwap_from_session_low(bars: pl.LazyFrame) -> pl.Expr:
    at_low = (pl.col("low") == pl.col("low").min().over("trade_date")).cast(pl.UInt8)
    after = at_low.cum_max().over("trade_date") == 1
    weighted = pl.when(after).then(pl.col("close").cast(pl.Float64) * pl.col("volume"))
    volume = pl.when(after).then(pl.col("volume").cast(pl.Float64))
    return weighted.cum_sum().over("trade_date") / volume.cum_sum().over("trade_date")


@ff.feature(outputs={"traded_close": "price"})
def forward_joined_traded_close(bars: pl.LazyFrame) -> pl.LazyFrame:
    traded = bars.filter(~pl.col("zero_volume")).select("ts_close", traded_close="close")
    return bars.select("ts_close").join_asof(traded, on="ts_close", strategy="forward")


@ff.feature(outputs={"up_close": "price"})
def nearest_joined_up_close(bars: pl.LazyFrame) -> pl.LazyFrame:
    up = bars.filter(pl.col("close") > pl.col("open")).select("ts_close", up_close="close")
    return bars.select("ts_close").join_asof(up, on="ts_close", strategy="nearest")


@ff.feature(outputs={"high_ahead": "price"})
def future_max_reversed(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("high").reverse().cum_max().reverse()


@ff.feature(outputs={"total": "price"})
def running_total(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").cum_sum()


@ff.feature(outputs={"bar_number": "count"})
def bar_number(bars: pl.LazyFrame) -> pl.Expr:
    return pl.int_range(pl.len())


@ff.feature(warmup=14, outputs={"slow_average": "price"})
def slow_average(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").ewm_mean(alpha=0.001)


AHEAD = frozenset({Check.CUTS, Check.LINT})
"""A look-ahead the cuts show and the lint reads."""

PLANTED = (
    Planted(next_close(), AHEAD),
    Planted(forward_return(), AHEAD),
    Planted(next_change(), AHEAD),
    Planted(zscore_full_sample(), AHEAD),
    Planted(minmax_full_sample(), AHEAD),
    Planted(rank_full_sample(), AHEAD),
    Planted(return_to_last_close(), AHEAD),
    Planted(centred_mean(), AHEAD),
    Planted(repainting_pivot(), AHEAD),
    Planted(swing_high_next_bar(), AHEAD),
    Planted(backfilled_up_close(), AHEAD),
    Planted(interpolated_up_close(), AHEAD),
    Planted(bucket_high_in_progress(), AHEAD),
    Planted(bucket_high_by_open(), AHEAD),
    Planted(session_mean_close(), AHEAD),
    Planted(session_range_position(), AHEAD),
    Planted(session_close_joined(), frozenset({Check.CUTS})),
    Planted(vwap_to_session_close(), AHEAD),
    Planted(vwap_from_session_low(), AHEAD),
    Planted(forward_joined_traded_close(), AHEAD),
    Planted(nearest_joined_up_close(), AHEAD),
    Planted(future_max_reversed(), AHEAD),
    Planted(running_total(), frozenset({Check.START})),
    Planted(bar_number(), frozenset({Check.START})),
    Planted(slow_average(), frozenset({Check.START})),
)
"""The planted features: look-ahead shifts and differences, normalisation, scaling, ranks, and the
last value over the full sample, centred windows and a repainting pivot, backward fills, a
higher-timeframe bucket read while in progress, aggregates over a session that has not ended, a
session's close joined to its rows, future-anchored VWAPs, wrong-direction joins, a reversed
maximum, and three that remember more than their warm-up."""
