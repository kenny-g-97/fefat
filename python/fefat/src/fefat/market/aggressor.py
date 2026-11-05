"""The prints of each bucket by their aggressor side (step 3.6, `02-engine-and-data.md` §6, D-78):
the volume bought, `B`, sold, `A`, and of no known side, `N`, in each bucket of the session grid,
which a feature's trades input reads (`TradesInput`, `fefat.features.runtime`).

A bucket holds the prints received in it, as a bar does (D-43): each print takes the trade date
of the session that opened last before its `ts_recv`, a print received after a close lies in a
bucket of the break, which the grid leaves out, and a bucket closing after the instant by which
every print is in hand is held back, as one closing before the bucket of the first print in hand
is, where the bars of the data's first session have no row either. So a bucket's volumes are
available at its close, as its bar is, and cutting them at an instant keeps what cutting the
prints at their `ts_recv` and building the buckets again keeps: the buckets closed by it. Every
other bucket of a trade date whose prints are held is a row, its volumes 0 where none was
received; a trade date without prints has no rows, which the trades input reads as null, no
volume known.

    volumes = side_volumes(prints, FIVE, sessions, [date(2026, 3, 6)], (first, until))
"""

from collections.abc import Sequence
from datetime import date

import polars as pl

from fefat.market.bars import grid_buckets, in_buckets
from fefat.market.calendar import SessionTable
from fefat.market.schema import AggressorSide, Timeframe

VOLUME_COLUMNS = ("buy_volume", "sell_volume", "unknown_side_volume")
"""The volumes of a bucket's prints by aggressor side, in contracts or units of the instrument."""
SIDE_VOLUME_COLUMNS = pl.Schema(
    {
        "trade_date": pl.Date,
        "ts_open": pl.Int64,
        "ts_close": pl.Int64,
        **dict.fromkeys(VOLUME_COLUMNS, pl.Int64),
    }
)
"""A bucket of the session grid and the volumes of its prints by side, signed integers so that a
feature subtracts them without wrapping."""
PRINT_COLUMNS = ("ts_recv", "size", "side")
"""The columns of the store's trades that give a bucket's volumes."""


def side_volumes(
    prints: pl.DataFrame,
    timeframe: Timeframe,
    sessions: SessionTable,
    held: Sequence[date],
    in_hand: tuple[int, int],
) -> pl.DataFrame:
    """The buckets of `timeframe` of the trade dates `held`, whose prints `prints` holds with the
    columns of `PRINT_COLUMNS`, with the columns of `SIDE_VOLUME_COLUMNS`, sorted by close: every
    bucket of the session grid closing after the first instant of `in_hand` and by its second,
    the instants of the first print in hand and by which every print is, with the volume of the
    prints received in it by side (module docstring)."""
    if not held:
        return pl.DataFrame(schema=SIDE_VOLUME_COLUMNS)
    received_from, received_until = in_hand
    closes = pl.col("ts_close")
    buckets = grid_buckets(sessions.between(min(held), max(held)), timeframe).filter(
        pl.col("trade_date").is_in(list(held)), closes > received_from, closes <= received_until
    )
    volumes = _bucket_volumes(prints, timeframe, sessions)
    return (
        buckets.join(volumes, on=["trade_date", "ts_open"], how="left")
        .with_columns(pl.col(VOLUME_COLUMNS).fill_null(0))
        .sort("ts_close")
        .select(SIDE_VOLUME_COLUMNS.names())
    )


def _bucket_volumes(
    prints: pl.DataFrame, timeframe: Timeframe, sessions: SessionTable
) -> pl.DataFrame:
    """`trade_date`, `ts_open`, and the volumes by side of the buckets `prints` fall in, those of
    the break included; none without prints, which `in_buckets` cannot date."""
    if prints.is_empty():
        return pl.DataFrame(schema=SIDE_VOLUME_COLUMNS).drop("ts_close")
    dated = sessions.assign_trade_dates_or_previous(prints.select(PRINT_COLUMNS), "ts_recv")
    bucketed = in_buckets(dated.rename({"ts_recv": "ts_open"}), timeframe, sessions)
    size, side = pl.col("size").cast(pl.Int64), pl.col("side")
    bought = size.filter(side == AggressorSide.BUY).sum()
    sold = size.filter(side == AggressorSide.SELL).sum()
    return bucketed.group_by("trade_date", ts_open="bucket_open").agg(
        buy_volume=bought, sell_volume=sold, unknown_side_volume=size.sum() - bought - sold
    )
