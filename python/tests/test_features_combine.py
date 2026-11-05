"""Combinators of step 3.7 (`fefat.features.combine`): each gives the values worked out by hand on
bars built by hand; a combination is a feature whose code is generated from its description, the
same code for the same description whatever the order of its parameters, built again from that
code and from its description's JSON with the same hash, and versioned as a hand-written feature
is; and a description the code cannot evaluate is refused when it is defined. The leak detector's
run over each kind is `python/tests/features/leaks/test_leaks_combinations.py`."""

import json
import math
import re
import typing
from collections.abc import Callable
from statistics import mean, pstdev

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter

import fefat as ff
from fefat.features import Combination, FeatureSpec, TimeframeInput, combine, registry
from fefat.features.combinations import (
    TERMS,
    FeatureOutput,
    Operand,
    Term,
    Window,
    feature_output,
)
from fefat.features.grids import Grid
from fefat.features.runtime import FeatureGraph
from fefat.market.schema import Timeframe
from notebook_runs import features_of_cell

MINUTE = 60_000_000_000
FIVE, FIFTEEN = Timeframe.parse("5m"), Timeframe.parse("15m")


def bars(
    closes: list[int], width: int = 5, start: int = 0, volumes: list[int] | None = None
) -> pl.DataFrame:
    """One series of bars of `width` minutes from minute `start` on, closing at `closes`, each
    one unit above and below its close, with `volumes`, one each where they are left out."""
    opens = [(start + width * index) * MINUTE for index in range(len(closes))]
    return pl.DataFrame(
        {
            "ts_open": opens,
            "ts_close": [opened + width * MINUTE for opened in opens],
            "open": closes,
            "high": [close + 1 for close in closes],
            "low": [close - 1 for close in closes],
            "close": closes,
            "volume": pl.Series([1] * len(closes) if volumes is None else volumes, dtype=pl.UInt64),
            "close_raw": closes,
        }
    )


CLOSES = [10, 12, 11, 15, 14, 18]
BARS = bars(CLOSES, volumes=[5, 3, 8, 2, 7, 4])
WAVES = bars([1000 + round(40 * math.sin(index / 12)) + index % 3 for index in range(400)])
"""Four hundred bars rising and falling in waves of about 75 bars, longer than RSI(14)'s and
EMA(21)'s warm-ups."""


def evaluated(
    term: Operand,
    frames: dict[Grid, pl.DataFrame] | None = None,
    slots: dict[str, FeatureSpec] | None = None,
) -> pl.DataFrame:
    """The combination of `term`, defined as `combined`, evaluated on ES's 5-minute grid over
    `frames`, `BARS` where they are left out, beside the features of `slots`."""
    definition = combine.define("combined", term)
    graph = FeatureGraph.of({"combined": definition(), **(slots or {})}, "ES", FIVE)
    return graph.evaluate({graph.signal_grid: BARS} if frames is None else frames)


def _windows(size: int, statistic: Callable[[list[int]], float]) -> list[float | None]:
    return [None] * (size - 1) + [
        statistic(CLOSES[end - size + 1 : end + 1]) for end in range(size - 1, len(CLOSES))
    ]


def _z_score(window: list[int]) -> float:
    return (window[-1] - mean(window)) / pstdev(window)


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        pytest.param(combine.add("close", 2), [12, 14, 13, 17, 16, 20], id="add"),
        pytest.param(
            combine.subtract("close", combine.lag("close", 1)),
            [None, 2, -1, 4, -1, 4],
            id="subtract",
        ),
        pytest.param(
            combine.multiply("close", 2), [20.0, 24.0, 22.0, 30.0, 28.0, 36.0], id="multiply"
        ),
        pytest.param(
            combine.divide("close", combine.subtract("close", 12)),
            [-5.0, None, -11.0, 5.0, 7.0, 3.0],
            id="divide-null-where-the-divisor-is-zero",
        ),
        pytest.param(combine.ratio_to("close", 10), [0.0, 0.2, 0.1, 0.5, 0.4, 0.8], id="ratio_to"),
        pytest.param(
            combine.greater_than("close", 12),
            [False, False, False, True, True, True],
            id="greater_than",
        ),
        pytest.param(
            combine.crosses_above("close", 12),
            [None, False, False, True, False, False],
            id="crosses_above",
        ),
        pytest.param(
            combine.crosses_below("close", 12),
            [None, False, True, False, False, False],
            id="crosses_below",
        ),
        pytest.param(
            combine.and_(combine.greater_than("close", 11), combine.greater_than("volume", 3)),
            [False, False, False, False, True, True],
            id="and",
        ),
        pytest.param(
            combine.or_(combine.greater_than("close", 14), combine.greater_than("volume", 6)),
            [False, False, True, True, True, True],
            id="or",
        ),
        pytest.param(
            combine.not_(combine.greater_than("close", 12)),
            [True, True, True, False, False, False],
            id="not",
        ),
        pytest.param(combine.rolling_mean("close", 3), _windows(3, mean), id="rolling_mean"),
        pytest.param(combine.rolling_std("close", 3), _windows(3, pstdev), id="rolling_std"),
        pytest.param(combine.rolling_min("close", 2), [None, 10, 11, 11, 14, 14], id="rolling_min"),
        pytest.param(combine.rolling_max("close", 2), [None, 12, 12, 15, 15, 18], id="rolling_max"),
        pytest.param(combine.rolling_rank("close", 3), [None, None, 2, 3, 2, 3], id="rolling_rank"),
        pytest.param(
            combine.percent_rank("close", 3), [None, None, 0.5, 1.0, 0.5, 1.0], id="percent_rank"
        ),
        pytest.param(combine.z_score("close", 3), _windows(3, _z_score), id="z_score"),
        pytest.param(combine.lag("close", 2), [None, None, 10, 12, 11, 15], id="lag"),
        pytest.param(
            combine.subtract("volume", combine.lag("volume", 1)),
            [None, -2, 5, -6, 5, -3],
            id="a-volume-that-falls-below-zero",
        ),
        pytest.param(
            ff.indicators.sma(2) - combine.rolling_mean(ff.indicators.sma(2), 2),
            [None, None, 0.25, 0.75, 0.75, 0.75],
            id="python-operators-on-a-feature",
        ),
    ],
)
def test_each_combinator_gives_the_values_worked_out_by_hand(
    term: Operand, expected: list[object]
) -> None:
    values = evaluated(term)["combined"].to_list()

    assert len(values) == len(expected)
    for value, wanted in zip(values, expected, strict=True):
        if isinstance(wanted, float):
            assert value == pytest.approx(wanted, abs=1e-12), (values, expected)
        else:
            assert value == wanted, (values, expected)


def test_the_rsi_stretch_is_the_rsi_less_its_mean_over_ten_bars() -> None:
    # The check notebook's feature: RSI(14) less its mean over ten bars, null through RSI's
    # warm-up and the nine bars of its mean after it; Polars' rolling mean of a frame and of a
    # series may differ in the last bits.
    rsi = ff.indicators.rsi
    stretch = rsi(14) - combine.rolling_mean(rsi(14), 10)

    values = evaluated(stretch, {Grid("ES", FIVE): WAVES}, slots={"rsi": rsi(14)})

    direct = values["rsi"] - values["rsi"].rolling_mean(10)
    assert values["combined"].is_null().equals(direct.is_null())
    assert values["combined"].drop_nulls().len() == 400 - 25 * 14 - 9
    assert values["combined"].drop_nulls().to_list() == pytest.approx(
        direct.drop_nulls().to_list(), abs=1e-12
    )


def test_a_cross_of_two_averages_reads_one_feature_with_two_sets_of_parameters() -> None:
    ema = ff.indicators.ema
    definition = combine.define("ema_cross", combine.crosses_above(ema(9), ema(21)))
    graph = FeatureGraph.of({"cross": definition(), "fast": ema(9), "slow": ema(21)}, "ES", FIVE)

    values = graph.evaluate({graph.signal_grid: WAVES})

    fast, slow = values["fast"], values["slow"]
    direct = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    first = 13 * 21 + 1
    assert 'alias="ema_1"' in definition.code
    assert 'alias="ema_2"' in definition.code
    assert values["cross"][:first].null_count() == first
    assert values["cross"][first:].equals(direct[first:])
    assert values["cross"][first:].any()


@ff.feature(
    inputs=[ff.indicators.sma, TimeframeInput(timeframe="15m")], outputs={"sma_15m": "price"}
)
def sma_15m(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("sma")


def test_a_higher_timeframe_is_a_feature_on_its_bars_seen_from_their_closes() -> None:
    # As a hand-written feature reading SMA(3) on 15-minute bars: the value of a 15-minute bar
    # from its close on, after SMA(3)'s two bars of warm-up, eight 5-minute bars; and inside a
    # combination, a feature of its own that the combination reads.
    sma = ff.indicators.sma
    five = bars(list(range(100, 112)))
    frames = {Grid("ES", FIVE): five, Grid("ES", FIFTEEN): bars([102, 105, 108, 111], 15)}
    graph = FeatureGraph.of({"sma_15m": sma_15m(), "sma": sma(3)}, "ES", FIVE)

    alone = evaluated(combine.at_timeframe(sma(3), "15m"), frames)["combined"]
    inside = combine.define(
        "from_hourly", combine.subtract("close", combine.at_timeframe(sma(3), "15m"))
    )
    read = FeatureGraph.of({"inside": inside()}, "ES", FIVE).evaluate(frames)["inside"]

    assert alone.to_list() == [None] * 8 + [105.0, 105.0, 105.0, 108.0]
    assert alone.equals(graph.evaluate(frames)["sma_15m"])
    assert read.to_list() == [None] * 8 + [3.0, 4.0, 5.0, 3.0]
    assert 'name="from_hourly_at_15m"' in inside.code


def test_a_spread_across_instruments_reads_the_other_close_as_of_each_close() -> None:
    # NQ's first bar closes at 10 minutes and none closes at 20, so ES's row of 20 minutes reads
    # NQ's bar of 15, and its first row reads none.
    es = bars([100, 101, 102, 103, 104])
    nq = bars([200, 201, 202, 203], start=5).filter(pl.col("ts_close") != 20 * MINUTE)
    spread = combine.subtract("close", combine.column("close", instrument="NQ"))

    values = evaluated(spread, {Grid("ES", FIVE): es, Grid("NQ", FIVE): nq})["combined"]

    assert values.to_list() == [None, -99, -99, -98, -99]


def test_scaled_by_atr_divides_a_distance_by_the_atr_of_the_bars() -> None:
    step = combine.subtract("close", combine.lag("close", 1))

    values = evaluated(
        combine.scaled_by_atr(step, 2),
        {Grid("ES", FIVE): WAVES},
        slots={"atr": ff.indicators.atr(2)},
    )

    closes, first = WAVES["close"], 25 * 2 + 1
    direct = (closes - closes.shift(1)) / values["atr"]
    assert values["combined"][:first].null_count() == first
    assert values["combined"][first:].to_list() == pytest.approx(direct[first:].to_list())


def test_the_code_of_a_combination_depends_on_its_description_alone() -> None:
    # If it fails: a combination whose code followed the order of its parameters would change
    # its version's hash between runs, so the generator writes them sorted, every default in.
    percent_k = combine.output(ff.indicators.stochastic(14, 3, 3), "percent_k")
    reordered = dict(reversed(list(percent_k.parameters.items())))

    defined = [
        combine.define("stretched_k", combine.subtract(percent_k.model_copy(update=update), 50))
        for update in ({}, {"parameters": reordered}, {"parameters": {"n": 14}})
    ]

    assert list(reordered) != list(percent_k.parameters)
    assert len({each.code for each in defined}) == 1
    assert len({each.hash for each in defined}) == 1


NUMERIC_LEAVES = st.one_of(
    st.sampled_from(["open", "high", "low", "close", "vwap", "volume"]).map(combine.column),
    st.integers(2, 6).map(lambda n: feature_output(ff.indicators.sma(n))),
)
PAIRS = st.sampled_from(["add", "subtract", "multiply", "divide", "ratio_to"])
WINDOWS = st.sampled_from(
    ["rolling_mean", "rolling_std", "rolling_min", "rolling_max", "rolling_rank", "percent_rank"]
)


def _numeric(children: st.SearchStrategy[Term]) -> st.SearchStrategy[Term]:
    numbers = st.integers(-5, 5).map(combine.constant)
    return st.one_of(
        st.builds(
            lambda kind, left, right: getattr(combine, kind)(left, right),
            PAIRS,
            children,
            st.one_of(children, numbers),
        ),
        st.builds(
            lambda kind, of, n: getattr(combine, kind)(of, n), WINDOWS, children, st.integers(2, 5)
        ),
        st.builds(combine.lag, children, st.integers(1, 3)),
        st.builds(combine.at_timeframe, children, st.sampled_from(["15m", "1h"])),
    )


NUMERIC = st.recursive(NUMERIC_LEAVES, _numeric, max_leaves=5)
FLAGS = st.builds(
    lambda kind, left, right: getattr(combine, kind)(left, right),
    st.sampled_from(["greater_than", "crosses_above", "crosses_below"]),
    NUMERIC,
    NUMERIC,
)
DESCRIPTIONS = st.one_of(
    NUMERIC, FLAGS, st.builds(combine.and_, FLAGS, st.builds(combine.not_, FLAGS))
)


@settings(max_examples=60, deadline=None)
@given(DESCRIPTIONS)
def test_a_combination_round_trips_through_the_json_of_its_description_and_its_code(
    description: Term,
) -> None:
    # The step's test: the description's JSON gives the description again, which gives the same
    # code and hash, and the code alone builds the feature again.
    definition = combine.define("drawn", description)
    assert definition.combination is not None

    written = json.dumps(definition.combination.model_dump(mode="json"))
    read = TypeAdapter(Combination).validate_json(written)

    assert read == definition.combination
    assert combine.define("drawn", read).code == definition.code
    assert ff.features.from_source(definition.code).hash == definition.hash


def test_a_combination_versions_as_a_hand_written_feature_does() -> None:
    rsi = ff.indicators.rsi
    stretch = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 10))
    wider = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 20))

    first, again, second = (ff.features.save(each) for each in (stretch, stretch, wider))
    loaded = ff.features.load("rsi_stretch", 1)

    assert (first.version, again.version, second.version) == (1, 1, 2)
    assert (loaded.hash, loaded.code) == (stretch.hash, stretch.code)
    assert loaded.combination == stretch.combination
    assert loaded.outputs == {"rsi_stretch": ff.features.OutputKind.RATIO}
    assert loaded.warmup == 9


UNKNOWN = FeatureOutput(name="gone", hash="0" * 64, parameters={}, output="gone")
"""A feature no process defined."""


@pytest.mark.parametrize(
    ("build", "refusal"),
    [
        pytest.param(
            lambda: combine.subtract(ff.indicators.bollinger(), "close"),
            "Expected a feature of one output, got bollinger with middle, upper, lower,",
            id="several-outputs",
        ),
        pytest.param(lambda: combine.column("clse"), "Input should be 'open'", id="column"),
        pytest.param(
            lambda: combine.rolling_std("close", 1),
            "Expected a rolling_std over two bars at least",
            id="one-bar",
        ),
        pytest.param(
            lambda: combine.constant(float("inf")), "Expected a finite number, got inf", id="inf"
        ),
        pytest.param(
            lambda: combine.define("constants", combine.add(1, 2)),
            "Expected combination constants to read a column of the bars or a feature, got "
            "constants alone.",
            id="constants-alone",
        ),
        pytest.param(
            lambda: combine.define("window", combine.subtract("close", combine.rolling_mean(5, 3))),
            "Expected the rolling_mean of combination window over a column of the bars or a "
            "feature, got constants alone.",
            id="window-of-constants",
        ),
        pytest.param(
            lambda: combine.define(
                "logic", combine.and_("close", combine.greater_than("close", 1))
            ),
            "Expected flags as the terms of and in combination logic, got price, flag.",
            id="logic-of-a-price",
        ),
        pytest.param(
            lambda: combine.define("unknown", combine.add(UNKNOWN, 1)),
            f"Expected the feature gone {'0' * 12} that a combination reads defined in this "
            "process or saved in the library, got neither",
            id="unknown-feature",
        ),
        pytest.param(
            lambda: combine.define("pl", combine.add("close", 1)),
            "Expected a feature named apart from the names its code reads, got pl",
            id="name-of-polars",
        ),
    ],
)
def test_a_description_the_code_cannot_evaluate_is_refused(
    build: Callable[[], object], refusal: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(refusal)):
        build()


def test_a_window_reads_two_bars_at_least_where_one_leaves_no_value() -> None:
    assert Window(kind="lag", of=combine.column("close"), n=1).n == 1
    with pytest.raises(ValueError, match="Expected a z_score over two bars at least"):
        Window(kind="z_score", of=combine.column("close"), n=1)


def test_a_spread_of_raw_closes_is_the_spread_as_quoted() -> None:
    # The code review: a continuous series' close moves each contract by its rolls' gaps, so two
    # instruments' closes differ by the difference of their offsets; their raw closes do not.
    es = bars([100, 101, 102]).with_columns(close=pl.col("close") + 10)
    nq = bars([200, 201, 202]).with_columns(close=pl.col("close") + 50)
    raw = combine.subtract("close_raw", combine.column("close_raw", instrument="NQ"))
    adjusted = combine.subtract("close", combine.column("close", instrument="NQ"))
    frames = {Grid("ES", FIVE): es, Grid("NQ", FIVE): nq}

    assert evaluated(raw, frames)["combined"].to_list() == [-100, -100, -100]
    assert evaluated(adjusted, frames)["combined"].to_list() == [-140, -140, -140]


def test_a_combinations_name_must_be_a_python_identifier() -> None:
    # The code review: the name becomes the function the code defines.
    for name in ("rsi stretch", "class", "2nd"):
        expected = f"Expected a combination's name, a Python identifier, got {name!r}."
        with pytest.raises(ValueError, match=re.escape(expected)):
            combine.define(name, combine.add("close", 1))


def test_a_combination_keeps_its_description_when_its_code_is_built_again() -> None:
    # The code review: building a combination's code again, as from_source does, defines the
    # same hash without a description, which must not drop the one the process keeps.
    stretch = combine.define("kept", combine.rolling_mean("close", 3) - combine.lag("close", 1))

    ff.features.from_source(stretch.code)

    kept = registry.registered(stretch.hash)
    assert kept is not None
    assert kept.combination == stretch.combination


COUNTER = """\
@ff.feature(outputs={"counted": "count"})
def counted(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").cum_count()
"""
"""A feature of a count Polars gives as an unsigned integer, as `bars_since` does."""


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        pytest.param(
            combine.subtract(combine.rolling_rank("close", 3), 3),
            [None, None, -1, 0, -1, 0],
            id="a-rank-less-a-number",
        ),
        pytest.param(
            combine.subtract(combine.greater_than("close", 11), combine.greater_than("volume", 3)),
            [-1, 1, -1, 1, 0, 0],
            id="a-flag-less-a-flag",
        ),
        pytest.param(
            combine.add(combine.greater_than("close", 11), 1),
            [1, 2, 1, 2, 2, 2],
            id="a-flag-and-one",
        ),
    ],
)
def test_arithmetic_of_ranks_and_flags_is_signed(term: Operand, expected: list[object]) -> None:
    # The ponytail review: a rank is an unsigned integer in Polars, whose difference wraps, and
    # Polars subtracts no flags, so both are read as signed integers in arithmetic.
    assert evaluated(term)["combined"].to_list() == expected


def test_a_count_a_feature_gives_is_read_as_a_signed_integer() -> None:
    counter = features_of_cell(COUNTER)["counted"]

    values = evaluated(combine.subtract(counter(), 5))["combined"]

    assert values.to_list() == [-4, -3, -2, -1, 0, 1]


@pytest.mark.parametrize(
    ("term", "kind"),
    [
        pytest.param(combine.subtract("close", "open"), "price_distance", id="price-less-price"),
        pytest.param(
            combine.add("close", combine.subtract("high", "low")), "price", id="price-and-distance"
        ),
        pytest.param(combine.subtract("close", 1_000_000_000), "price", id="price-less-a-number"),
        pytest.param(
            combine.multiply(ff.indicators.atr(14), 2), "price_distance", id="twice-an-atr"
        ),
        pytest.param(combine.divide(ff.indicators.atr(14), 2), "price_distance", id="half-an-atr"),
        pytest.param(combine.divide(2, ff.indicators.atr(14)), "other", id="a-number-over-an-atr"),
        pytest.param(combine.divide("close", ff.indicators.sma(5)), "ratio", id="price-over-price"),
        pytest.param(combine.subtract(100, ff.indicators.rsi(14)), "ratio", id="a-number-less-rsi"),
        pytest.param(combine.add("volume", 1), "count", id="volume-and-one"),
        pytest.param(combine.add("volume", 0.5), "other", id="volume-and-a-half"),
        pytest.param(combine.rolling_mean("volume", 3), "other", id="mean-of-a-count"),
        pytest.param(combine.rolling_std("close", 3), "price_distance", id="deviation-of-a-price"),
        pytest.param(
            combine.rolling_mean(combine.greater_than("close", 1), 3), "ratio", id="share-of-a-flag"
        ),
        pytest.param(combine.add(combine.greater_than("close", 1), 1), "other", id="flag-and-one"),
        pytest.param(combine.lag(combine.greater_than("close", 1), 1), "flag", id="a-flag-before"),
        pytest.param(combine.rolling_rank("close", 3), "count", id="rank"),
        pytest.param(combine.percent_rank("close", 3), "ratio", id="percent-rank"),
        pytest.param(combine.multiply("close", "volume"), "other", id="price-times-volume"),
    ],
)
def test_the_kind_of_a_combination_follows_from_its_terms(term: Operand, kind: str) -> None:
    definition = combine.define("kinded", term)

    assert definition.outputs == {"kinded": ff.features.OutputKind(kind)}
    evaluated(term)


def test_a_term_tested_for_truth_is_refused() -> None:
    # The ponytail review: Python's `and`, `or`, `not`, and a chained comparison test a term
    # for truth, which would drop a condition without a word; Polars refuses it alike.
    rsi = ff.indicators.rsi(14)
    with pytest.raises(TypeError, match=re.escape("write (rsi > 30) & (rsi < 70)")):
        _ = 30 < combine.rolling_mean(rsi, 3) < 70
    with pytest.raises(TypeError, match="tested for truth"):
        bool(combine.greater_than("close", 1))


def test_every_model_of_a_term_is_one_term_of_reads() -> None:
    # The ponytail review: a model added to the union of terms but not to TERMS would be refused.
    assert typing.get_args(Term) == TERMS


def test_terms_compared_with_equals_are_refused_where_they_join_a_combination() -> None:
    # The ponytail review of the Phase 3 exit: `==` and `!=` compare two terms as Python objects
    # and give a bool, which joined a combination as a constant, so a candle closing at its high
    # was false on every bar without a word; a flag the same on every bar is `constant(True)`.
    close, high, opened = combine.column("close"), combine.column("high"), combine.column("open")

    with pytest.raises(ValueError, match="== and != compare terms as Python objects"):
        _ = (close == high) | (close > opened)
    with pytest.raises(ValueError, match="== and != compare terms as Python objects"):
        _ = (close != opened) & (close > opened)
    assert (combine.constant(True) | (close > opened)).left == combine.constant(True)
