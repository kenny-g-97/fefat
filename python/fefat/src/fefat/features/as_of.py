"""The joins that give a feature its inputs (`fefat.features.runtime`, step 3.2): each input as of
each row's close, backward on `ts_close`, so a row sees a bar from its close on and never while
it is in progress, and nothing before an input's first bar (D-12)."""

from collections.abc import Sequence

import polars as pl


def with_feature(frame: pl.DataFrame, read: pl.DataFrame, reader: str) -> pl.DataFrame:
    """`frame` with the outputs of a feature that the feature `reader` reads, as of each row's
    close: on its own grid the row's, on a coarser grid the last bar closed by then."""
    _require_apart(frame, [column for column in read.columns if column != "ts_close"], reader)
    return frame.join_asof(read, on="ts_close", strategy="backward")


def with_instrument(
    frame: pl.DataFrame, other: pl.DataFrame, root: str, reader: str
) -> pl.DataFrame:
    """`frame` with the columns of another instrument's bars that the feature `reader` reads,
    each suffixed with its `root`, as of each row's close, and `staleness_<root>`, the
    nanoseconds from that bar's close to the row's; null before its first bar."""
    suffixed = other.select(pl.all().name.suffix(f"_{root}"))
    closed, staleness = f"ts_close_{root}", f"staleness_{root}"
    _require_apart(frame, [*suffixed.columns, staleness], reader)
    joined = frame.join_asof(suffixed, left_on="ts_close", right_on=closed, strategy="backward")
    return joined.with_columns((pl.col("ts_close") - pl.col(closed)).alias(staleness))


def _require_apart(frame: pl.DataFrame, columns: Sequence[str], reader: str) -> None:
    """Refuse an input whose columns the frame already holds, which a join would rename."""
    taken = sorted(set(columns) & set(frame.columns))
    if taken:
        raise ValueError(
            f"Expected the inputs of feature {reader} to give columns apart from each other's "
            f"and its bars', got {', '.join(taken)} twice."
        )
