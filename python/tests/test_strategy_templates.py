"""The templates of step 5.2 (D-93): the engine guide's breakout, a mean reversion reading
`ff.indicators.rsi` in a slot, and a breakout in an entry window with a flat-by time, each a
strategy version's code that builds on MES's 5-minute bars, reads nothing ahead, and states its
hypothesis on one line; together their parameters take every type step 5.5's form renders
(Done means 3)."""

import polars as pl
import pytest

import fefat as ff
from fefat.strategy.starting_points import StrategyTemplate
from notebook_runs import store_with


def test_the_templates_are_the_breakout_the_mean_reversion_and_the_entry_window() -> None:
    assert [template.name for template in ff.strategy.templates()] == [
        "breakout",
        "mean_reversion",
        "entry_window",
    ]


@pytest.mark.parametrize("template", ff.strategy.templates(), ids=lambda template: template.name)
def test_each_template_builds_reads_nothing_ahead_and_states_its_hypothesis(
    template: StrategyTemplate,
) -> None:
    definition = ff.strategy.from_source(template.code)

    assert definition.code == template.code
    assert (definition.with_defaults.instrument, definition.with_defaults.timeframe) == (
        "MES",
        "5m",
    )
    assert ff.strategy.lint(template.code) == ()
    assert len(template.hypothesis.splitlines()) == 1
    assert template.hypothesis.endswith(".")


def test_the_templates_parameters_take_every_type_a_form_renders() -> None:
    kinds = {
        "enum" if "enum" in parameter else parameter["type"]
        for template in ff.strategy.templates()
        for parameter in ff.strategy.from_source(template.code)
        .parameter_schema["properties"]
        .values()
    }

    assert kinds == {"integer", "number", "boolean", "string", "enum"}


def test_each_template_saves_as_a_first_version() -> None:
    # The mean reversion pins the RSI and the ATR of the SDK, which a run needs no saved feature
    # of the trader's for.
    saved = [
        ff.strategy.save(template.name, template.code, hypothesis=template.hypothesis)
        for template in ff.strategy.templates()
    ]

    assert [version.version for version in saved] == [1, 1, 1]
    assert [pin.name for pin in saved[1].pinned_features] == ["atr", "rsi"]


@pytest.mark.parametrize(
    ("name", "signal", "step", "range_of_a_bar"),
    [
        ("breakout", "long_entry", 1.0, 1.0),
        ("entry_window", "long_entry", 1.0, 1.0),
        ("entry_window", "short_entry", -1.0, 1.0),
        ("breakout", "long_entry", 1.0, 0.0),
    ],
    ids=["breakout", "entry-window-long", "entry-window-short", "bars-without-a-range"],
)
def test_an_entry_waits_for_an_atr_its_stop_can_read(
    name: str, signal: str, step: float, range_of_a_bar: float
) -> None:
    # Step 5.6 (D-112): the ATR of these two is a plain expression, null on a window's first 13
    # bars and zero over bars without a range, where the engine refuses a stop (F-RND-01).
    (template,) = [each for each in ff.strategy.templates() if each.name == name]
    strategy = ff.strategy.from_source(template.code).with_defaults
    closes = pl.Series("close", [100 + step * bar for bar in range(30)])
    bars = pl.DataFrame(
        {"close": closes, "high": closes + range_of_a_bar, "low": closes - range_of_a_bar}
    )

    features = {
        name: feature for name, feature in strategy.features.items() if isinstance(feature, pl.Expr)
    }
    entries = bars.with_columns(**features).with_columns(entry=getattr(strategy, signal))

    assert not entries.filter(~(pl.col("atr") > 0).fill_null(False)).get_column("entry").any()
    if range_of_a_bar > 0:
        assert entries.filter(pl.col("atr") > 0).get_column("entry").any()


def test_a_breakout_from_the_first_bars_the_store_holds_runs() -> None:
    # Step 5.6 (D-112): with two closes to look back at it would enter inside the ATR's first 13
    # bars, whose stop the engine refuses, the run ending on its error.
    store_with("ohlcv-1m")
    (breakout,) = [each for each in ff.strategy.templates() if each.name == "breakout"]
    code = breakout.code.replace('instrument="MES"', 'instrument="ES"')
    version = ff.strategy.save("es_breakout", code, hypothesis=breakout.hypothesis)

    run = ff.backtest.run(version.strategy(lookback=2), "2026-03-05", "2026-03-09")

    assert run.record.summary.trades > 0
