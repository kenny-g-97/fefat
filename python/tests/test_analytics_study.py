"""The feature study (step 3.8, Done means 1): on bars where one feature foretells the next bar's
move, it finds that feature's information coefficient significant and an unrelated feature's not;
its quantile returns rise with the planted feature, with day-block intervals that exclude 0 at the
ends; features that say the same share a cluster; an event study follows a flag's events; and the
trials counter counts every feature and horizon examined, beside every result."""

import random
from datetime import date, timedelta
from itertools import accumulate

import polars as pl
import pytest

from fefat.analytics import FeatureStudy, PositionSide
from fefat.analytics.labels import forward_returns

TICK = 250_000_000
FIRST_DATE = date(2025, 12, 12)
DAYS, BARS = 40, 60


def planted_bars(seed: int = 0) -> pl.DataFrame:
    """Forty trade dates of sixty bars of ES, across a year's end: each bar's move, its close less
    its open in ticks, is twice the feature `planted` of the bar before plus noise of four ticks;
    `twin` is `planted` with a little noise, and `random` foretells nothing."""
    draw = random.Random(seed)
    days = [
        planted_day(draw, FIRST_DATE + timedelta(days=number), number) for number in range(DAYS)
    ]
    return pl.concat(days)


def planted_day(draw: random.Random, trade_date: date, number: int) -> pl.DataFrame:
    planted = [draw.gauss(0, 1) for _ in range(BARS)]
    unrelated = [draw.gauss(0, 1) for _ in range(BARS)]
    twin = [value + draw.gauss(0, 0.1) for value in planted]
    moves = [round(draw.gauss(0, 4))]
    moves += [round(2 * planted[bar - 1] + draw.gauss(0, 4)) for bar in range(1, BARS)]
    opens = list(accumulate(moves[:-1], initial=20_000))
    closes = [opened + move for opened, move in zip(opens, moves, strict=True)]
    return pl.DataFrame(
        {
            "ts_close": [(number * BARS + bar + 1) * 300 * 10**9 for bar in range(BARS)],
            "trade_date": [trade_date] * BARS,
            "contract": ["ESH2026"] * BARS,
            "open": [opened * TICK for opened in opens],
            "high": [(max(pair) + 1) * TICK for pair in zip(opens, closes, strict=True)],
            "low": [(min(pair) - 1) * TICK for pair in zip(opens, closes, strict=True)],
            "close_raw": [closed * TICK for closed in closes],
            "zero_volume": [False] * BARS,
            "planted": planted,
            "twin": twin,
            "random": unrelated,
        }
    )


def by_horizon(frame: pl.DataFrame, horizon: int) -> pl.DataFrame:
    return frame.filter(pl.col("horizon") == horizon)


def test_a_planted_feature_has_a_significant_ic_and_a_random_feature_has_not() -> None:
    study = FeatureStudy(planted_bars(), "ES", horizons=(1, 5, 20))

    planted = study.information_coefficient("planted")
    unrelated = study.information_coefficient("random")

    first = by_horizon(planted.by_horizon, 1).row(0, named=True)
    means = dict(planted.by_horizon.select("horizon", "mean_coefficient").iter_rows())
    assert first["days"] == DAYS
    assert first["mean_coefficient"] > 0.2
    assert first["t_statistic"] > 3
    assert means[1] > means[5] > means[20]
    assert planted.by_year.get_column("year").unique().sort().to_list() == [2025, 2026]
    assert (unrelated.by_horizon.get_column("t_statistic").abs() < 2).all()


def random_walk(seed: int = 7, days: int = 65, bars: int = 276) -> pl.DataFrame:
    """A random walk of ES's 5-minute bars, a session of `bars` each trade date, with
    `close_location`, where the close lies in the range of the last 20 bars, a persistent feature
    that foretells nothing."""
    draw = random.Random(seed)
    frames = []
    for number in range(days):
        moves = [round(draw.gauss(0, 6)) for _ in range(bars)]
        opens = list(accumulate(moves[:-1], initial=20_000))
        closes = [opened + move for opened, move in zip(opens, moves, strict=True)]
        frames.append(
            pl.DataFrame(
                {
                    "ts_close": [(number * bars + bar + 1) * 300 * 10**9 for bar in range(bars)],
                    "trade_date": [FIRST_DATE + timedelta(days=number)] * bars,
                    "contract": ["ESH2026"] * bars,
                    "open": [opened * TICK for opened in opens],
                    "high": [(max(pair) + 1) * TICK for pair in zip(opens, closes, strict=True)],
                    "low": [(min(pair) - 1) * TICK for pair in zip(opens, closes, strict=True)],
                    "close": [closed * TICK for closed in closes],
                    "close_raw": [closed * TICK for closed in closes],
                    "zero_volume": [False] * bars,
                }
            )
        )
    highest, lowest = pl.col("high").rolling_max(20), pl.col("low").rolling_min(20)
    location = pl.when(highest > lowest).then((pl.col("close") - lowest) / (highest - lowest))
    return pl.concat(frames).with_columns(close_location=location.over("trade_date"))


def test_a_persistent_feature_on_a_random_walk_has_no_significant_ic() -> None:
    # A feature that changes slowly, ranked against the returns of its own day alone, leans
    # towards a negative coefficient on a walk that foretells nothing (t -2.9, -2.5, and -3.4
    # here); ranked among all the bars studied, it shows none.
    coefficient = FeatureStudy(random_walk(), "ES").information_coefficient("close_location")

    assert coefficient.by_horizon.get_column("days").to_list() == [65] * 3
    assert (coefficient.by_horizon.get_column("t_statistic").abs() < 2).all()


def test_quantile_returns_rise_with_the_planted_feature() -> None:
    study = FeatureStudy(planted_bars(), "ES")

    planted = by_horizon(study.quantile_returns("planted").frame, 1)
    unrelated = by_horizon(study.quantile_returns("random").frame, 1)
    again = FeatureStudy(planted_bars(), "ES").quantile_returns("planted").frame
    reseeded = FeatureStudy(planted_bars(), "ES", seed=1).quantile_returns("planted").frame

    means = planted.get_column("mean_ticks").to_list()
    spread = means[-1] - means[0]
    random_means = unrelated.get_column("mean_ticks").to_list()
    assert planted.get_column("quantile").to_list() == [1, 2, 3, 4, 5]
    assert means == sorted(means)
    assert planted.item(4, "interval_low_ticks") > 0
    assert planted.item(0, "interval_high_ticks") < 0
    assert abs(random_means[-1] - random_means[0]) < spread / 4
    assert planted.get_column("bars").sum() == DAYS * (BARS - 2)
    assert again.equals(study.quantile_returns("planted").frame)
    assert reseeded.get_column("mean_ticks").equals(again.get_column("mean_ticks"))
    assert not reseeded.get_column("interval_low_ticks").equals(
        again.get_column("interval_low_ticks")
    )


def test_a_quantile_on_few_trade_dates_has_no_interval() -> None:
    # The code review: a quantile whose bars fall on two trade dates is missing from about one
    # draw in eight, whose means a narrower interval would leave out; it gets none.
    rare = pl.when(pl.col("trade_date") <= FIRST_DATE + timedelta(days=1)).then(10.0).otherwise(0.0)
    study = FeatureStudy(planted_bars().with_columns(rare=rare), "ES")

    returns = study.quantile_returns("rare")

    intervals = returns.frame.select("quantile", "interval_low_ticks", "interval_high_ticks")
    assert intervals.filter(pl.col("quantile") == 5).null_count().row(0) == (0, 3, 3)
    assert intervals.filter(pl.col("quantile") == 1).null_count().row(0) == (0, 0, 0)
    assert "interval none to none" in returns.report()


def test_many_quantiles_of_many_bars_reach_the_last_quantile() -> None:
    # The second code review: the rank times the quantiles wrapped round in 32 bits from 4.3e9,
    # here 99,999 times 50,000, and put the highest bars in a low quantile. The highest values
    # open the series, so that their bars have a forward return.
    count, per_day = 100_000, 2_500
    position = pl.int_range(count)
    walk = (position.hash(1) % 9).cast(pl.Int64) - 4
    bars = pl.select(
        ts_close=(position + 1) * 300 * 10**9,
        trade_date=pl.lit(FIRST_DATE) + pl.duration(days=position // per_day),
        contract=pl.lit("ESH2026"),
        open=(20_000 + walk) * TICK,
        zero_volume=pl.lit(False),
        rank=(count - position).cast(pl.Float64),
    ).with_columns(high=pl.col("open") + TICK, low=pl.col("open") - TICK, close_raw=pl.col("open"))
    study = FeatureStudy(bars, "ES", horizons=(1,), resamples=1)

    frame = study.quantile_returns("rank", quantiles=50_000).frame

    assert frame.get_column("quantile").max() == 50_000
    assert frame.filter(pl.col("quantile") == 50_000).item(0, "feature_low") == count - 1


def test_identical_days_have_no_t_statistic() -> None:
    # The second code review: days whose coefficients are all the same have no spread, so their
    # mean over it is no number; the t-statistic is none, not infinite.
    days = [planted_day(random.Random(0), FIRST_DATE + timedelta(days=day), day) for day in (0, 1)]

    coefficient = FeatureStudy(pl.concat(days), "ES").information_coefficient("planted")

    assert coefficient.by_horizon.get_column("days").to_list() == [2, 2, 2]
    assert coefficient.by_horizon.get_column("t_statistic").null_count() == 3


def test_a_feature_named_like_a_column_the_analyses_add_is_studied_as_any() -> None:
    # The code review: a feature named quantile, or a flag named mae_ticks, kept its values.
    renamed = planted_bars().rename({"planted": "quantile"})
    flags = flagged_bars().rename({"signal": "mae_ticks"})

    quantiles = FeatureStudy(renamed, "ES").quantile_returns("quantile").frame
    events = FeatureStudy(flags, "ES", horizons=(1, 2)).event_study("mae_ticks", PositionSide.LONG)

    assert quantiles.equals(FeatureStudy(planted_bars(), "ES").quantile_returns("planted").frame)
    assert events.path.rows() == [(1, 2, 1.5, 1.5), (2, 2, 3.0, 3.0)]


def off_grid_bars(days: int = 400) -> pl.DataFrame:
    """`days` trade dates of planted bars whose opens lie off the tick grid, so that each forward
    return is a fraction of ticks, and enough of them for Polars to sum them in parallel."""
    draw = random.Random(3)
    bars = pl.concat(
        planted_day(draw, FIRST_DATE + timedelta(days=day), day) for day in range(days)
    )
    offsets = pl.Series([draw.randrange(1, TICK) for _ in range(bars.height)])
    return bars.with_columns(pl.col("open") + offsets)


def test_quantile_returns_are_the_same_at_each_run() -> None:
    # The Phase 4 exit: Polars summed a group's labels in the order its threads gathered them,
    # so the means and intervals differed in their last bits from one run to the next (D-11).
    study = FeatureStudy(off_grid_bars(), "ES")

    frames = [study.quantile_returns("planted").frame for _ in range(10)]

    assert all(frame.equals(frames[0]) for frame in frames[1:])


def test_correlations_cluster_the_features_that_say_the_same() -> None:
    study = FeatureStudy(planted_bars(), "ES")

    correlated = study.correlations(["random", "twin", "planted"])

    matrix = correlated.matrix
    assert correlated.clusters.rows() == [("planted", 1), ("twin", 1), ("random", 2)]
    assert matrix.get_column("feature").to_list() == ["planted", "twin", "random"]
    assert matrix.columns == ["feature", "planted", "twin", "random"]
    assert [matrix.item(row, name) for row, name in enumerate(["planted", "twin", "random"])] == [
        1.0
    ] * 3
    assert matrix.item(0, "twin") == matrix.item(1, "planted") > 0.9
    assert abs(matrix.item(0, "random")) < 0.1
    assert correlated.trials.pairs == frozenset()


def flagged_bars() -> pl.DataFrame:
    """One trade date of eight bars of ES, opens in ticks, each high a tick above its open and
    each low a tick below, and the flag `signal` true on the first two bars, the fourth, and the
    last, after which no bar trades."""
    opens = [100, 102, 101, 105, 104, 108, 107, 110]
    return pl.DataFrame(
        {
            "ts_close": [(bar + 1) * 300 * 10**9 for bar in range(8)],
            "trade_date": [FIRST_DATE] * 8,
            "contract": ["ESH2026"] * 8,
            "open": [opened * TICK for opened in opens],
            "high": [(opened + 1) * TICK for opened in opens],
            "low": [(opened - 1) * TICK for opened in opens],
            "close_raw": [opened * TICK for opened in opens],
            "zero_volume": [False] * 8,
            "signal": [True, True, False, True, False, False, False, True],
        }
    )


def test_an_event_study_follows_each_event_and_its_excursions() -> None:
    # Two events, the first bar and the fourth, entering at 102 and 104 ticks: after one bar at
    # 101 and 108, after two at 105 and 107; held two bars, they reach 105 and 109 and fall to
    # 100 and 103, their exits included. The flag on the last bar has no bar to enter on.
    study = FeatureStudy(flagged_bars(), "ES", horizons=(1, 2))

    long = study.event_study("signal", PositionSide.LONG, horizon=2)
    short = study.event_study("signal", PositionSide.SHORT, horizon=2)
    planted = FeatureStudy(planted_bars().with_columns(high_planted=pl.col("planted") > 1.5), "ES")
    after_one = planted.event_study("high_planted", PositionSide.LONG, horizon=1).path

    assert long.events == 2
    assert long.path.rows() == [(1, 2, 1.5, 1.5), (2, 2, 3.0, 3.0)]
    assert dict(long.excursions.select("statistic", "mae_ticks").iter_rows())["mean"] == 1.5
    assert dict(long.excursions.select("statistic", "mfe_ticks").iter_rows())["median"] == 4.0
    assert short.path.get_column("mean_ticks").to_list() == [-1.5, -3.0]
    assert short.excursions.get_column("mae_ticks").equals(long.excursions.get_column("mfe_ticks"))
    assert short.excursions.get_column("mfe_ticks").equals(long.excursions.get_column("mae_ticks"))
    assert abs(after_one.item(0, "mean_ticks") - 2 * 1.94) < 1


def test_the_trials_count_what_was_examined_beside_every_result() -> None:
    bars = planted_bars().with_columns(high_planted=pl.col("planted") > 1.5)
    study = FeatureStudy(bars, "ES", horizons=(1, 5, 20))

    quantiles = study.quantile_returns("planted")
    coefficient = study.information_coefficient("random")
    correlated = study.correlations(["planted", "random"])
    events = study.event_study("high_planted", PositionSide.LONG, horizon=5)

    assert (quantiles.trials.features, quantiles.trials.horizons) == (1, 3)
    assert (coefficient.trials.features, len(coefficient.trials.pairs)) == (2, 6)
    assert correlated.trials == coefficient.trials
    assert (events.trials.features, events.trials.horizons, len(events.trials.pairs)) == (3, 6, 11)
    assert study.trials == events.trials
    assert coefficient.trials.line() == (
        "Trials so far: 2 features and 3 horizons examined, 6 feature-horizon pairs; a "
        "t-statistic beyond 2.64 either way keeps 5 % significance across them."
    )
    for result in (quantiles, coefficient, correlated, events):
        report = result.report()
        assert report.endswith(result.trials.line())
        assert report.isascii()


ALTERNATE_CONTRACTS = (
    pl.when(pl.int_range(pl.len()) % 2 == 0).then(pl.lit("ESM2026")).otherwise("contract")
)
FIRST_NAN = pl.when(pl.int_range(pl.len()) == 0).then(float("nan")).otherwise("planted")


@pytest.mark.parametrize(
    ("bars", "instrument", "refusal"),
    [
        (planted_bars().drop("zero_volume"), "ES", "got no zero_volume"),
        (planted_bars().with_columns(pl.col("open").cast(pl.Float64)), "ES", "got open as Float64"),
        (
            planted_bars().with_columns(contract=ALTERNATE_CONTRACTS),
            "ES",
            "Expected one contract each trade date, .* got 2 on 2025-12-12",
        ),
        (planted_bars().reverse(), "ES", "as one series, their closes strictly increasing"),
        (
            forward_returns(planted_bars().lazy(), (1,), TICK).collect(),
            "ES",
            "the label column next_open in the bars of the feature study: a label reads",
        ),
        (
            planted_bars().with_columns(close_raw=pl.lit(None, dtype=pl.Int64)),
            "ES",
            "got a back-adjusted import",
        ),
        (
            planted_bars(),
            "BTCUSDT-PERP",
            "Expected the bars of BTCUSDT-PERP, whose tick the study counts in, got contract ESH2026",
        ),
        (
            planted_bars().group_by("trade_date", maintain_order=True).first(),
            "ES",
            "Expected bars with a forward return over 1 bar within their trade date, got none",
        ),
    ],
)
def test_a_study_refuses_a_frame_of_other_than_signal_bars(
    bars: pl.DataFrame, instrument: str, refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        FeatureStudy(bars, instrument)


def test_a_study_refuses_a_horizon_no_bar_reaches_and_resamples_that_are_no_count() -> None:
    # The second code review: a horizon longer than every session gave no row and still counted
    # as examined; a fraction of a resample or of a quantile is no count.
    with pytest.raises(ValueError, match="forward return over 500 bars within their trade date"):
        FeatureStudy(planted_bars(), "ES", horizons=(1, 5, 500))
    with pytest.raises(ValueError, match=r"whole number of resamples from 1, got 2\.5"):
        FeatureStudy(planted_bars(), "ES", resamples=2.5)  # pyright: ignore[reportArgumentType]


def test_a_study_refuses_what_it_cannot_judge() -> None:
    bars = planted_bars().with_columns(
        flag=pl.col("planted") > 0, broken=FIRST_NAN, constant=pl.lit(1.0)
    )
    study = FeatureStudy(bars, "ES")
    refusals = [
        (lambda: FeatureStudy(bars, "ES", horizons=(5, 5)), "each once"),
        (lambda: study.quantile_returns("rsi"), "got rsi"),
        (lambda: study.information_coefficient("forward_return_1"), "labels and next_open apart"),
        (lambda: study.quantile_returns("flag"), "Expected the feature flag as numbers"),
        (lambda: study.quantile_returns("broken"), "Expected no NaN in the feature broken, got 1"),
        (lambda: study.quantile_returns("planted", 1), "whole number of quantiles from 2, got 1"),
        (
            lambda: study.quantile_returns("planted", 2.5),  # pyright: ignore[reportArgumentType]
            "whole number of quantiles from 2, got 2.5",
        ),
        (lambda: study.correlations(["planted", "constant"]), "that differ .* got 1"),
        (lambda: study.information_coefficient("constant"), "that differ .* got 1"),
        (lambda: study.correlations(["planted"]), "two features or more"),
        (
            lambda: study.event_study("planted", PositionSide.LONG),
            "Expected a flag for an event study, got planted as Float64",
        ),
    ]

    for analysis, refusal in refusals:
        with pytest.raises(ValueError, match=refusal):
            analysis()
    assert study.trials.pairs == frozenset()
