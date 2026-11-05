"""Rank correlations (step 3.8, `02-engine-and-data.md` §6): a feature's daily rank information
coefficient with the forward returns, and the features' rank correlations with each other.

A trade date's information coefficient is its share of the rank correlation of the feature with
the forward returns at a horizon: the mean, over its bars, of the product of the bar's two ranks,
each ranked among all the bars studied and standardised. Its mean over the trade dates is close
to Spearman's correlation over all the bars and says how well the feature sorts the returns after
it; its t-statistic, the mean over its standard error, says whether to believe it, each day one
piece of evidence, since the returns of a day's bars overlap and move together; and its fall from
the shorter horizons to the longer, the decay, says how long what the feature foretells lasts.
Ranking within each day instead would compare a bar with its own day's alone, which pushes a
persistent feature, such as the RSI or where the close lies in its range, towards a negative
coefficient even on a random walk, a bias of short samples that grows with the horizon.

The correlations of features with each other are rank correlations over the bars where both have
a value. Features that correlate at 0.7 or more either way share a cluster: single linkage cut at
a distance, one less the correlation's size, of 0.3, which joins two features whenever a chain of
such pairs links them. Features of one cluster say much the same, so a strategy rarely needs more
than one of them.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import polars as pl

from fefat.analytics.labels import Label
from fefat.analytics.trials import Trials
from fefat.market.calendar import counted

IC_COLUMNS = pl.Schema(
    {"horizon": pl.Int64, "days": pl.UInt32, "mean_ic": pl.Float64, "t_statistic": pl.Float64}
)
"""A row per horizon: the trade dates with a coefficient, their mean, and its t-statistic."""
IC_BY_YEAR_COLUMNS = pl.Schema({"year": pl.Int32, **IC_COLUMNS})
"""The same, a row per calendar year of the trade dates and horizon."""
CLUSTER_COLUMNS = pl.Schema({"feature": pl.String, "cluster": pl.Int64})
"""A row per feature: its cluster, numbered from 1, the largest first."""
REDUNDANT = 0.7
"""The size of a rank correlation from which two features share a cluster."""


@dataclass(frozen=True)
class InformationCoefficient:
    """The daily rank information coefficient of `feature`: `by_horizon` with the columns of
    `IC_COLUMNS`, the decay from one horizon to the next, `by_year` with those of
    `IC_BY_YEAR_COLUMNS`, and the trials the study had examined."""

    feature: str
    by_horizon: pl.DataFrame
    by_year: pl.DataFrame
    trials: Trials

    def report(self) -> str:
        """The coefficients as text, by horizon and by year, and the trials line."""
        return "\n".join(
            [
                f"Daily rank information coefficient of {self.feature}: each trade date's share "
                "of its rank correlation with the forward returns, ranked among all the bars "
                "studied, the mean over the dates, and the t-statistic of that mean",
                *(f"  {_coefficient_line(row)}" for row in self.by_horizon.iter_rows(named=True)),
                "  By year",
                *(
                    f"    {row['year']}  {_coefficient_line(row)}"
                    for row in self.by_year.iter_rows(named=True)
                ),
                self.trials.line(),
            ]
        )


@dataclass(frozen=True)
class Correlations:
    """The rank correlations of features with each other: `matrix`, a row per feature with its
    name in `feature` and a column per feature, both in the clusters' order, and `clusters`
    with the columns of `CLUSTER_COLUMNS`, and the trials the study had examined, which a
    correlation of features adds nothing to."""

    matrix: pl.DataFrame
    clusters: pl.DataFrame
    trials: Trials

    def report(self) -> str:
        """The clusters and the matrix as text, and the trials line."""
        features = self.clusters.get_column("feature").to_list()
        width = max(8, *(len(feature) + 2 for feature in features))
        groups = self.clusters.group_by("cluster", maintain_order=True).agg("feature")
        return "\n".join(
            [
                f"Rank correlations of {counted(len(features), 'feature')} over the bars where "
                f"both have values, clustered where they correlate at {REDUNDANT} or more "
                "either way",
                *(
                    f"  cluster {number}: {', '.join(members)}"
                    for number, members in groups.iter_rows()
                ),
                "  " + " " * width + "".join(f"{feature:>{width}}" for feature in features),
                *(
                    f"  {row[0]:<{width}}"
                    + "".join(f"{_signed(value):>{width}}" for value in row[1:])
                    for row in self.matrix.iter_rows()
                ),
                self.trials.line(),
            ]
        )


def information_coefficient_of(
    labelled: pl.DataFrame, feature: str, labels: Sequence[Label], trials: Trials
) -> InformationCoefficient:
    """The daily rank information coefficient of `feature` in `labelled`, the study's frame, at
    each of `labels`."""
    daily = (
        pl.concat(_daily_coefficients(labelled, feature, label) for label in labels)
        .filter(pl.col("ic").is_finite())
        .with_columns(year=pl.col("trade_date").dt.year())
    )
    return InformationCoefficient(
        feature,
        _summary(daily, ["horizon"]).cast(IC_COLUMNS),
        _summary(daily, ["year", "horizon"]).cast(IC_BY_YEAR_COLUMNS),
        trials,
    )


def correlations_of(frame: pl.DataFrame, features: Sequence[str], trials: Trials) -> Correlations:
    """The rank correlations of `features` in `frame` with each other, and their clusters."""
    pairs = list(combinations(features, 2))
    values = frame.select(
        pl.corr(left, right, method="spearman").alias(str(number))
        for number, (left, right) in enumerate(pairs)
    ).row(0)
    rho: dict[tuple[str, str], float | None] = {}
    for (left, right), value in zip(pairs, values, strict=True):
        rho[left, right] = rho[right, left] = _finite(value)
    linked = [
        pair for pair in pairs if (value := rho[pair]) is not None and abs(value) >= REDUNDANT
    ]
    cluster_of = _clusters(features, linked)
    order = sorted(features, key=lambda feature: (cluster_of[feature], feature))
    matrix = pl.DataFrame(
        {
            "feature": order,
            **{
                column: [1.0 if row == column else rho[row, column] for row in order]
                for column in order
            },
        },
        schema={"feature": pl.String, **dict.fromkeys(order, pl.Float64)},
    )
    clusters = pl.DataFrame(
        {"feature": order, "cluster": [cluster_of[feature] for feature in order]},
        schema=CLUSTER_COLUMNS,
    )
    return Correlations(matrix, clusters, trials)


def _daily_coefficients(labelled: pl.DataFrame, feature: str, label: Label) -> pl.DataFrame:
    """Each trade date's coefficient at `label`'s horizon: the mean product of its bars'
    standardised ranks of `feature` and of the label, ranked among all the bars with both."""
    paired = labelled.filter(pl.col(feature).is_not_null() & pl.col(label.column).is_not_null())
    return (
        paired.with_columns(score=_standard_rank(feature) * _standard_rank(label.column))
        .group_by("trade_date")
        .agg(ic=pl.col("score").mean())
        .with_columns(horizon=pl.lit(label.horizon, dtype=pl.Int64))
    )


def _standard_rank(column: str) -> pl.Expr:
    """The rank of each value of `column` among all its values, less their mean, over their
    standard deviation."""
    rank = pl.col(column).rank("average")
    return (rank - rank.mean()) / rank.std(ddof=0)


def _summary(daily: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """The days, the mean coefficient, and its t-statistic of each group of `keys`."""
    coefficient = pl.col("ic")
    return (
        daily.group_by(keys)
        .agg(
            days=pl.len(),
            mean_ic=coefficient.mean(),
            t_statistic=coefficient.mean() / coefficient.std() * pl.len().sqrt(),
        )
        .sort(keys)
    )


def _clusters(features: Sequence[str], linked: Iterable[tuple[str, str]]) -> dict[str, int]:
    """The cluster of each feature: the groups the linked pairs join, directly or through
    others, numbered from 1, the largest first, then by their first feature's name."""
    leader = {feature: feature for feature in features}

    def root(feature: str) -> str:
        while leader[feature] != feature:
            feature = leader[feature]
        return feature

    for left, right in linked:
        leader[root(left)] = root(right)
    members: dict[str, list[str]] = {}
    for feature in features:
        members.setdefault(root(feature), []).append(feature)
    groups = sorted((sorted(group) for group in members.values()), key=lambda g: (-len(g), g[0]))
    return {feature: number for number, group in enumerate(groups, start=1) for feature in group}


def _coefficient_line(row: Mapping[str, Any]) -> str:
    return (
        f"{counted(row['horizon'], 'bar'):>8} ahead  {counted(row['days'], 'trade date'):>16}  "
        f"mean {row['mean_ic']:+.3f}  t {_signed(row['t_statistic'])}"
    )


def _finite(value: float | None) -> float | None:
    """A correlation, or None where it has none, as for a feature that never moves."""
    return None if value is None or math.isnan(value) else value


def _signed(value: float | None) -> str:
    return "none" if value is None else f"{value:+.2f}"
