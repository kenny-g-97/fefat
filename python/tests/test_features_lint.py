"""The leak detector's lint (step 3.4, `02-engine-and-data.md` §6): a reading of a feature's source
that flags the usual ways of reading ahead, each finding with its line and why (Done means 3), and
warns of what the content hash leaves out (`BACKLOG.md`), in well under a second."""

import time
from datetime import date

import polars as pl

import fefat as ff
from fefat.features.examples import atr, in_session_window, rsi
from fefat.features.lint import LintFinding, LintRule, lint

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
    assert str(first) == (f"line {first.line}: ahead = close.shift(-1): {first.explanation}")
    assert "shift(1)" in first.explanation
    assert took < 1.0


def test_the_examples_have_no_finding() -> None:
    assert [lint(example.definition) for example in (rsi(), atr(), in_session_window())] == [
        (),
        (),
        (),
    ]


def test_aggregates_in_a_group_by_a_cumulative_window_or_a_list_are_no_finding() -> None:
    @ff.feature(outputs={"prior_high": "price"})
    def prior_high(bars: pl.LazyFrame) -> pl.LazyFrame:
        highs = bars.group_by("trade_date").agg(prior_high=pl.col("high").max())
        shifted = highs.sort("trade_date").with_columns(pl.col("prior_high").shift(1))
        running = pl.col("high").cum_max().over("trade_date").alias("running")
        hourly = pl.col("close").mean().rolling(index_column="ts_close", period="1h")
        listed = pl.concat_list("open", "close").list.max().alias("listed")
        frame = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
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
