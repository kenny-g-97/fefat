"""A strategy from its code, step 5.2 (D-93): `ff.strategy.from_source` runs a version's code, a
module whose function `strategy` gives the `SignalStrategy`, builds the strict model of the
function's parameters and the strategy with their defaults, and builds its signal frame on bars
with no rows; each refusal names the line of the code it is at (Done means 2), a feature version
the code reads that was never saved among them (the step's Prompt)."""

import pytest

import fefat as ff
from fefat.features import FeatureDef
from fefat.strategy.source_code import StrategyCodeError, from_source
from strategy_code import BREAKOUT, WITH_A_SLOT

DEFINED_ON = 6
INDICATOR_CALLS = {
    "bars_since": 'flag="roll_flag"',
    "distance_from_vwap": 'instrument="MES"',
    "vwap_since": 'flag="roll_flag"',
}
"""The arguments of the indicators that take one without a default."""


def refusal(code: str) -> StrategyCodeError:
    """How `from_source` refuses `code`."""
    with pytest.raises(StrategyCodeError) as refused:
        from_source(code)
    return refused.value


def test_a_strategy_is_built_with_its_defaults_and_with_parameters_of_its_own() -> None:
    definition = from_source(BREAKOUT)

    properties = definition.parameter_schema["properties"]
    assert definition.with_defaults.instrument == "MES"
    assert definition.with_defaults.execution.stop == ff.Stop(atr=1.5)
    assert definition(stop_atr=2.0).execution.stop == ff.Stop(atr=2.0)
    assert (properties["lookback"]["type"], properties["lookback"]["default"]) == ("integer", 12)
    assert (properties["stop_atr"]["type"], properties["stop_atr"]["default"]) == ("number", 1.5)
    assert definition.code == BREAKOUT


@pytest.mark.parametrize("parameters", [{"lookback": "20"}, {"lookback": 20.0}, {"other": 1}])
def test_parameters_are_validated_strictly(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Expected the strategy's parameters"):
        from_source(BREAKOUT)(**parameters)


def test_a_syntax_error_is_refused_with_its_line() -> None:
    # Done means 2, in the SDK: the editor of step 5.5 underlines the line.
    broken = BREAKOUT.replace('pl.col("close")', 'pl.col("close") +')

    refused = refusal(broken)

    assert refused.line == 7
    assert str(refused).startswith("SyntaxError: ")


def test_lines_are_counted_as_written_whatever_the_line_ends_and_the_blank_lines_above() -> None:
    broken = "\r\n\r\n" + BREAKOUT.replace('pl.col("close")', 'pl.col("close") +').replace(
        "\n", "\r\n"
    )

    assert refusal(broken).line == 9


def test_an_error_while_building_is_refused_at_the_innermost_line_of_the_code() -> None:
    helper = BREAKOUT.replace(
        "def strategy(",
        "def lookback_bars() -> int:\n    return 12 // 0\n\n\ndef strategy(",
    ).replace("rolling_max(lookback)", "rolling_max(lookback_bars())")

    refused = refusal(helper)

    assert refused.line == 7
    assert str(refused) == "ZeroDivisionError: integer division or modulo by zero"


def test_a_syntax_error_in_a_text_the_code_runs_is_put_at_the_line_that_runs_it() -> None:
    evaluated = BREAKOUT.replace(
        'close = pl.col("close")', 'close = pl.col("close")\n    exec("x = (")'
    )

    refused = refusal(evaluated)

    assert refused.line == 8
    assert str(refused).startswith("SyntaxError: ")


def test_a_feature_version_never_saved_is_refused_at_the_line_that_reads_it() -> None:
    # The step's Prompt: validation rejects a strategy that references a missing feature version.
    reads_gap = WITH_A_SLOT.format(
        feature='ff.features.ref("gap", version=3)', entry='pl.col("read") > 0'
    )

    refused = refusal(reads_gap)

    assert refused.line == 10
    assert "Expected version 3 of feature gap" in str(refused)


@pytest.mark.parametrize(
    ("entry", "said"),
    [
        ('pl.col("clsoe") > 0', '"clsoe"'),
        ('pl.col("close")', "Boolean"),
    ],
)
def test_a_signal_frame_that_bars_cannot_give_is_refused_before_a_version_exists(
    entry: str, said: str
) -> None:
    # A column no bar holds, and a signal that is no boolean, fail on bars with no rows.
    refused = refusal(WITH_A_SLOT.format(feature='pl.col("close")', entry=entry))

    assert refused.line == 6
    assert said in str(refused)


@pytest.mark.parametrize(
    ("code", "line", "said"),
    [
        ("import fefat as ff\n", None, "got no strategy"),
        (
            BREAKOUT.replace(
                "def strategy(lookback: int = 12, stop_atr: float = 1.5)", "def build()"
            )
            .replace("rolling_max(lookback)", "rolling_max(12)")
            .replace("atr=stop_atr", "atr=1.5")
            + "\n\nstrategy = build()\n",
            26,
            "write `def strategy() -> ff.SignalStrategy:`",
        ),
        (BREAKOUT.replace("lookback: int = 12", "lookback=12"), 6, "lookback without one"),
        (BREAKOUT.replace("lookback: int = 12", "lookback: int"), 6, "lookback without one"),
        (BREAKOUT.replace("lookback: int = 12", "lookback: int = 1.5"), 6, "default of lookback"),
        (BREAKOUT.replace("lookback: int = 12", "*lookbacks: int"), 6, "by name"),
        (BREAKOUT.replace("return ff.SignalStrategy(", "return dict("), 6, "got dict"),
    ],
)
def test_code_that_gives_no_strategy_is_refused_in_words(
    code: str, line: int | None, said: str
) -> None:
    refused = refusal(code)

    assert refused.line == line
    assert said in str(refused)


@pytest.mark.parametrize(
    ("parameter", "said"),
    [("_hidden: int = 12", "_hidden"), ("side: Side = Side.LONG", "can send as JSON")],
)
def test_parameters_a_form_cannot_set_are_refused(parameter: str, said: str) -> None:
    # A name Pydantic keeps for itself, and a StrEnum, which a strict model takes as its members
    # alone, so that the JSON of a form never sets it.
    code = (
        'from enum import StrEnum\n\n\nclass Side(StrEnum):\n    LONG = "long"\n\n\n'
        + BREAKOUT.replace("lookback: int = 12", parameter).replace(
            "rolling_max(lookback)", "rolling_max(12)"
        )
    )

    refused = refusal(code)

    assert refused.line == DEFINED_ON + 7
    assert said in str(refused)


def test_a_module_of_its_own_runs_dataclasses_features_and_no_main_block() -> None:
    # Postponed annotations make a dataclass look its module up in sys.modules; a feature defined
    # in the code finds its text; and a block under `if __name__ == "__main__"` stays unrun.
    code = """\
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

import fefat as ff


@dataclass(frozen=True)
class Window:
    bars: int


@ff.feature(params={"n": 3}, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)


def strategy() -> ff.SignalStrategy:
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={"gap": gap(Window(bars=4).bars)},
        long_entry=pl.col("gap") > 0,
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )


if __name__ == "__main__":
    raise SystemExit(1)
"""

    definition = from_source(code)

    assert definition.with_defaults.feature_columns() == ("gap",)


@pytest.mark.parametrize(
    "name",
    [
        name
        for name in ff.indicators.__all__
        if isinstance(getattr(ff.indicators, name), FeatureDef)
    ],
)
def test_every_indicator_of_the_sdk_gives_its_columns_on_bars_with_no_rows(name: str) -> None:
    # The check on bars with no rows refuses no strategy that reads an indicator of the SDK.
    call = f"ff.indicators.{name}({INDICATOR_CALLS.get(name, '')})"

    definition = from_source(WITH_A_SLOT.format(feature=call, entry="pl.lit(True)"))

    assert definition.with_defaults.feature_columns()
