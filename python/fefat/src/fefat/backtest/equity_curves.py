"""A run's equity curve for a chart (step 5.7, D-116): the account after each decision that values
it, with how far each lies below the highest equity before it, the capital first, as the run's
metrics measure the maximum drawdown (`02` §7, D-63). A long curve is downsampled: its decisions
are cut into buckets of consecutive rows, and each bucket keeps those of its lowest equity, its
highest equity, and its deepest drawdown, the first of equals, beside the run's first and last
decision. The lowest and the highest alone would lose the maximum drawdown where one bucket holds
its peak and its trough with a lower value before the peak.

    curve = ff.backtest.equity_curve(run, max_points=2000)
"""

import polars as pl

from fefat.backtest.artifacts import read_artifact
from fefat.backtest.runs import Run
from fefat.market.engine_units import micro_units

EQUITY_POINTS = 3000
"""The points of a curve a chart gets unless it asks for others: about a bucket a pixel."""
FEWEST_POINTS = 5
"""The fewest points a curve can be asked for: a bucket's three, its first, and its last."""
_KEPT_A_BUCKET = 3


def equity_curve(run: Run, max_points: int = EQUITY_POINTS) -> pl.DataFrame:
    """The account of `run` after each decision, whatever its timeframe, in at most `max_points`
    rows (module docstring): `ts`, `equity`, and `drawdown`, in the artifacts' units."""
    decisions = read_artifact(run.folder, "equity")
    return downsampled_equity(decisions, micro_units(run.config.capital), max_points)


def downsampled_equity(equity: pl.DataFrame, capital: int, max_points: int) -> pl.DataFrame:
    """`equity`, a run's `ts` and `equity` after each decision in micro-units, without the
    decisions that value no account, as the metrics leave them out, with each row's `drawdown`
    below its peak, `capital` first, in micro-units: every row up to `max_points`, else the rows
    the module docstring keeps. Refused under `FEWEST_POINTS`."""
    if max_points < FEWEST_POINTS:
        raise ValueError(
            f"Expected at least {FEWEST_POINTS} points of the curve, got {max_points}."
        )
    valued = equity.filter(pl.col("equity").is_not_null()).select("ts", "equity")
    peak = pl.max_horizontal(pl.lit(capital, dtype=pl.Int64), pl.col("equity").cum_max())
    curve = valued.with_columns(drawdown=peak - pl.col("equity"))
    if curve.height <= max_points:
        return curve
    buckets = (max_points - 2) // _KEPT_A_BUCKET
    numbered = curve.with_row_index("row").with_columns(
        bucket=pl.col("row").cast(pl.Int64) * buckets // curve.height
    )
    row = pl.col("row")
    extreme = (
        (row == row.get(pl.col("equity").arg_min()).over("bucket"))
        | (row == row.get(pl.col("equity").arg_max()).over("bucket"))
        | (row == row.get(pl.col("drawdown").arg_max()).over("bucket"))
    )
    return numbered.filter(extreme | (row == 0) | (row == curve.height - 1)).select(curve.columns)
