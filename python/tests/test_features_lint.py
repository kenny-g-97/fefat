"""The leak detector's lint (step 3.4, `02-engine-and-data.md` §6): a reading of a feature's source
that flags the usual ways of reading ahead, each finding with its line and why (Done means 3), and
warns of what the content hash leaves out (`BACKLOG.md`), in well under a second."""

import time
from datetime import date

import polars as pl

import fefat as ff
from fefat.analytics import labels
from fefat.features import examples
from fefat.features.examples import atr, in_session_window, rsi
from fefat.features.source_lint import LintFinding, LintRule, lint
from fefat.market.api import series_source
from fefat.market.schema import Timeframe

SESSION_START = date(2026, 3, 9)


@ff.feature(outputs={"everything": "other"})
def everything(bars: pl.LazyFrame) -> pl.LazyFrame:
    close = pl.col("close")
    ahead = close.shift(-1)
    filled = close.fill_null(strategy="backward").interpolate()
    centred = close.rolling_mean(window_size=5, center=True)
    scaled = close / close.max()
    session = close.mean().over("trade_date")
    future = close.reverse().cum_max().reverse()
    up = bars.filter(close > pl.col("open")).select("ts_close", up_close="close")
    joined = bars.join_asof(up, on="ts_close", strategy="forward")
    opened = bars.join_asof(up.rename({"ts_close": "ts_open"}), on="ts_open")
    named = (ahead + filled + centred + scaled + session + future).alias("everything")
    return joined.join(opened, on="ts_close").with_columns(named).select("ts_close", "everything")


def line_of(text: str) -> int:
    """The line of `everything`'s source, its decorator line 1, that holds `text`."""
    lines = everything.code.splitlines()
    (number,) = [number for number, line in enumerate(lines, start=1) if text in line]
    return number


def test_the_lint_explains_each_way_of_reading_ahead_with_its_line_in_under_a_second() -> None:
    # Done means 3: each finding names its rule, its line counted from the decorator, the line's
    # text, and why it reads ahead, and the lint takes well under a second.
    began = time.perf_counter()
    findings = lint(everything)
    took = time.perf_counter() - began

    assert [(finding.rule, finding.line) for finding in findings] == [
        (LintRule.NEGATIVE_SHIFT, line_of("close.shift(-1)")),
        (LintRule.BACKWARD_FILL, line_of('strategy="backward"')),
        (LintRule.CENTRED_WINDOW, line_of("center=True")),
        (LintRule.FULL_SAMPLE, line_of("close.max()")),
        (LintRule.PARTITION_AGGREGATE, line_of('.over("trade_date")')),
        (LintRule.REVERSED, line_of("reverse()")),
        (LintRule.FORWARD_JOIN, line_of('strategy="forward"')),
        (LintRule.JOIN_ON_OPEN, line_of('on="ts_open"')),
    ]
    assert all(finding.rule.looks_ahead for finding in findings)
    first = findings[0]
    assert str(first) == (
        f"line {first.line} of everything: ahead = close.shift(-1): {first.explanation}"
    )
    assert "shift(1)" in first.explanation
    assert took < 1.0


def test_the_examples_have_no_finding() -> None:
    assert [lint(example.definition) for example in (rsi(), atr(), in_session_window())] == [
        (),
        (),
        (),
    ]


def test_aggregates_in_a_group_by_a_cumulative_window_or_a_list_are_no_finding() -> None:
    # The step review: a group-by's own aggregate, `group_by(...).min()`, reduces each group, as
    # `agg` does, and is left to the cuts.
    @ff.feature(outputs={"prior_high": "price"})
    def prior_high(bars: pl.LazyFrame) -> pl.LazyFrame:
        highs = bars.group_by("trade_date").agg(prior_high=pl.col("high").max())
        shifted = highs.sort("trade_date").with_columns(pl.col("prior_high").shift(1))
        running = pl.col("high").cum_max().over("trade_date").alias("running")
        hourly = pl.col("close").mean().rolling(index_column="ts_close", period="1h")
        lows = bars.group_by("trade_date").min().select("trade_date", prior_low="low")
        listed = pl.concat_list("open", "close").list.max().alias("listed")
        frame = bars.join(shifted.join(lows, on="trade_date"), on="trade_date", how="left")
        return frame.with_columns(running, hourly, listed).select("ts_close", "prior_high")

    assert lint(prior_high) == ()


LEVEL = 5


def scaled_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close") * LEVEL


def test_the_lint_warns_of_a_helper_and_a_default_the_hash_leaves_out() -> None:
    # BACKLOG.md, What a feature's hash leaves out: a helper the function calls and a default
    # worked out when the feature is defined change no hash; the lint warns of both, and a
    # warning is no look-ahead.
    @ff.feature(params={"level": LEVEL}, outputs={"helped": "other"})
    def helped(bars: pl.LazyFrame, level: int) -> pl.Expr:
        return scaled_close(bars) + level + SESSION_START.day

    findings = lint(helped)

    assert [(finding.rule, finding.source) for finding in findings] == [
        (
            LintRule.NON_LITERAL_DEFAULT,
            '@ff.feature(params={"level": LEVEL}, outputs={"helped": "other"})',
        ),
        (LintRule.NAME_READ_OUTSIDE, "return scaled_close(bars) + level + SESSION_START.day"),
        (LintRule.NAME_READ_OUTSIDE, "return scaled_close(bars) + level + SESSION_START.day"),
    ]
    assert "SESSION_START" in findings[1].explanation
    assert "scaled_close" in findings[2].explanation
    assert not any(finding.rule.looks_ahead for finding in findings)
    assert isinstance(findings[0], LintFinding)


def doubled(closes: pl.Series) -> pl.Series:
    return closes * 2


@ff.feature(outputs={"binned": "other"})
def binned(bars: pl.LazyFrame) -> pl.Expr:
    bins = pl.col("close").qcut(5).to_physical()
    peaks = pl.col("high").peak_max()
    twice = pl.col("close").map_batches(lambda closes: doubled(closes))
    return (bins + peaks + twice).alias(examples.atr.name)


def test_the_lint_reads_quantile_bins_peaks_and_a_helper_inside_a_lambda() -> None:
    # The code review: bins from the full sample's quantiles and a peak, which compares a bar with
    # the next, read ahead; a helper called inside a lambda is read from outside the feature; and
    # an attribute that shares a name with a global, `atr` here, is no name the feature reads.
    def line(text: str) -> int:
        (number,) = [n for n, each in enumerate(binned.code.splitlines(), 1) if text in each]
        return number

    found = [(finding.rule, finding.line) for finding in lint(binned)]

    assert found == [
        (LintRule.FULL_SAMPLE, line("qcut")),
        (LintRule.CENTRED_WINDOW, line("peak_max")),
        (LintRule.NAME_READ_OUTSIDE, line("doubled(closes)")),
    ]


fetch = ff.market.load


@ff.feature(outputs={"read": "other"})
def reads_files(bars: pl.LazyFrame) -> pl.LazyFrame:
    daily = ff.market.load("ES", "1d", "2026-02-02", "2026-02-20")
    events = pl.scan_parquet("events.parquet")
    rolls = ff.market.roll_calendar("ES").rolls().lazy()
    weekly = fetch("ES", "1d", "2026-02-02", "2026-02-20").select("trade_date", week="close")
    with open("levels.txt") as levels:
        level = float(levels.read())
    joined = bars.join(daily, on="trade_date").join(events, on="trade_date")
    joined = joined.join(rolls, on="trade_date", how="left").join(weekly, on="trade_date")
    return joined.select("ts_close", read=pl.col("close") * level)


def test_a_feature_reading_data_itself_fails_its_validation_where_its_code_reads_it() -> None:
    # The leakage audit, two rounds: data a feature loads itself is never cut, so the lint names
    # each read, the store's, a Polars reader's, the roll calendar's, a file's, and a reader bound
    # to another name, and a finding of it fails a validation.
    def line(text: str) -> int:
        (number,) = [n for n, each in enumerate(reads_files.code.splitlines(), 1) if text in each]
        return number

    found = lint(reads_files)

    assert [(finding.rule, finding.line) for finding in found] == [
        (LintRule.READS_DATA, line("ff.market.load")),
        (LintRule.READS_DATA, line("pl.scan_parquet")),
        (LintRule.READS_DATA, line("roll_calendar")),
        (LintRule.READS_DATA, line("fetch(")),
        (LintRule.READS_DATA, line("open(")),
        (LintRule.READS_DATA, line("levels.read()")),
    ]
    assert all(each.rule.fails_validation and not each.rule.looks_ahead for each in found)


@ff.feature(outputs={"bought": "count"})
def reads_prints(bars: pl.LazyFrame) -> pl.LazyFrame:
    source = series_source("ES")
    held = source.side_volumes(Timeframe.parse("5m"), (date(2026, 3, 9), date(2026, 3, 9)))
    return bars.join(held.lazy(), on="ts_close").select("ts_close", bought="buy_volume")


def test_a_feature_reading_prints_itself_fails_its_validation() -> None:
    # Step 3.6: the prints by side a feature reads are cut as its trades input; read by the
    # feature itself, they are never cut.
    found = {(finding.rule, finding.line) for finding in lint(reads_prints)}

    assert found == {(LintRule.READS_DATA, 3), (LintRule.READS_DATA, 4)}


@ff.feature(warmup=20, outputs={"windowed": "other"})
def windowed(bars: pl.LazyFrame) -> pl.Expr:
    month = pl.col("contract").str.tail(4)
    highest = pl.col("high").rolling_map(lambda window: window.max(), window_size=20)
    widest = pl.concat_list("open", "close").list.eval(pl.element().max())
    stacked = pl.concat_list("open", "close").list.reverse()
    filled = pl.col("close").fill_null(strategy="mean")
    return highest + widest.list.first() + stacked.list.first() + filled + month.cast(pl.Int64)


def test_the_lint_leaves_each_rows_own_values_and_a_windows_function_to_the_cuts() -> None:
    # The leakage audit: a method of a namespace of each row's own values and an aggregate inside a
    # rolling window's function or a list's eval read nothing ahead, while a fill of nulls with the
    # whole column's mean reads every bar (the ponytail review).
    found = [(finding.rule, finding.source) for finding in lint(windowed)]

    assert found == [
        (LintRule.FULL_SAMPLE, 'filled = pl.col("close").fill_null(strategy="mean")'),
    ]


@ff.feature(outputs={"ahead": "other"})
def ahead(bars: pl.LazyFrame) -> pl.LazyFrame:
    ticks = labels.forward_returns(bars, (1,), 250_000_000)
    return ticks.select("ts_close", ahead=pl.col("forward_return_1"))


def test_a_feature_that_computes_the_labels_fails_a_validation() -> None:
    # The leakage audit of step 3.8: the labels read the future by design, so a feature built on
    # them is refused, where its own text, the platform's, showed no shift.
    findings = lint(ahead)

    assert [finding.rule for finding in findings] == [LintRule.READS_LABELS]
    assert LintRule.READS_LABELS.fails_validation
    assert LintRule.READS_LABELS.looks_ahead
