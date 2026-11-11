"""A strategy's lint, step 5.2 (D-93, D-12): the leak detector's rules on calls read every statement
of a strategy version's code, each finding with its line and why it reads ahead; the guide's
breakout has none."""

import fefat as ff
from fefat.features.source_lint import LintRule
from strategy_code import BREAKOUT

LEAKS = """\
import polars as pl

import fefat as ff


def strategy() -> ff.SignalStrategy:
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={
            "ahead": close.shift(-1),
            "filled": close.backward_fill(),
            "scaled": close / close.max(),
            "session_high": close.max().over("trade_date"),
        },
        long_entry=close > close.rolling_mean(12, center=True),
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )
"""
"""A strategy whose slots and signals read ahead five ways."""
READS = """\
import polars as pl

import fefat as ff
from fefat.analytics import labels


@ff.feature(outputs={"ahead": "other"})
def ahead(bars: pl.LazyFrame) -> pl.LazyFrame:
    ticks = labels.forward_returns(bars, (1,), 250_000_000)
    return ticks.select("ts_close", ahead=pl.col("forward_return_1"))


@ff.feature(outputs={"settlement": "price"})
def settlement(bars: pl.LazyFrame) -> pl.LazyFrame:
    settled = pl.scan_parquet("settlements.parquet")
    return bars.join(settled, on="trade_date").select("ts_close", "settlement")


def strategy() -> ff.SignalStrategy:
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={"ahead": ahead(), "settlement": settlement()},
        long_entry=pl.col("ahead") > 0,
        short_entry=pl.col("close") < pl.col("settlement"),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )
"""
"""A strategy whose features compute the labels and read a file (the step's leakage audit)."""


def test_the_lint_finds_reading_ahead_in_a_strategys_slots_and_signals_by_line() -> None:
    findings = ff.strategy.lint(LEAKS)

    assert [(finding.rule, finding.line) for finding in findings] == [
        (LintRule.NEGATIVE_SHIFT, 12),
        (LintRule.BACKWARD_FILL, 13),
        (LintRule.FULL_SAMPLE, 14),
        (LintRule.PARTITION_AGGREGATE, 15),
        (LintRule.CENTRED_WINDOW, 17),
    ]
    assert findings[0].source == '"ahead": close.shift(-1),'
    assert str(findings[0]).startswith('line 12: "ahead": close.shift(-1),: a negative shift')


def test_the_lint_finds_the_labels_and_the_data_a_strategys_features_read_by_line() -> None:
    findings = ff.strategy.lint(READS)

    assert [(finding.rule, finding.line) for finding in findings] == [
        (LintRule.READS_LABELS, 9),
        (LintRule.READS_DATA, 15),
    ]
    assert "the labels of ff.analytics" in findings[0].explanation
    assert "reads data itself" in findings[1].explanation


def test_the_lint_counts_lines_as_python_does_whatever_their_ends() -> None:
    findings = ff.strategy.lint('import polars as pl\rahead = pl.col("close").shift(-1)\r')

    assert [(finding.rule, finding.line) for finding in findings] == [(LintRule.NEGATIVE_SHIFT, 2)]


def test_the_guides_breakout_reads_nothing_ahead() -> None:
    assert ff.strategy.lint(BREAKOUT) == ()
