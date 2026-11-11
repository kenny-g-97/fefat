"""The templates of step 5.2 (D-93): the engine guide's breakout, a mean reversion reading
`ff.indicators.rsi` in a slot, and a breakout in an entry window with a flat-by time, each a
strategy version's code that builds on MES's 5-minute bars, reads nothing ahead, and states its
hypothesis on one line; together their parameters take every type step 5.5's form renders
(Done means 3)."""

import pytest

import fefat as ff
from fefat.strategy.starting_points import StrategyTemplate


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
