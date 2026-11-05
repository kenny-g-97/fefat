"""Event studies of boolean signals (step 3.8, `02-engine-and-data.md` §6): what the price did after
the bars where a flag turns true, for a long or a short, and how far it went against and for the
position on the way, its maximum adverse and favourable excursions (MAE and MFE).

An event is a bar where the flag turns true: true there and not on the bar before in its trade
date, so that a flag that stays true for several bars is one event, as one entry, and the
events' returns do not count one move again and again; a bar with no trade after it in its
trade date, which no order could enter on, is none. Each event enters at its bar's next
tradable open and is followed for `horizon` bars, as the labels are (`fefat.analytics.labels`):
the path is the mean and median forward return after 1, 2, ... `horizon` bars, and the
excursions those of the events still held after `horizon` bars within their trade date.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import polars as pl

from fefat.analytics.labels import SESSION, excursions, exit_open
from fefat.analytics.trials import Trials
from fefat.features.label_columns import NEXT_OPEN
from fefat.market.calendar import counted
from fefat.reference.orders import PositionSide

EVENT_PATH_COLUMNS = pl.Schema(
    {
        "bars_after": pl.Int64,
        "events": pl.UInt32,
        "mean_ticks": pl.Float64,
        "median_ticks": pl.Float64,
    }
)
"""A row per number of bars after the event: the events with a return there, and its mean and
median in ticks, for the side studied."""
EXCURSION_COLUMNS = pl.Schema(
    {"statistic": pl.String, "mae_ticks": pl.Float64, "mfe_ticks": pl.Float64}
)
"""A row per statistic of the events' excursions, in ticks, each 0 or more."""
EXCURSION_QUANTILES = {"p10": 0.1, "p25": 0.25, "median": 0.5, "p75": 0.75, "p90": 0.9}
"""The quantiles of the excursions given beside their mean."""
EVENT_INPUTS = ("contract", "trade_date", "high", "low", "zero_volume", NEXT_OPEN)
"""The columns of the study's frame an event study reads beside the flag."""


@dataclass(frozen=True)
class EventStudy:
    """The event study of the flag `feature` for `side`: its `events`, the path after them,
    `path` with the columns of `EVENT_PATH_COLUMNS`, the excursions over `horizon` bars,
    `excursions` with those of `EXCURSION_COLUMNS`, and the trials the study had examined."""

    feature: str
    side: PositionSide
    horizon: int
    events: int
    path: pl.DataFrame
    excursions: pl.DataFrame
    trials: Trials

    def report(self) -> str:
        """The path and the excursions as text, and the trials line."""
        held = self.path.filter(pl.col("bars_after") == self.horizon).get_column("events")
        return "\n".join(
            [
                f"Event study of {self.feature} for a {self.side}: "
                f"{counted(self.events, 'event')}, the bars where it turns true, followed "
                f"{counted(self.horizon, 'bar')}",
                "  The forward return after the event, in ticks",
                *(f"    {_path_line(row)}" for row in self.path.iter_rows(named=True)),
                f"  Excursions over the {counted(self.horizon, 'bar')}, in ticks, of the "
                f"{counted(int(held.sum()), 'event')} held that long within their trade date",
                f"    {'statistic':<10}{'adverse':>10}{'favourable':>12}",
                *(
                    f"    {name:<10}{_size(adverse):>10}{_size(favourable):>12}"
                    for name, adverse, favourable in self.excursions.iter_rows()
                ),
                self.trials.line(),
            ]
        )


def onsets(feature: str) -> pl.Expr:
    """True on the bars where the flag `feature` turns true in their session, a null false."""
    flag = pl.col(feature).fill_null(False)
    return flag & ~flag.shift(1, fill_value=False).over(SESSION)


def event_study_of(
    labelled: pl.DataFrame,
    feature: str,
    side: PositionSide,
    horizon: int,
    tick_units: int,
    trials: Trials,
) -> EventStudy:
    """The event study of the flag `feature` in `labelled`, the study's frame, for `side`,
    followed `horizon` bars, in ticks of `tick_units` 1e-9 units of price."""
    sign = 1 if side is PositionSide.LONG else -1
    moves = [
        ((exit_open(after) - pl.col(NEXT_OPEN)) * sign / tick_units).alias(f"after_{after}")
        for after in range(1, horizon + 1)
    ]
    # shortcut: the path shifts every bar's entry once for each bar count up to the horizon,
    # some 800 MB for 60 one-minute bars over five years; gather them at the events alone then.
    flagged = labelled.lazy().select(*EVENT_INPUTS, flag=pl.col(feature))
    entered = onsets("flag") & pl.col(NEXT_OPEN).is_not_null()
    at_events = (
        excursions(flagged, horizon, tick_units)
        .with_columns(*moves, event=entered)
        .filter("event")
        .collect()
    )
    return EventStudy(
        feature,
        side,
        horizon,
        at_events.height,
        _path(at_events, horizon),
        _excursions(at_events, side),
        trials,
    )


def _path(at_events: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """The mean and median return of the events after each number of bars up to `horizon`."""
    per_bar = [
        at_events.select(bars_after=pl.lit(after, dtype=pl.Int64), ticks=pl.col(f"after_{after}"))
        for after in range(1, horizon + 1)
    ]
    return (
        pl.concat(per_bar)
        .drop_nulls("ticks")
        .group_by("bars_after")
        .agg(
            events=pl.len(),
            mean_ticks=pl.col("ticks").mean(),
            median_ticks=pl.col("ticks").median(),
        )
        .sort("bars_after")
        .cast(EVENT_PATH_COLUMNS)
    )


def _excursions(at_events: pl.DataFrame, side: PositionSide) -> pl.DataFrame:
    """The mean and the quantiles of the excursions of the events held the whole horizon: a
    short's adverse excursion is a long's favourable one, and its favourable a long's adverse."""
    adverse, favourable = ("mae_ticks", "mfe_ticks")
    if side is PositionSide.SHORT:
        adverse, favourable = favourable, adverse
    held = at_events.select(mae=pl.col(adverse), mfe=pl.col(favourable)).drop_nulls()
    return pl.DataFrame(
        {
            "statistic": ["mean", *EXCURSION_QUANTILES],
            "mae_ticks": _statistics(held, "mae"),
            "mfe_ticks": _statistics(held, "mfe"),
        },
        schema=EXCURSION_COLUMNS,
    )


def _statistics(held: pl.DataFrame, column: str) -> list[Any]:
    """The mean of `column` and its quantiles of `EXCURSION_QUANTILES`, in that order."""
    values = pl.col(column)
    quantiles = (
        values.quantile(share, "linear").alias(name) for name, share in EXCURSION_QUANTILES.items()
    )
    return list(held.select(values.mean().alias("mean"), *quantiles).row(0))


def _path_line(row: Mapping[str, Any]) -> str:
    return (
        f"{counted(row['bars_after'], 'bar'):>8} after  {counted(row['events'], 'event'):>12}  "
        f"mean {_signed(row['mean_ticks'])}  median {_signed(row['median_ticks'])}"
    )


def _signed(value: object) -> str:
    return "none" if value is None else f"{value:+.2f}"


def _size(value: object) -> str:
    return "none" if value is None else f"{value:.2f}"
