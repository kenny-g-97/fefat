"""Twenty-five prefix-invariant features the leak detector of step 3.4 must pass (Done means 1),
each reading only bars closed by its row's close and declaring the warm-up it needs: the examples,
averages and deviations over past bars, session-anchored running values, a session's open and
opening range, the session before, a forward fill, a backward as-of join, a higher timeframe's last
closed bar, another timeframe's features, another instrument on the same calendar and one on
another, bitcoin's, whose trade dates are UTC days, through the runtime, and counts.
They run where the planted features do (`planted_leaks`)."""

from dataclasses import dataclass

import polars as pl

import fefat as ff
from fefat.features import FeatureSpec, InstrumentInput, TimeframeInput
from fefat.features.examples import atr, in_session_window, rsi


@dataclass(frozen=True)
class Clean:
    """A clean feature with its parameters and the features it reads, which a validation is
    given as `compute` is."""

    spec: FeatureSpec
    reads: tuple[FeatureSpec, ...] = ()


@ff.feature(params={"n": 20}, warmup=lambda n: n, outputs={"sma": "price"})
def sma(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(window_size=n)


@ff.feature(params={"n": 20}, warmup=lambda n: 25 * n, outputs={"ema": "price"})
def ema(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").ewm_mean(alpha=2 / (n + 1))


@ff.feature(params={"n": 20}, warmup=lambda n: n, outputs={"deviation": "price_distance"})
def rolling_std(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_std(window_size=n)


@ff.feature(params={"n": 20}, warmup=lambda n: n, outputs={"band_position": "ratio"})
def bollinger_position(bars: pl.LazyFrame, n: int) -> pl.Expr:
    close = pl.col("close")
    return (close - close.rolling_mean(window_size=n)) / close.rolling_std(window_size=n)


@ff.feature(warmup=1, outputs={"previous_close": "price"})
def previous_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").shift(1)


@ff.feature(warmup=1, outputs={"bar_return": "ratio"})
def bar_return(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") / pl.col("close").shift(1) - 1


@ff.feature(outputs={"session_vwap": "price"})
def session_vwap(bars: pl.LazyFrame) -> pl.Expr:
    weighted = pl.col("close").cast(pl.Float64) * pl.col("volume")
    volume = pl.col("volume").cast(pl.Float64)
    return weighted.cum_sum().over("trade_date") / volume.cum_sum().over("trade_date")


@ff.feature(outputs={"high_so_far": "price"})
def session_high_so_far(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("high").cum_max().over("trade_date")


@ff.feature(outputs={"bars_since_open": "count"})
def bars_since_open(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").cum_count().over("trade_date")


@ff.feature(outputs={"session_open": "price"})
def session_open(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("open").first().over("trade_date")


@ff.feature(params={"minutes": 30}, outputs={"range_high": "price"})
def opening_range_high(bars: pl.LazyFrame, minutes: int) -> pl.Expr:
    since_open = pl.col("ts_close") - pl.col("ts_open").first().over("trade_date")
    inside = since_open <= minutes * 60_000_000_000
    high_inside = pl.when(inside).then(pl.col("high")).cum_max().over("trade_date")
    return pl.when(~inside).then(high_inside.forward_fill().over("trade_date"))


@ff.feature(warmup=1380, outputs={"prior_high": "price"})
def prior_session_high(bars: pl.LazyFrame) -> pl.LazyFrame:
    highs = bars.group_by("trade_date").agg(prior_high=pl.col("high").max())
    shifted = highs.sort("trade_date").with_columns(pl.col("prior_high").shift(1))
    joined = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "prior_high")


@ff.feature(warmup=1, outputs={"traded_close": "price"})
def forward_filled_traded_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.when(~pl.col("zero_volume")).then(pl.col("close")).forward_fill()


@ff.feature(warmup=60, outputs={"hourly_mean": "price"})
def rolling_mean_by_hour(bars: pl.LazyFrame) -> pl.Expr:
    clock = pl.col("ts_close").cast(pl.Datetime("ns", "UTC"))
    return pl.col("close").rolling_mean_by(clock, window_size="1h")


@ff.feature(warmup=60, outputs={"up_close": "price"})
def backward_joined_up_close(bars: pl.LazyFrame) -> pl.LazyFrame:
    up = bars.filter(pl.col("close") > pl.col("open")).select("ts_close", up_close="close")
    return bars.select("ts_close").join_asof(up, on="ts_close", strategy="backward")


@ff.feature(warmup=15, outputs={"bucket_high": "price"})
def last_completed_bucket_high(bars: pl.LazyFrame) -> pl.LazyFrame:
    closes = (pl.col("ts_open") // 900_000_000_000 + 1) * 900_000_000_000
    buckets = bars.group_by(closes.alias("ts_close")).agg(bucket_high=pl.col("high").max())
    return bars.select("ts_close").join_asof(buckets.sort("ts_close"), on="ts_close")


@ff.feature(inputs=[rsi, TimeframeInput(timeframe="15m")], outputs={"rsi_15m": "ratio"})
def rsi_15m(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("rsi")


@ff.feature(inputs=[TimeframeInput(timeframe="1d")], outputs={"daily_close": "price"})
def last_daily_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")


@ff.feature(warmup=1, inputs=[InstrumentInput(root="NQ")], outputs={"spread": "price_distance"})
def nq_spread(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") - pl.col("close_NQ")


@ff.feature(warmup=1, outputs={"true_range": "price_distance"})
def true_range(bars: pl.LazyFrame) -> pl.Expr:
    previous = pl.col("close").shift(1)
    return pl.max_horizontal("high", previous) - pl.min_horizontal("low", previous)


@ff.feature(outputs={"up_bars": "count"})
def up_bars_today(bars: pl.LazyFrame) -> pl.Expr:
    return (pl.col("close") > pl.col("open")).cast(pl.UInt32).cum_sum().over("trade_date")


@ff.feature(warmup=1, inputs=[InstrumentInput(root="BTCUSDT-PERP")], outputs={"btc_wait": "other"})
def bitcoin_staleness(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("staleness_BTCUSDT-PERP")


CLEAN = (
    Clean(rsi(n=14)),
    Clean(atr(n=14)),
    Clean(in_session_window()),
    Clean(sma()),
    Clean(ema()),
    Clean(rolling_std()),
    Clean(bollinger_position()),
    Clean(previous_close()),
    Clean(bar_return()),
    Clean(session_vwap()),
    Clean(session_high_so_far()),
    Clean(bars_since_open()),
    Clean(session_open()),
    Clean(opening_range_high()),
    Clean(prior_session_high()),
    Clean(forward_filled_traded_close()),
    Clean(rolling_mean_by_hour()),
    Clean(backward_joined_up_close()),
    Clean(last_completed_bucket_high()),
    Clean(rsi_15m(), reads=(rsi(n=14),)),
    Clean(last_daily_close()),
    Clean(nq_spread()),
    Clean(true_range()),
    Clean(up_bars_today()),
    Clean(bitcoin_staleness()),
)
"""The clean features, each with what it reads."""
