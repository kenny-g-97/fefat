"""The signal frame (`02-engine-and-data.md` §2.1, D-53): the table a signal strategy gives the
engine beside its specification, one row per close of its signal bars. It carries `ts_close`,
`trade_date`, `contract`, and `adj_offset` from the bars, the strategy's features, its four
signals, and the optional columns the execution template reads. Its prices are int64 raw prices
of each row's contract in 1e-9 units, so that the engine never sees an adjusted price (D-09)."""

from collections.abc import Mapping

import polars as pl

from fefat.market.calendar import counted, utc_text

REQUIRED_SIGNAL_COLUMNS = pl.Schema(
    {
        "ts_close": pl.Int64,
        "trade_date": pl.Date,
        "contract": pl.String,
        "adj_offset": pl.Int64,
        "long_entry": pl.Boolean,
        "short_entry": pl.Boolean,
        "long_exit": pl.Boolean,
        "short_exit": pl.Boolean,
    }
)
"""The columns of every signal frame: those it carries from its bars, then its four signals."""

OPTIONAL_SIGNAL_COLUMNS = pl.Schema(
    {
        "entry_price": pl.Int64,
        "stop_price": pl.Int64,
        "target_price": pl.Int64,
        "trail_ref": pl.Int64,
        "size_mult": pl.Float64,
        "wake": pl.Boolean,
    }
)
"""The columns a signal frame holds where its strategy gives them: the prices its execution
template may read, a factor of each entry's size, and `wake`, false on a bar on which no entry is
placed, so that an engine may pass it over while flat; exits and time rules still act there."""

PRICE_COLUMNS = ("entry_price", "stop_price", "target_price", "trail_ref")
"""The signal frame's price columns, raw prices of each row's contract in 1e-9 units."""


def validated_signal_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """`frame` once it holds the signal frame's columns with their types, no null in its required
    columns or in `wake`, no NaN in any column of floats (Polars reads NaN as larger than any
    number), and its closes strictly increasing, one row per signal bar of one series; its other
    columns are the strategy's features."""
    present = {name: dtype for name, dtype in OPTIONAL_SIGNAL_COLUMNS.items() if name in frame}
    require_column_types(frame, {**REQUIRED_SIGNAL_COLUMNS, **present}, "the signal frame's")
    _require_no_nulls(frame, [*REQUIRED_SIGNAL_COLUMNS, *(["wake"] if "wake" in frame else [])])
    _require_no_nan(frame)
    _require_increasing_closes(frame)
    return frame


def require_column_types(
    frame: pl.DataFrame, columns: Mapping[str, pl.DataType], owner: str
) -> None:
    """Refuse a frame without one of `columns` or holding it with another type; `owner` names
    whose columns they are, such as "the signal frame's"."""
    for name, dtype in columns.items():
        actual = frame.schema.get(name)
        if actual != dtype:
            got = "none" if actual is None else actual
            raise ValueError(f"Expected {owner} {name} as {dtype}, got {got}.")


def require_one_entry_per_bar(frame: pl.DataFrame) -> None:
    """Refuse a bar with both entry signals, which a market entry cannot place (D-53)."""
    both = frame.filter(pl.col("long_entry") & pl.col("short_entry"))
    if both.is_empty():
        return
    raise ValueError(
        "Expected one of long_entry and short_entry per bar with a market entry, got both on "
        f"{counted(both.height, 'bar')}{_first_close(both)}."
    )


def _require_no_nulls(frame: pl.DataFrame, columns: list[str]) -> None:
    for name in columns:
        nulls = frame.filter(pl.col(name).is_null())
        if not nulls.is_empty():
            raise ValueError(
                f"Expected no null in the signal frame's {name}, got "
                f"{counted(nulls.height, 'row')}{_first_close(nulls)}."
            )


def _require_no_nan(frame: pl.DataFrame) -> None:
    for name, dtype in frame.schema.items():
        if not dtype.is_float():
            continue
        nans = frame.filter(pl.col(name).is_nan())
        if not nans.is_empty():
            raise ValueError(
                f"Expected no NaN in the signal frame's {name}, got "
                f"{counted(nans.height, 'row')}{_first_close(nans)}: Polars reads NaN as larger "
                "than any number, so a signal read from it is wrong; make it null with "
                "`fill_nan(None)`."
            )


def _require_increasing_closes(frame: pl.DataFrame) -> None:
    steps = frame.select(close=pl.col("ts_close"), before=pl.col("ts_close").shift(1))
    back = steps.filter(pl.col("close") <= pl.col("before"))
    if back.is_empty():
        return
    close, before = utc_text(back.item(0, "close")), utc_text(back.item(0, "before"))
    raise ValueError(
        "Expected the signal frame's ts_close strictly increasing, one row per signal bar of one "
        f"series, got {close} after {before}."
    )


def _first_close(rows: pl.DataFrame) -> str:
    """ ", the first closing at <instant>" for rows whose first close is known."""
    first = rows.item(0, "ts_close")
    return "" if first is None else f", the first closing at {utc_text(first)}"
