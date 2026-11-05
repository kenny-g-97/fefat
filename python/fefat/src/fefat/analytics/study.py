"""The feature study (step 3.8, `02-engine-and-data.md` §6): the frame of signal bars with the
features to judge, as `ff.features.compute` gives it, its forward returns at the horizons asked
for, and the four analyses, each a result of Polars frames with a text report that ends with the
trials counter: how many features and horizons the study has examined so far.

    frame = ff.features.compute({"stretch": rsi_stretch(), "rsi": rsi(14)}, "MES", "5m", start, end)
    frame = frame.with_columns(oversold=pl.col("rsi") < 30)
    study = ff.analytics.FeatureStudy(frame, "MES", horizons=(1, 5, 20))
    print(study.quantile_returns("stretch").report())
    print(study.information_coefficient("stretch").report())
    print(study.correlations(["stretch", "rsi"]).report())
    print(study.event_study("oversold", ff.analytics.PositionSide.LONG).report())
    print(study.trials.line())

A study counts what it examined for as long as it lives, as a notebook's session does: start a
new one and the count starts again, so keep one study for one line of research.
"""

from collections.abc import Iterable, Sequence

import polars as pl

from fefat.analytics.events import EventStudy, event_study_of
from fefat.analytics.labels import Label, forward_returns
from fefat.analytics.quantiles import QuantileReturns, quantile_returns_of
from fefat.analytics.rank_correlation import (
    Correlations,
    InformationCoefficient,
    correlations_of,
    information_coefficient_of,
)
from fefat.analytics.trials import Trials
from fefat.features.evaluation import require_one_series_of_raw_prices
from fefat.features.label_columns import NEXT_OPEN, reads_ahead
from fefat.indicators.ticks import bars_tick
from fefat.market.calendar import counted
from fefat.reference.orders import PositionSide

BAR_COLUMNS = pl.Schema(
    {
        "ts_close": pl.Int64,
        "trade_date": pl.Date,
        "contract": pl.String,
        "open": pl.Int64,
        "high": pl.Int64,
        "low": pl.Int64,
        "close_raw": pl.Int64,
        "zero_volume": pl.Boolean,
    }
)
"""The columns of the signal bars a study reads, as `ff.market.load` gives them, the raw
closes among them, which a back-adjusted import lacks."""


class FeatureStudy:
    """A study of the features in `frame`, the signal bars of the root `instrument` in time order
    with a column per feature, against their forward returns at `horizons` bars, in ticks of
    the instrument, with intervals from `resamples` day-block draws from `seed`."""

    def __init__(
        self,
        frame: pl.DataFrame | pl.LazyFrame,
        instrument: str,
        horizons: Sequence[int] = (1, 5, 20),
        *,
        resamples: int = 1000,
        seed: int = 0,
    ) -> None:
        bars = frame.lazy().collect()
        _require_signal_bars(bars)
        self._labels = _labels_of(horizons)
        if type(resamples) is not int or resamples < 1:
            raise ValueError(f"Expected a whole number of resamples from 1, got {resamples!r}.")
        self._bootstrap = (resamples, seed)
        self._tick = bars_tick(bars.lazy(), instrument, "the study")
        self._frame = forward_returns(bars.lazy(), self.horizons, self._tick).collect()
        empty = [label for label in self._labels if self._frame[label.column].is_null().all()]
        if empty:
            raise ValueError(
                f"Expected bars with a forward return over {counted(empty[0].horizon, 'bar')} "
                "within their trade date, got none: study bars of which a trade date holds "
                "several, such as 5-minute bars, at horizons shorter than a session."
            )
        self._examined: set[tuple[str, int]] = set()

    @property
    def horizons(self) -> tuple[int, ...]:
        """The horizons of the forward returns, in bars, shortest first."""
        return tuple(label.horizon for label in self._labels)

    @property
    def trials(self) -> Trials:
        """What the study has examined so far."""
        return Trials(frozenset(self._examined))

    def quantile_returns(self, feature: str, quantiles: int = 5) -> QuantileReturns:
        """The mean forward return of each quantile of `feature` at each horizon, with its
        day-block interval (`fefat.analytics.quantiles`)."""
        self._require_values(feature)
        if type(quantiles) is not int or quantiles < 2:
            raise ValueError(f"Expected a whole number of quantiles from 2, got {quantiles!r}.")
        trials = self._examine(feature, self.horizons)
        return quantile_returns_of(
            self._frame, feature, self._labels, quantiles, self._bootstrap, trials
        )

    def information_coefficient(self, feature: str) -> InformationCoefficient:
        """The daily rank information coefficient of `feature` at each horizon and by year
        (`fefat.analytics.rank_correlation`)."""
        self._require_values(feature)
        trials = self._examine(feature, self.horizons)
        return information_coefficient_of(self._frame, feature, self._labels, trials)

    def correlations(self, features: Sequence[str]) -> Correlations:
        """The rank correlations of `features` with each other, clustered; they compare no
        forward return, so the trials stay as they are."""
        if len(features) < 2 or len(set(features)) != len(features):
            raise ValueError(f"Expected two features or more, each once, got {list(features)}.")
        if "feature" in features:
            raise ValueError(
                "Expected features named apart from feature, the matrix's column of their "
                "names, got feature."
            )
        for feature in features:
            self._require_values(feature)
        return correlations_of(self._frame, features, self.trials)

    def event_study(
        self, feature: str, side: PositionSide, horizon: int | None = None
    ) -> EventStudy:
        """The event study of the flag `feature` for `side`, followed `horizon` bars, the
        study's longest horizon where none is given (`fefat.analytics.events`); it examines
        the flag at every number of bars up to `horizon`."""
        dtype = self._column(feature)
        if dtype != pl.Boolean:
            raise ValueError(f"Expected a flag for an event study, got {feature} as {dtype}.")
        followed = Label(max(self.horizons) if horizon is None else horizon).horizon
        trials = self._examine(feature, range(1, followed + 1))
        return event_study_of(
            self._frame, feature, PositionSide(side), followed, self._tick, trials
        )

    def _examine(self, feature: str, horizons: Iterable[int]) -> Trials:
        """The trials once `feature` is examined at `horizons`."""
        self._examined.update((feature, horizon) for horizon in horizons)
        return self.trials

    def _column(self, feature: str) -> pl.DataType:
        """The type of the column `feature`, refused where the frame has none or it reads ahead,
        a label's or the entries'."""
        if feature not in self._frame.columns or reads_ahead(feature):
            raise ValueError(
                f"Expected a feature among the study's columns, its labels and {NEXT_OPEN} "
                f"apart, got {feature}."
            )
        return self._frame.schema[feature]

    def _require_numbers(self, feature: str) -> None:
        """Refuse a feature that is no column of numbers, or holds a NaN."""
        dtype = self._column(feature)
        if not dtype.is_numeric():
            raise ValueError(
                f"Expected the feature {feature} as numbers, got a column of {dtype}: study a "
                "flag with event_study."
            )
        not_numbers = self._frame.get_column(feature).is_nan().sum() if dtype.is_float() else 0
        if not_numbers:
            raise ValueError(
                f"Expected no NaN in the feature {feature}, got {not_numbers}: give null where "
                "it has no value, as features do (D-71)."
            )

    def _require_values(self, feature: str) -> None:
        """Refuse a feature without two values on the bars with a forward return."""
        self._require_numbers(feature)
        valued = pl.col(feature).is_not_null() & pl.col(self._labels[0].column).is_not_null()
        values = self._frame.filter(valued).get_column(feature).n_unique()
        if values < 2:
            raise ValueError(
                f"Expected values of the feature {feature} that differ on the bars with a forward "
                f"return, got {values}: compute it over a window longer than its warm-up."
            )


def _require_signal_bars(bars: pl.DataFrame) -> None:
    """Refuse a frame that is not signal bars of one contract each trade date in time order,
    with raw closes."""
    wrong = [name for name, dtype in BAR_COLUMNS.items() if bars.schema.get(name) != dtype]
    if wrong:
        got = [
            f"{name} as {bars.schema[name]}" if name in bars.schema else f"no {name}"
            for name in wrong
        ]
        raise ValueError(
            f"Expected the signal bars' columns {', '.join(BAR_COLUMNS)}, as "
            f"`ff.features.compute` gives them, got {', '.join(got)}."
        )
    if bars.is_empty():
        raise ValueError("Expected signal bars to study, got an empty frame.")
    crowded = (
        bars.group_by("trade_date")
        .agg(contracts=pl.col("contract").n_unique())
        .filter(pl.col("contracts") > 1)
        .sort("trade_date")
    )
    if not crowded.is_empty():
        raise ValueError(
            "Expected one contract each trade date, a continuous series or one contract's bars, "
            f"got {crowded.item(0, 'contracts')} on {crowded.item(0, 'trade_date')}."
        )
    require_one_series_of_raw_prices(bars.lazy(), "the feature study")


def _labels_of(horizons: Sequence[int]) -> tuple[Label, ...]:
    """The labels of `horizons`, shortest first, refused unless they are distinct."""
    labels = tuple(sorted({Label(horizon) for horizon in horizons}, key=lambda each: each.horizon))
    if not labels or len(labels) != len(horizons):
        raise ValueError(f"Expected one horizon or more, each once, got {list(horizons)}.")
    return labels
