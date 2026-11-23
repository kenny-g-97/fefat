"""A run's trades as histograms (step 5.7, D-116): net P&L in the currency, the R multiple, the MAE
and the MFE in ticks, and the minutes held. A histogram's bins share one width, the smallest of 1,
2, and 5 times a power of ten that gives at most `MOST_BINS`, its finest a cent, a hundredth of an
R, a tick, or a hundredth of a minute. Their edges are multiples of the width, so that no bin
straddles zero, and a bin holds its lower edge and not its upper, so that a trade that breaks even
stands above zero. Each trade is placed in whole numbers of the finest width, never through a
float, so that a value on an edge stands in the bin that edge names. A trade without a stop has no
R multiple and is counted apart.

    ff.backtest.trade_distributions(run.trades).pnl
"""

from collections.abc import Iterator
from itertools import count

import polars as pl
from pydantic import Field

from fefat.market.schema import FrozenModel

MOST_BINS = 40
"""The most bins a histogram holds."""
_HUNDREDTHS = 100
_MICRO_UNITS_A_CENT = 10_000
_NANOSECONDS_A_HUNDREDTH_OF_A_MINUTE = 600_000_000


class Histogram(FrozenModel):
    """Trades counted in bins of one width, one entry a bin in each column, in order: each bin
    from `lower` up to but not including `upper`, holding `trades` trades, none where a measure
    has no value."""

    lower: tuple[float, ...]
    upper: tuple[float, ...]
    trades: tuple[int, ...]


class TradeDistributions(FrozenModel):
    """A run's trades by net P&L in the currency, R multiple, MAE and MFE in ticks, and minutes
    held, with how many trades have no R multiple, having no stop."""

    pnl: Histogram
    r_multiple: Histogram
    trades_without_r_multiple: int = Field(ge=0)
    mae_ticks: Histogram
    mfe_ticks: Histogram
    holding_minutes: Histogram


def trade_distributions(trades: pl.DataFrame) -> TradeDistributions:
    """The histograms of `trades`, a run's trades artifact (module docstring)."""
    measures = trades.select(
        pnl=pl.col("pnl") // _MICRO_UNITS_A_CENT,
        r_multiple=pl.col("pnl") * _HUNDREDTHS // pl.col("initial_risk"),
        holding_minutes=(pl.col("exit_ts") - pl.col("entry_ts"))
        // _NANOSECONDS_A_HUNDREDTH_OF_A_MINUTE,
    )
    r_multiple = measures.get_column("r_multiple")
    return TradeDistributions(
        pnl=_histogram(measures.get_column("pnl"), _HUNDREDTHS),
        r_multiple=_histogram(r_multiple, _HUNDREDTHS),
        trades_without_r_multiple=r_multiple.null_count(),
        mae_ticks=_histogram(trades.get_column("mae_ticks"), 1),
        mfe_ticks=_histogram(trades.get_column("mfe_ticks"), 1),
        holding_minutes=_histogram(measures.get_column("holding_minutes"), _HUNDREDTHS),
    )


def _histogram(values: pl.Series, per_unit: int) -> Histogram:
    """The histogram of `values`, whole counts of `1 / per_unit` of their measure, nulls left
    out; every bin from the first that holds a value to the last, empty ones included."""
    held = values.drop_nulls().to_frame("value")
    if held.is_empty():
        return Histogram(lower=(), upper=(), trades=())
    low, high = held.select(pl.col("value").min(), pl.col("value").max().alias("high")).row(0)
    width = _width(low, high)
    counted = held.group_by(bin=pl.col("value") // width).len("trades")
    every_bin = pl.int_range(low // width, high // width + 1, eager=True).to_frame("bin")
    bins = every_bin.join(counted, on="bin", how="left", maintain_order="left").fill_null(0)
    numbers = bins.get_column("bin").to_list()
    return Histogram(
        lower=tuple(number * width / per_unit for number in numbers),
        upper=tuple((number + 1) * width / per_unit for number in numbers),
        trades=tuple(bins.get_column("trades").to_list()),
    )


def _width(low: int, high: int) -> int:
    """The smallest of 1, 2, and 5 times a power of ten whose multiples hold `low` to `high` in
    at most `MOST_BINS` bins."""
    return next(width for width in _widths() if high // width - low // width < MOST_BINS)


def _widths() -> Iterator[int]:
    """1, 2, 5, 10, 20, 50, and so on."""
    for exponent in count():
        for step in (1, 2, 5):
            yield step * 10**exponent
