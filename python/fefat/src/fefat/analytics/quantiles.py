"""The mean forward return by quantile of a feature (step 3.8, `02-engine-and-data.md` §6), each
with its interval from a day-block bootstrap.

The bars are put into `quantiles` buckets by the rank of their value of the feature among all the
values studied, ties in the lowest's bucket: a rank over the whole sample, which a feature must
never take (D-12), is how analytics sort a feature's values once they are known, and nothing
here feeds a strategy. A bucket's mean is that of its labels at each horizon. Its interval comes
from drawing whole trade dates with replacement, `resamples` times from a seed, so that the bars
of one day, whose returns overlap and move together, stay together: the 2.5 % and 97.5 %
quantiles of the means of the draws bound its 95 % interval. A bucket whose bars fall on so few
trade dates that some draws hold none of them has no interval. Each interval is 95 % on its own,
so among the fifteen of five quantiles at three horizons one that leaves 0 by chance alone is
more likely than not: read the pattern across the quantiles, not one interval.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from fefat.analytics.labels import Label
from fefat.analytics.trials import Trials
from fefat.market.calendar import counted

QUANTILE_COLUMNS = pl.Schema(
    {
        "horizon": pl.Int64,
        "quantile": pl.Int64,
        "bars": pl.UInt32,
        "feature_low": pl.Float64,
        "feature_high": pl.Float64,
        "mean_ticks": pl.Float64,
        "interval_low_ticks": pl.Float64,
        "interval_high_ticks": pl.Float64,
    }
)
"""A row per horizon and quantile: the bars with a label, the feature's range in the bucket, and
the mean forward return in ticks with its 95 % interval."""
INTERVAL = (0.025, 0.975)
"""The quantiles of the resampled means that bound a 95 % interval."""


@dataclass(frozen=True)
class QuantileReturns:
    """The mean forward return of each quantile of `feature` at each horizon, `frame` with the
    columns of `QUANTILE_COLUMNS`, from `resamples` day-block draws, and the trials the study had
    examined."""

    feature: str
    quantiles: int
    resamples: int
    frame: pl.DataFrame
    trials: Trials

    def report(self) -> str:
        """The table as text, a block per horizon, and the trials line."""
        lines = [
            f"Forward returns by quantile of {self.feature}, in ticks: each quantile's mean and "
            f"its 95 % interval from {self.resamples:,} day-block resamples, each interval on "
            "its own, none where some draws hold none of the quantile's trade dates"
        ]
        for (horizon,), rows in self.frame.group_by("horizon", maintain_order=True):
            lines.append(f"  {counted(int(horizon), 'bar')} ahead")
            lines.extend(_quantile_line(row) for row in rows.iter_rows(named=True))
        return "\n".join([*lines, self.trials.line()])


def quantile_returns_of(
    labelled: pl.DataFrame,
    feature: str,
    labels: Sequence[Label],
    quantiles: int,
    bootstrap: tuple[int, int],
    trials: Trials,
) -> QuantileReturns:
    """The quantile returns of `feature` in `labelled`, the study's frame, at each of `labels`,
    with intervals from `bootstrap`, its number of resamples and its seed."""
    bucketed = labelled.filter(pl.col(feature).is_not_null()).select(
        "trade_date",
        *(label.column for label in labels),
        value=pl.col(feature),
        quantile=_bucket(feature, quantiles),
    )
    ranges = bucketed.group_by("quantile").agg(
        feature_low=pl.col("value").min(), feature_high=pl.col("value").max()
    )
    by_day = _returns_by_day(bucketed, labels)
    means = by_day.group_by("horizon", "quantile").agg(
        bars=pl.col("bars").sum(), mean_ticks=pl.col("ticks").sum() / pl.col("bars").sum()
    )
    frame = (
        means.join(ranges, on="quantile")
        .join(_day_block_intervals(by_day, *bootstrap), on=["horizon", "quantile"], how="left")
        .sort("horizon", "quantile")
        .select(QUANTILE_COLUMNS.names())
        .cast(QUANTILE_COLUMNS)
    )
    return QuantileReturns(feature, quantiles, bootstrap[0], frame, trials)


def _bucket(feature: str, quantiles: int) -> pl.Expr:
    """The quantile of each bar's value of `feature` among the values, from 1 for the lowest."""
    rank = pl.col(feature).rank("min").cast(pl.Int64)
    return (rank - 1) * quantiles // pl.len() + 1


def _returns_by_day(bucketed: pl.DataFrame, labels: Sequence[Label]) -> pl.DataFrame:
    """The sum and the count of each trade date's labels in each quantile at each horizon."""
    per_label = [
        bucketed.select(
            "trade_date",
            "quantile",
            horizon=pl.lit(label.horizon, dtype=pl.Int64),
            ticks=pl.col(label.column),
        )
        for label in labels
    ]
    return (
        pl.concat(per_label)
        .drop_nulls("ticks")
        .group_by("trade_date", "horizon", "quantile")
        .agg(ticks=pl.col("ticks").sum(), bars=pl.len())
    )


def _day_block_intervals(by_day: pl.DataFrame, resamples: int, seed: int) -> pl.DataFrame:
    """The 95 % interval of each quantile's mean at each horizon from `resamples` draws of the
    trade dates with replacement, each as many dates as the study holds, drawn from `seed`, and
    none where some draws hold none of the quantile's dates."""
    # shortcut: every draw joins its day's sums at once, some 600 MB at ten years of trade dates
    # and 1,000 resamples; draw in chunks of resamples once studies span decades or share a job.
    days = by_day.select(pl.col("trade_date").unique().sort()).with_row_index("day")
    count = days.height
    draws = pl.select(
        resample=pl.int_range(resamples * count) // count,
        day=pl.int_range(count, dtype=pl.UInt32).sample(
            resamples * count, with_replacement=True, seed=seed
        ),
    )
    drawn = draws.join(by_day.join(days, on="trade_date").drop("trade_date"), on="day")
    means = drawn.group_by("resample", "horizon", "quantile").agg(
        mean=pl.col("ticks").sum() / pl.col("bars").sum()
    )
    low, high = INTERVAL
    every_draw = pl.len() == resamples
    return means.group_by("horizon", "quantile").agg(
        interval_low_ticks=pl.when(every_draw).then(pl.col("mean").quantile(low, "linear")),
        interval_high_ticks=pl.when(every_draw).then(pl.col("mean").quantile(high, "linear")),
    )


def _quantile_line(row: Mapping[str, Any]) -> str:
    return (
        f"    quantile {row['quantile']}  {row['feature_low']:>9.4g} to "
        f"{row['feature_high']:<9.4g} {counted(row['bars'], 'bar'):>12}  "
        f"mean {_ticks(row['mean_ticks'])}  interval {_ticks(row['interval_low_ticks'])} to "
        f"{_ticks(row['interval_high_ticks'])}"
    )


def _ticks(value: object) -> str:
    return "none" if value is None else f"{value:+.2f}"
