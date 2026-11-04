"""Prices on the tick (step 3.5, F-RND-01): a price worked out from features, such as a stop at
the bar's low less half an ATR, rounded down or up to the instrument's tick, as the trader asks,
so that the execution template takes it as `stop_price`, `target_price`, `entry_price`, or
`trail_ref`, which must lie on the tick.

    stop_price=ff.indicators.round_down_to_tick(pl.col("low") - pl.col("atr") / 2, "ES")
"""

import os

import polars as pl

from fefat.config import resolve_paths
from fefat.market.engine_units import instrument_parameters
from fefat.market.saved_instruments import instrument_table


def round_down_to_tick(price: pl.Expr, instrument: str) -> pl.Expr:
    """`price`, in the bars' 1e-9 units, rounded down to the tick of the root `instrument`, as
    integers; a float is first rounded to whole units, so that a price float arithmetic leaves a
    hair below a tick stays on that tick, and one that is no finite number is null."""
    tick = instrument_tick(instrument)
    return _whole_units(price) // tick * tick


def round_up_to_tick(price: pl.Expr, instrument: str) -> pl.Expr:
    """`price`, in the bars' 1e-9 units, rounded up to the tick of the root `instrument`, as
    integers; a float is first rounded to whole units, so that a price float arithmetic leaves a
    hair above a tick stays on that tick, and one that is no finite number is null."""
    tick = instrument_tick(instrument)
    return -(-_whole_units(price) // tick) * tick


def _whole_units(price: pl.Expr) -> pl.Expr:
    return pl.when(price.is_finite()).then(price.round(0)).cast(pl.Int64)


def instrument_tick(instrument: str) -> int:
    """The tick of the root `instrument` in 1e-9 units of price, from its newest specification
    among those a run reads: the static table's and those saved in the data folder."""
    table = instrument_table(resolve_paths(os.environ).data_dir)
    return instrument_parameters(table.get(instrument)).tick
