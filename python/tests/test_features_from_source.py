"""A feature from a code string (step 3.7, `BACKLOG.md`): `ff.features.from_source` builds a
feature again from the text its version keeps, with no file or notebook cell holding that text,
as a feature read from the library by name and version is, and refuses a text that reads names
its version does not keep."""

import re

import polars as pl
import pytest

import fefat as ff
from notebook_runs import features_of_cell

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature with one parameter, as a notebook cell defines it."""

READER = """\
@ff.feature(params={"n": 2})
def base(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(n)


@ff.feature(inputs=[base], outputs={"lifted": "price"})
def lifted(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("base") + 1
"""
"""A feature reading another by its name."""

BARS = pl.DataFrame(
    {
        "ts_close": [1, 2, 3, 4, 5],
        "close": [10, 13, 11, 16, 12],
        "close_raw": [10, 13, 11, 16, 12],
    }
)


def test_the_code_of_a_feature_gives_the_same_feature_again() -> None:
    gap = features_of_cell(GAP)["gap"]

    built = ff.features.from_source(gap.code)

    assert built.hash == gap.hash
    assert built.code == gap.code
    assert built(n=2).evaluate(BARS).collect().equals(gap(n=2).evaluate(BARS).collect())


def test_an_indicator_without_helpers_is_built_from_its_code() -> None:
    sma = ff.indicators.sma

    built = ff.features.from_source(sma.code)

    assert built.hash == sma.hash
    assert built(4).evaluate(BARS).collect().equals(sma(4).evaluate(BARS).collect())


def test_a_feature_that_reads_another_by_its_name_is_built_with_the_definition_given() -> None:
    defined = features_of_cell(READER)

    built = ff.features.from_source(defined["lifted"].code, reads=[defined["base"]])

    assert built.hash == defined["lifted"].hash
    with pytest.raises(ValueError, match=re.escape("got: name 'base' is not defined: give the")):
        ff.features.from_source(defined["lifted"].code)


def test_a_body_that_calls_a_helper_its_version_does_not_keep_is_refused() -> None:
    # BACKLOG.md: a helper the feature calls is not versioned with it, so its text alone cannot
    # build it, as the indicators' exponential averages show.
    refusal = (
        "Expected the body of feature rsi to read only its parameters and the names its code may "
        "read (ff, pl, the input kinds, and the parameter types), got exponential_average"
    )

    with pytest.raises(ValueError, match=re.escape(refusal)):
        ff.features.from_source(ff.indicators.rsi.code)


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("x = 1\n", id="no-feature"),
        pytest.param(GAP + "\n\n" + GAP.replace("def gap", "def other"), id="two-features"),
        pytest.param("def gap(bars):\n    return bars\n", id="no-decorator"),
    ],
)
def test_a_text_that_is_not_one_feature_is_refused(code: str) -> None:
    with pytest.raises(ValueError, match="Expected the code of one feature, a function under"):
        ff.features.from_source(code)
