"""A warm-up counted in sessions (step 3.6, D-78): a feature that looks back whole sessions, as the
session before or the week so far do, declares `warmup_sessions` beside its warm-up in bars, which
its hash and its version keep. The runtime reads that many sessions before a window on any
timeframe, and nulls a feature's values until, from where the features it reads have their first
values, that many whole sessions and then its bars have passed."""

import os
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features.runtime import FeatureGraph
from fefat.market import instruments
from fefat.market.calendar import sessions_of
from fefat.market.schema import Timeframe
from generated_minutes import SPRING, write_minutes
from notebook_runs import features_of_cell

FIVE, DAILY = Timeframe.parse("5m"), Timeframe.parse("1d")
MINUTE = 60_000_000_000
GAP = """\
@ff.feature(params={"n": 3}, warmup_sessions=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature whose warm-up in sessions is a lambda of its parameter, as a notebook cell defines it."""


def cell(decorator: str, before: str = "") -> str:
    """A cell defining the feature `gap` of one parameter under `decorator`."""
    return (
        f"{before}{decorator}\ndef gap(bars: pl.LazyFrame, n: int) -> pl.Expr:\n"
        '    return pl.col("close")\n'
    )


def bars(closes: list[int], per_session: int) -> pl.DataFrame:
    """One series of 5-minute bars, `per_session` to a trade date from 2026-03-02 on."""
    rows = range(len(closes))
    return pl.DataFrame(
        {
            "ts_open": [index * 5 * MINUTE for index in rows],
            "ts_close": [(index + 1) * 5 * MINUTE for index in rows],
            "trade_date": [date(2026, 3, 2 + index // per_session) for index in rows],
            "close": closes,
            "close_raw": closes,
        }
    )


@ff.feature(warmup=1, outputs={"step": "price_distance"})
def step(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").diff()


@ff.feature(warmup=1, warmup_sessions=1, outputs={"change": "price_distance"})
def change_after_a_session(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").diff()


@ff.feature(warmup_sessions=1, outputs={"previous_last": "price"})
def previous_last_close(bars: pl.LazyFrame) -> pl.LazyFrame:
    lasts = bars.group_by("trade_date").agg(previous_last=pl.col("close").last())
    shifted = lasts.sort("trade_date").with_columns(pl.col("previous_last").shift(1))
    joined = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "previous_last")


@ff.feature(inputs=[step], warmup_sessions=1, outputs={"previous_peak": "price_distance"})
def previous_peak(bars: pl.LazyFrame) -> pl.LazyFrame:
    peaks = bars.group_by("trade_date").agg(previous_peak=pl.col("step").max())
    shifted = peaks.sort("trade_date").with_columns(pl.col("previous_peak").shift(1))
    joined = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "previous_peak")


@ff.feature(inputs=[previous_last_close], outputs={"above": "flag"})
def above_previous_last(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") > pl.col("previous_last")


@ff.feature(warmup_sessions=1, outputs={"two_back": "price"})
def close_two_sessions_ago(bars: pl.LazyFrame) -> pl.LazyFrame:
    lasts = bars.group_by("trade_date").agg(two_back=pl.col("close").last())
    shifted = lasts.sort("trade_date").with_columns(pl.col("two_back").shift(2))
    joined = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "two_back")


def test_a_warmup_in_sessions_is_kept_bound_and_covered_by_the_hash() -> None:
    gap = features_of_cell(GAP)["gap"]
    one = features_of_cell(GAP.replace("lambda n: n", "1"))["gap"]
    two = features_of_cell(GAP.replace("lambda n: n", "2"))["gap"]

    assert gap.written_warmup_sessions == "lambda n: n"
    assert (gap(n=4).warmup_sessions, gap(n=4).warmup) == (4, 0)
    assert (one.written_warmup_sessions, one().warmup_sessions) == (1, 1)
    assert len({gap.hash, one.hash, two.hash}) == 3


@pytest.mark.parametrize(
    ("source", "refusal"),
    [
        pytest.param(
            cell('@ff.feature(params={"n": 3}, warmup_sessions=SESSIONS)', "SESSIONS = 1\n\n\n"),
            "Expected the session warm-up of feature gap written in its decorator, as a number "
            "of sessions or a lambda of its parameters, got SESSIONS.",
            id="from-elsewhere",
        ),
        pytest.param(
            cell('@ff.feature(params={"n": 3}, warmup_sessions=lambda m: m)'),
            "Expected the session warm-up of feature gap to read its parameters (n), got m.",
            id="of-another-parameter",
        ),
        pytest.param(
            cell('@ff.feature(params={"n": 3}, warmup_sessions=-1)'),
            "Expected the session warm-up of feature gap as a whole number of sessions, at "
            "least 0, or a lambda of its parameters, got -1.",
            id="below-zero",
        ),
    ],
)
def test_a_warmup_in_sessions_its_version_could_not_keep_is_refused(
    source: str, refusal: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(refusal)):
        features_of_cell(source)


def test_a_version_keeps_its_warmup_in_sessions_and_refuses_one_changed() -> None:
    saved = ff.features.save(features_of_cell(GAP)["gap"])
    path = resolve_paths(os.environ).features_dir / "gap" / "v1.json"

    assert saved.warmup_sessions == "lambda n: n"
    assert ff.features.load("gap", 1) == saved
    written = b'"warmup_sessions": "lambda n: n"'
    path.write_bytes(path.read_bytes().replace(written, b'"warmup_sessions": 0'))
    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.features.load("gap", 1)


def test_evaluate_flags_the_rows_of_its_first_sessions_then_its_bars() -> None:
    frame = bars([10, 11, 12, 13, 14, 15], per_session=2)

    flagged = change_after_a_session().evaluate(frame).collect()["warmup"].to_list()

    assert flagged == [True, True, True, False, False, False]
    expected = (
        "Expected trade_date in the bars of feature change_after_a_session, whose warm-up counts "
        "sessions, got none."
    )
    with pytest.raises(ValueError, match=re.escape(expected)):
        change_after_a_session().evaluate(frame.drop("trade_date"))


def test_whole_sessions_count_from_where_the_features_read_have_their_first_values() -> None:
    # The step's first value, at the second bar, lies inside the first session, whose peak the
    # second session reads without the first bar's step: only the second session is whole, so
    # the peak of the session before has its first value on the third session, from either start.
    frame = bars([10, 13, 11, 15, 14, 18, 20, 19, 22], per_session=3)
    graph = FeatureGraph.of({"step": step(), "peak": previous_peak()}, "ES", FIVE)

    values = graph.evaluate({graph.signal_grid: frame})

    assert values["peak"].to_list() == [None] * 6 + [4] * 3
    assert graph.session_warmups[graph.slots["peak"]] == 2
    later = graph.evaluate({graph.signal_grid: frame.slice(3)})
    assert later["peak"].to_list() == [None] * 6


def test_a_reader_inherits_the_sessions_of_the_feature_it_reads() -> None:
    frame = bars([10, 11, 12, 13, 14, 15], per_session=2)
    graph = FeatureGraph.of(
        {"last": previous_last_close(), "above": above_previous_last()}, "ES", FIVE
    )

    values = graph.evaluate({graph.signal_grid: frame})

    assert values["last"].to_list() == [None, None, 11, 11, 13, 13]
    assert values["above"].to_list() == [None, None, True, True, True, True]
    assert graph.session_warmups[graph.slots["above"]] == 1


def test_the_lead_in_reads_the_sessions_a_warmup_counts_on_any_timeframe(tmp_path: Path) -> None:
    # Before Monday 2026-03-09: a session is the Friday, whatever the bars; a session and a bar
    # read the Thursday too; and the peak of the session before a step's first value, which may
    # fall inside a session, reads a session more.
    sessions = sessions_of(instruments.get("ES").session_calendar(), tmp_path)
    monday = date(2026, 3, 9)

    def lead_in(slots: dict[str, ff.features.FeatureSpec], timeframe: Timeframe = FIVE) -> date:
        return FeatureGraph.of(slots, "ES", timeframe).lead_in(sessions, monday)

    assert lead_in({"last": previous_last_close()}) == date(2026, 3, 6)
    assert lead_in({"last": previous_last_close()}, DAILY) == date(2026, 3, 6)
    assert lead_in({"last": previous_last_close(), "above": above_previous_last()}) == date(
        2026, 3, 6
    )
    assert lead_in({"change": change_after_a_session()}) == date(2026, 3, 5)
    assert lead_in({"step": step(), "peak": previous_peak()}) == date(2026, 3, 4)


def test_a_feature_that_reads_further_back_than_its_sessions_is_refused() -> None:
    # The feature cache compares a month's values read past its end with the next month's from
    # its own warm-up: a close two sessions back declared as one session differs on the first
    # session of each month.
    write_minutes(SPRING)

    with pytest.raises(ValueError, match="it remembers more than its warm-up of 1 session of 5m"):
        ff.features.compute(
            {"two_back": close_two_sessions_ago()}, "ES", "5m", "2026-01-05", "2026-03-31"
        )
