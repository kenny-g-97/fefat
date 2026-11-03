"""The joins that give a feature its inputs (`fefat.features.runtime`, step 3.2): each input as of
each row's close, backward on `ts_close`, so a row sees a bar from its close on and never while
it is in progress, and nothing before an input's first bar (D-12); another instrument's bars
held, as the reader's own are, to one series of raw prices (D-09, D-49)."""

from collections.abc import Sequence

import polars as pl

from fefat.features.evaluation import require_one_series_of_raw_prices


def with_feature(frame: pl.DataFrame, values: pl.DataFrame, reader: str) -> pl.DataFrame:
    """`frame` with the `values` of a feature that the feature `reader` reads, its `ts_close` and
    outputs, as of each row's close: on its own grid the row's, on a coarser grid the last bar
    closed by then."""
    _require_apart(frame, [column for column in values.columns if column != "ts_close"], reader)
    return frame.join_asof(values, on="ts_close", strategy="backward")


def with_instrument(
    frame: pl.DataFrame, other: pl.DataFrame, root: str, reader: str
) -> pl.DataFrame:
    """`frame` with the columns of another instrument's bars that the feature `reader` reads,
    each suffixed with its `root`, as of each row's close, and `staleness_<root>`, the
    nanoseconds from that bar's close to the row's; null before its first bar. Bars that are not
    one series of raw prices are refused: a back-adjusted import's hold the gaps of later rolls."""
    require_one_series_of_raw_prices(other.lazy(), f"{root} that feature {reader} reads")
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
