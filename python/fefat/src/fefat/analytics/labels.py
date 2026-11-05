"""Labels, the forward returns a feature is judged against (`02-engine-and-data.md` §6, step 3.8).

A label reads the future, so it is never a feature and never feeds a strategy (D-12): a
`SignalStrategy` refuses a `Label` in a slot and any expression that reads a label's column,
`forward_return_<h>`. The forward return of horizon h at a bar is what a market order decided at
the bar's close makes when it is held h bars. It buys at the open of the first bucket with volume
after the bar, where that order fills (F-MKT-03), since a `zero_volume` bucket holds no trade to
fill at (F-BAR-07), and sells where the order decided at the close h bars later fills, found
alike. Both prices are the forward-anchored series', so a roll's gap is no return (D-09), and the
return, in ticks of the instrument, stays within the trade date: where no exit is left in it, the
label is null. A horizon counts the grid's bars, so a label across a halt spans more clock time.

    labelled = forward_returns(bars, horizons=(1, 5, 20), tick_units=250_000_000)
    labelled.select(Label(5).column)  # forward_return_5, in ticks
"""

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

LABEL_PREFIX = "forward_return_"
"""The names of the labels' columns: `forward_return_<h>` for a horizon of h bars."""
NEXT_OPEN = "next_open"
"""The column of each bar's entry: the open of the first bucket with volume after it."""
SESSION = ("contract", "trade_date")
"""What a label stays within: one contract's trade date."""


def is_label_column(name: str) -> bool:
    """Whether `name` is the column of a label, `forward_return_<h>`."""
    return name.startswith(LABEL_PREFIX)


@dataclass(frozen=True)
class Label:
    """The forward return over `horizon` bars, in ticks, held in the column `column`."""

    horizon: int

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon < 1:
            raise ValueError(
                f"Expected a label's horizon as a whole number of bars from 1, got "
                f"{self.horizon!r}."
            )

    @property
    def column(self) -> str:
        return f"{LABEL_PREFIX}{self.horizon}"


def forward_returns(bars: pl.LazyFrame, horizons: Sequence[int], tick_units: int) -> pl.LazyFrame:
    """`bars`, signal bars in time order with `contract`, `trade_date`, `open`, and
    `zero_volume`, with each bar's entry, `next_open`, and a label column for each horizon, in
    ticks of `tick_units` 1e-9 units of price."""
    if tick_units < 1:
        raise ValueError(f"Expected a tick of at least one 1e-9 unit of price, got {tick_units}.")
    labels = [Label(horizon) for horizon in horizons]
    entered = bars.with_columns(
        _tradable("open").shift(-1).backward_fill().over(SESSION).alias(NEXT_OPEN)
    )
    return entered.with_columns(
        ((exit_open(label.horizon) - pl.col(NEXT_OPEN)) / tick_units).alias(label.column)
        for label in labels
    )


def exit_open(horizon: int) -> pl.Expr:
    """Where a position entered at a bar's `next_open` and held `horizon` bars leaves: the
    `next_open` of the bar `horizon` bars on in the session, null where none is left."""
    return pl.col(NEXT_OPEN).shift(-horizon).over(SESSION)


def excursions(labelled: pl.LazyFrame, horizon: int, tick_units: int) -> pl.LazyFrame:
    """`labelled`, the frame `forward_returns` gives, with how far the price went for and against
    a long held `horizon` bars from each bar's entry, in ticks: `mfe_ticks`, the highest high
    traded while it was held, or its exit where that lies higher, less its entry, and
    `mae_ticks`, its entry less the lowest low or exit. The bars between the entry decision and
    the exit decision are those held; an empty bucket's high and low repeat the close before it,
    which no trade made, so they count for nothing; both are null where the label is."""
    exit_price = exit_open(horizon)
    highest = _tradable("high").rolling_max(horizon, min_samples=1).shift(-horizon).over(SESSION)
    lowest = _tradable("low").rolling_min(horizon, min_samples=1).shift(-horizon).over(SESSION)
    held = exit_price.is_not_null()
    return labelled.with_columns(
        mfe_ticks=pl.when(held).then(
            (pl.max_horizontal(highest, exit_price) - pl.col(NEXT_OPEN)) / tick_units
        ),
        mae_ticks=pl.when(held).then(
            (pl.col(NEXT_OPEN) - pl.min_horizontal(lowest, exit_price)) / tick_units
        ),
    )


def _tradable(price: str) -> pl.Expr:
    """The bar's `price` where its bucket traded, else null."""
    return pl.when(~pl.col("zero_volume")).then(pl.col(price))
