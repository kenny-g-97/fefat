"""`fefat_engine.running_drawdown` and `ff.backtest.running_drawdown` (step 2.11, replacing step
0.8's `max_drawdown`): how far an account's equity lies below the highest value before it, read
from an int64 Arrow array or stream through its own slice, without the values around it, and
prefix-invariant (the amendment of step 2.11, from the leakage review of the Phase 0 exit)."""

import array

import fefat_engine
import polars as pl
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

import fefat as ff

EQUITY = [100, 60, 90, -30, 20, 10]
DRAWDOWN = [0, 40, 10, 130, 80, 90]
equities = st.lists(st.integers(min_value=-(2**40), max_value=2**40), max_size=200)


def running_drawdown_by_definition(equity: list[int]) -> list[int]:
    """Each value's fall below the highest value up to it."""
    return [max(equity[: index + 1]) - value for index, value in enumerate(equity)]


def int64_array(values: list[int]) -> pa.Array:
    return pa.array(values, type=pa.int64())


@given(equities)
def test_the_engine_agrees_with_the_definition_in_plain_python(equity: list[int]) -> None:
    expected = running_drawdown_by_definition(equity)

    assert fefat_engine.running_drawdown(int64_array(equity)) == expected
    assert ff.backtest.running_drawdown(pl.Series(equity, dtype=pl.Int64)).to_list() == expected


@given(equities, st.integers(min_value=0, max_value=200))
def test_the_running_drawdown_of_a_prefix_is_the_prefix_of_the_running_drawdown(
    equity: list[int], cut: int
) -> None:
    whole = fefat_engine.running_drawdown(int64_array(equity))

    assert whole[:cut] == fefat_engine.running_drawdown(int64_array(equity[:cut]))


def test_a_sliced_array_is_read_without_the_values_around_it() -> None:
    around = int64_array([10_000, *EQUITY, -10_000])

    assert fefat_engine.running_drawdown(around.slice(1, len(EQUITY))) == DRAWDOWN


def test_a_sliced_series_is_read_without_the_values_around_it() -> None:
    around = pl.Series("equity", [10_000, *EQUITY, -10_000], dtype=pl.Int64)

    drawdown = ff.backtest.running_drawdown(around.slice(1, len(EQUITY)))

    assert drawdown.name == "equity"
    assert drawdown.to_list() == DRAWDOWN


def test_a_chunked_array_carries_its_peak_from_chunk_to_chunk() -> None:
    chunked = pa.chunked_array([EQUITY[:3], EQUITY[3:]], type=pa.int64())

    assert fefat_engine.running_drawdown(chunked) == DRAWDOWN


def test_no_values_give_no_drawdown() -> None:
    assert ff.backtest.running_drawdown(pl.Series([], dtype=pl.Int64)).to_list() == []


def test_a_buffer_that_is_not_an_arrow_array_is_refused() -> None:
    with pytest.raises(ValueError, match="__arrow_c_array__ or __arrow_c_stream__"):
        fefat_engine.running_drawdown(array.array("q", EQUITY))  # pyright: ignore[reportArgumentType]


def test_a_series_that_is_not_int64_is_refused_with_its_type_and_name() -> None:
    with pytest.raises(
        TypeError, match='Expected an int64 Arrow array, got Float64 in field "equity"'
    ):
        ff.backtest.running_drawdown(pl.Series("equity", [1.5, -2.0]))


def test_an_empty_array_that_is_not_int64_is_refused_too() -> None:
    with pytest.raises(TypeError, match="Expected an int64 Arrow array, got Float64"):
        fefat_engine.running_drawdown(pa.chunked_array([], type=pa.float64()))


def test_nulls_are_counted_across_every_chunk() -> None:
    values = pa.chunked_array([[1, None], [None, None, -2]], type=pa.int64())

    with pytest.raises(ValueError, match="without nulls, got 3 nulls"):
        fefat_engine.running_drawdown(values)


def test_a_fall_beyond_int64_is_an_overflow_error_that_names_its_values() -> None:
    with pytest.raises(OverflowError, match="overflow from 9223372036854775807 and -1"):
        fefat_engine.running_drawdown(int64_array([2**63 - 1, -1]))
