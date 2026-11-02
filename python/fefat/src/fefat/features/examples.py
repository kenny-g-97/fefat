"""Three example features (step 3.1), written as any feature is, with `@ff.feature` over the
signal bars: RSI as `02-engine-and-data.md` §5 writes it, ATR in the bars' 1e-9 units of price,
and a flag of a window of the trading day. `fefat.indicators` (steps 3.5 and 3.6) holds the
library's indicators, matched to TA-Lib; these show the contract.

    from fefat.features.examples import atr, in_session_window, rsi

    rsi(n=14).evaluate(bars)
"""

from datetime import time

import polars as pl

from fefat.features.definition import feature
from fefat.market.calendar_definition import LocalTime, TimeZoneName


@feature(params={"n": 14}, warmup=lambda n: 10 * n, outputs={"rsi": "ratio"})
def rsi(bars: pl.LazyFrame, n: int) -> pl.Expr:
    """The relative strength index of the closes over `n` bars, from 0 to 100, as `02` §5 writes
    it: 100 less 100 over one plus the closes' mean rise over their mean fall, each mean weighing
    a bar 1 - 1/n times the bar after it (`ewm_mean(alpha=1/n)`), and null where the closes have
    not moved. By its warm-up of ten times `n` bars the weight of the bars before has fallen below
    a ten-thousandth; TA-Lib seeds its means otherwise, which step 3.5 matches."""
    change = pl.col("close").diff()
    rise, fall = change.clip(lower_bound=0), (-change).clip(lower_bound=0)
    return 100 - 100 / (1 + rise.ewm_mean(alpha=1 / n) / fall.ewm_mean(alpha=1 / n))


@feature(params={"n": 14}, warmup=lambda n: 10 * n, outputs={"atr": "price_distance"})
def atr(bars: pl.LazyFrame, n: int) -> pl.Expr:
    """The average true range over `n` bars in the bars' 1e-9 units of price, the units in which
    the execution template reads it (`ff.Stop(atr=1.5)`, F-RND-01): each bar's true range, its
    high less its low widened to the close before it, averaged as `rsi` averages; the first
    bar's range is its high less its low."""
    previous = pl.col("close").shift(1)
    true_range = pl.max_horizontal("high", previous) - pl.min_horizontal("low", previous)
    return true_range.ewm_mean(alpha=1 / n)


@feature(
    params={"start": "08:30", "end": "15:00", "time_zone": "America/Chicago"},
    outputs={"in_session_window": "flag"},
)
def in_session_window(
    bars: pl.LazyFrame, start: LocalTime, end: LocalTime, time_zone: TimeZoneName
) -> pl.Expr:
    """True on the bars that close inside the window of the day from `start` to just before
    `end`, local times in `time_zone`, past midnight when `end` comes first, as F-TIM-04 reads
    an entry window: by default the cash session of CME's equity index, 08:30 to 15:00 Chicago.
    The window follows the local clock across its changes."""
    clock = pl.col("ts_close").cast(pl.Datetime("ns", "UTC")).dt.convert_time_zone(time_zone)
    local, opens, closes = clock.dt.time(), time.fromisoformat(start), time.fromisoformat(end)
    if opens <= closes:
        return (local >= opens) & (local < closes)
    return (local >= opens) | (local < closes)
