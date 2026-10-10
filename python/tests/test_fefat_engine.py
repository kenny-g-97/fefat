import fefat_engine
import polars as pl
import pyarrow as pa
import pytest

PNL = [100, -40, 30, -120, 50, -10]
MAX_DRAWDOWN = 130


def test_a_list_gives_the_deepest_fall_below_a_peak() -> None:
    assert fefat_engine.max_drawdown(PNL) == MAX_DRAWDOWN


def test_a_pyarrow_array_is_read_in_place() -> None:
    values = pa.array(PNL, type=pa.int64())

    assert fefat_engine.arrow_values_addresses(values) == [values.buffers()[1].address]
    assert fefat_engine.max_drawdown_arrow(values) == MAX_DRAWDOWN


def test_a_chunked_array_is_read_in_place_chunk_by_chunk() -> None:
    values = pa.chunked_array([PNL[:3], PNL[3:]], type=pa.int64())

    addresses = [chunk.buffers()[1].address for chunk in values.chunks]
    assert fefat_engine.arrow_values_addresses(values) == addresses
    assert fefat_engine.max_drawdown_arrow(values) == MAX_DRAWDOWN


def test_a_polars_series_is_read_in_place() -> None:
    series = pl.Series(PNL, dtype=pl.Int64)

    assert fefat_engine.arrow_values_addresses(series) == [series.to_arrow().buffers()[1].address]
    assert fefat_engine.max_drawdown_arrow(series) == MAX_DRAWDOWN


def test_an_array_that_is_not_int64_is_refused_with_its_type() -> None:
    with pytest.raises(TypeError, match="Expected an int64 Arrow array, got Float64"):
        fefat_engine.max_drawdown_arrow(pa.array([1.5, -2.0]))


def test_an_array_with_nulls_is_refused_with_their_count() -> None:
    with pytest.raises(ValueError, match="without nulls, got 1 nulls"):
        fefat_engine.max_drawdown_arrow(pa.array([1, None, -2], type=pa.int64()))


def test_a_sum_beyond_int64_is_an_overflow_error_that_names_the_value() -> None:
    with pytest.raises(OverflowError, match=r"overflow at index 1 \(value 1\)"):
        fefat_engine.max_drawdown([2**63 - 1, 1])


def test_a_series_that_is_not_int64_is_refused_with_its_type_and_name() -> None:
    with pytest.raises(
        TypeError, match='Expected an int64 Arrow array, got Float64 in field "pnl"'
    ):
        fefat_engine.max_drawdown_arrow(pl.Series("pnl", [1.5, -2.0]))


def test_an_empty_array_that_is_not_int64_is_refused_too() -> None:
    with pytest.raises(TypeError, match="Expected an int64 Arrow array, got Float64"):
        fefat_engine.max_drawdown_arrow(pa.chunked_array([], type=pa.float64()))


def test_nulls_are_counted_across_every_chunk() -> None:
    values = pa.chunked_array([[1, None], [None, None, -2]], type=pa.int64())

    with pytest.raises(ValueError, match="without nulls, got 3 nulls"):
        fefat_engine.max_drawdown_arrow(values)
