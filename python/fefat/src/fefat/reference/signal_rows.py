"""The signal rows of a template scenario (step 2.3, D-53): each a row of a signal frame at one
signal close, written as a scenario writes a tape, its prices in quotes and raw prices of its
contract, so that its `adj_offset` is 0 (`fixtures/scenarios/README.md`)."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated

import polars as pl
from pydantic import Field

from fefat.market.schema import FrozenModel
from fefat.reference.units import Instant, Price
from fefat.strategy.signal_frame import OPTIONAL_SIGNAL_COLUMNS, REQUIRED_SIGNAL_COLUMNS

_ROW_COLUMNS = pl.Schema(
    {name: dtype for name, dtype in REQUIRED_SIGNAL_COLUMNS.items() if name != "adj_offset"}
    | dict(OPTIONAL_SIGNAL_COLUMNS)
)


class SignalRow(FrozenModel):
    """One signal close of a template scenario: when, on which trade date and contract, its four
    signals, false where left out, and the optional columns, `wake` true where left out."""

    ts_close: Instant
    trade_date: date
    contract: Annotated[str, Field(min_length=1)]
    long_entry: bool = False
    short_entry: bool = False
    long_exit: bool = False
    short_exit: bool = False
    entry_price: Price | None = None
    stop_price: Price | None = None
    target_price: Price | None = None
    trail_ref: Price | None = None
    size_mult: float | None = None
    wake: bool = True

    def prices(self) -> tuple[int, ...]:
        """The prices the row names."""
        given = (self.entry_price, self.stop_price, self.target_price, self.trail_ref)
        return tuple(price for price in given if price is not None)


def signal_frame(rows: Sequence[SignalRow]) -> pl.DataFrame:
    """The signal frame of `rows` (`fefat.strategy.signal_frame`): its required columns with an
    `adj_offset` of 0, then each optional column that a row sets, `wake` where a row is false."""
    frame = pl.DataFrame([row.model_dump() for row in rows], schema=_ROW_COLUMNS)
    given = [
        name
        for name in OPTIONAL_SIGNAL_COLUMNS
        if (name == "wake" and not frame.get_column(name).all())
        or (name != "wake" and frame.get_column(name).is_not_null().any())
    ]
    with_offset = frame.with_columns(adj_offset=pl.lit(0, dtype=pl.Int64))
    return with_offset.select(*REQUIRED_SIGNAL_COLUMNS, *given)
