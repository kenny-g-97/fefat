from itertools import accumulate

import fefat_engine
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

import fefat


def max_drawdown_by_definition(values: list[int]) -> int:
    """The largest fall from any cumulative sum to a later one, with the sum starting at 0."""
    sums = list(accumulate(values, initial=0))
    return max(peak - later for index, peak in enumerate(sums) for later in sums[index:])


@given(st.lists(st.integers(min_value=-(2**40), max_value=2**40), max_size=200))
def test_the_engine_agrees_with_the_definition_in_plain_python(values: list[int]) -> None:
    expected = max_drawdown_by_definition(values)

    assert fefat_engine.max_drawdown(values) == expected
    assert fefat.stats.max_drawdown(pl.Series(values, dtype=pl.Int64)) == expected


def test_an_empty_series_has_no_drawdown() -> None:
    assert fefat.stats.max_drawdown(pl.Series([], dtype=pl.Int64)) == 0


def test_a_series_that_is_not_int64_is_refused_with_its_type() -> None:
    with pytest.raises(TypeError, match="Expected an int64 Arrow array, got Int32"):
        fefat.stats.max_drawdown(pl.Series([1, -2], dtype=pl.Int32))
