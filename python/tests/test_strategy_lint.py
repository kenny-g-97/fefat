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


def test_the_guides_breakout_reads_nothing_ahead() -> None:
    assert ff.strategy.lint(BREAKOUT) == ()
