"""The feature contract of step 3.1 (`02-engine-and-data.md` §6, D-71): `@ff.feature` makes a
`FeatureDef` of a function, its typed parameters, its declared inputs and outputs, and its
warm-up, whose content hash covers its normalised source, the features it reads, and its
parameter schema; calling it gives a `FeatureSpec`, its parameters validated, which evaluates
over the signal bars and takes a slot of a signal strategy."""

import re
import textwrap

import polars as pl
import pytest
from pydantic import ValidationError

import fefat as ff
from fefat.features import FeatureInput, InstrumentInput, OutputKind
from notebook_runs import features_of_cell, store_with

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature with one parameter, as a notebook cell defines it."""

CHANNEL = """\
@ff.feature(params={"n": 2}, outputs={"upper": "price", "lower": "price"})
def channel(bars: pl.LazyFrame, n: int) -> dict[str, pl.Expr]:
    return {"upper": pl.col("high").rolling_max(n), "lower": pl.col("low").rolling_min(n)}
"""
"""A feature with two outputs."""

BARS = pl.DataFrame(
    {
        "ts_close": [60, 120, 180, 240],
        "high": [11, 12, 13, 14],
        "low": [9, 10, 11, 12],
        "close": [10, 11, 12, 13],
    }
)


def cell(decorator: str, parameters: str = "bars: pl.LazyFrame", before: str = "") -> str:
    """A cell defining the feature `gap` under `decorator`, with `parameters`."""
    return f'{before}{decorator}\ndef gap({parameters}) -> pl.Expr:\n    return pl.col("close")\n'


def test_a_feature_keeps_its_source_parameters_outputs_and_warmup() -> None:
    gap = features_of_cell(GAP)["gap"]

    assert gap.name == "gap"
    assert gap.code == GAP
    assert gap.parameter_schema["properties"] == {
        "n": {"default": 3, "title": "N", "type": "integer"}
    }
    assert gap.outputs == {"gap": OutputKind.PRICE_DISTANCE}
    assert gap.inputs == ()
    assert gap.written_warmup == "lambda n: n"
    assert re.fullmatch("[0-9a-f]{64}", gap.hash)


def test_the_hash_reads_the_text_not_its_file_indentation_or_line_ends() -> None:
    nested = (
        "def define():\n" + textwrap.indent(GAP, "    ") + "    return gap\n\n\ngap = define()\n"
    )
    texts = {
        "first cell": GAP,
        "second cell": GAP,
        "nested cell": nested,
        "spaced cell": GAP.replace("\n", "   \n"),
        "windows cell": GAP.replace("\n", "\r\n"),
    }

    hashes = {features_of_cell(text, filename)["gap"].hash for filename, text in texts.items()}

    assert len(hashes) == 1


def test_a_changed_default_or_one_changed_character_changes_the_hash() -> None:
    first = features_of_cell(GAP)["gap"]
    other_default = features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"]
    other_character = features_of_cell(GAP.replace(" - ", " + "))["gap"]

    assert len({first.hash, other_default.hash, other_character.hash}) == 3


def test_the_hash_covers_the_parameter_schema_beside_the_code() -> None:
    bound = 'DEFAULTS = {"n": 3}\n\n\n' + GAP.replace('params={"n": 3}', "params=DEFAULTS")
    first = features_of_cell(bound)["gap"]
    other = features_of_cell(bound.replace('{"n": 3}', '{"n": 4}', 1))["gap"]

    assert first.code == other.code
    assert first.hash != other.hash


def test_the_hash_covers_the_hashes_of_the_features_it_reads() -> None:
    reader = """\
@ff.feature(params={"n": 3})
def base(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(n)


@ff.feature(inputs=[base])
def reader(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")
"""
    first = features_of_cell(reader)
    second = features_of_cell(reader.replace("rolling_mean", "rolling_max"))

    assert first["reader"].inputs == (FeatureInput(name="base", hash=first["base"].hash),)
    assert first["reader"].code == second["reader"].code
    assert first["reader"].hash != second["reader"].hash


def test_a_feature_without_source_is_refused() -> None:
    namespace = {"ff": ff, "pl": pl}

    with pytest.raises(ValueError, match="Expected the source of feature gap, got none"):
        exec(compile(GAP, "<no source>", "exec"), namespace)


@pytest.mark.parametrize(
    ("source", "refusal"),
    [
        pytest.param(
            cell('@ff.feature(params={"m": 3})', "bars: pl.LazyFrame, n: int"),
            "Expected params to name parameters of feature gap, got m, which its signature lacks.",
            id="unknown-parameter",
        ),
        pytest.param(
            cell("@ff.feature()", "bars: pl.LazyFrame, n"),
            "Expected each parameter of feature gap annotated with its type, got n without one.",
            id="no-annotation",
        ),
        pytest.param(
            cell("@ff.feature()", "bars: pl.LazyFrame, n: int = 3"),
            "Expected the defaults of feature gap in params, which its decorator keeps, got "
            "n: int = 3 in its signature.",
            id="default-in-the-signature",
        ),
        pytest.param(
            cell("@ff.feature()", "bars: pl.LazyFrame, *n: int"),
            "Expected the parameters of feature gap by name, got *n: int.",
            id="parameters-not-by-name",
        ),
        pytest.param(
            cell('@ff.feature(params={"n": "3"})', "bars: pl.LazyFrame, n: int"),
            "Expected the default of n of feature gap as int, got '3': Input should be a valid "
            "integer.",
            id="default-of-another-type",
        ),
        pytest.param(
            cell('@ff.feature(params={"cap": float("inf")})', "bars: pl.LazyFrame, cap: float"),
            "Expected defaults of feature gap that JSON can write",
            id="default-not-finite",
        ),
        pytest.param(
            cell(
                '@ff.feature(params={"n": 3}, warmup=WARMUP)', "bars: pl.LazyFrame, n: int"
            ).replace("@ff", "WARMUP = lambda n: n\n\n\n@ff", 1),
            "Expected the warm-up of feature gap written in its decorator, as a number of bars "
            "or a lambda of its parameters, got WARMUP.",
            id="warmup-from-elsewhere",
        ),
        pytest.param(
            cell('@ff.feature(params={"n": 3}, warmup=lambda m: m)', "bars: pl.LazyFrame, n: int"),
            "Expected the warm-up of feature gap to read its parameters (n), got m.",
            id="warmup-of-another-parameter",
        ),
        pytest.param(
            cell("@ff.feature(warmup=2.5)"),
            "Expected the warm-up of feature gap as a whole number of bars, at least 0, or a "
            "lambda of its parameters, got 2.5.",
            id="warmup-not-whole",
        ),
        pytest.param(
            cell('@ff.feature(outputs={"gap": "level"})'),
            "Expected the kinds of the outputs of feature gap among price, price_distance, "
            "ratio, count, flag, other, got {'gap': 'level'}.",
            id="unknown-kind",
        ),
        pytest.param(
            cell('@ff.feature(outputs={"close": "price"})'),
            "Expected outputs of feature gap, at least one, named apart from ts_close, warmup, "
            "and the bars' columns, got close.",
            id="output-named-a-bar-column",
        ),
        pytest.param(
            cell("@ff.feature(outputs={})"),
            "Expected outputs of feature gap, at least one, named apart from ts_close, warmup, "
            "and the bars' columns, got none.",
            id="no-output",
        ),
        pytest.param(
            cell("@ff.feature(outputs=KINDS)", before='KINDS = {"gap": "price"}\n\n\n'),
            "Expected the outputs of feature gap written in its decorator as a mapping of names "
            'to kinds, such as {"rsi": "ratio"}, got KINDS.',
            id="outputs-from-elsewhere",
        ),
        pytest.param(
            cell('@ff.feature(inputs=["MNQ"])'),
            "Expected each input of feature gap as a feature or one of FeatureInput, "
            "InstrumentInput, TimeframeInput, DatasetInput, got 'MNQ'.",
            id="input-of-no-kind",
        ),
        pytest.param(
            cell(
                "@ff.feature(inputs=[HIGHER])",
                before='HIGHER = ff.features.TimeframeInput(timeframe="15m")\n\n\n',
            ),
            "Expected each input of feature gap other than a feature written in its decorator "
            'with literal values, such as InstrumentInput(root="MNQ"), got '
            "(TimeframeInput(kind='timeframe', timeframe='15m'),) where it writes a name.",
            id="input-from-elsewhere",
        ),
        pytest.param(
            cell(
                "@ff.feature(inputs=[ff.features.InstrumentInput(root=ROOT)])",
                before='ROOT = "MNQ"\n',
            ),
            "Expected each input of feature gap written in its decorator, a feature by its name "
            'or an input with literal values such as InstrumentInput(root="MNQ"), got '
            "ff.features.InstrumentInput(root=ROOT).",
            id="input-of-a-value-from-elsewhere",
        ),
        pytest.param(
            cell("@ff.feature(inputs=INPUTS)", before="INPUTS = []\n\n\n"),
            "Expected the inputs of feature gap written in its decorator as a list, got INPUTS.",
            id="inputs-from-elsewhere",
        ),
        pytest.param(
            cell('@ff.feature(**{"params": {"n": 3}})', "bars: pl.LazyFrame, n: int"),
            "Expected the declarations of feature gap written in its decorator by name, got "
            "ff.feature(**{'params': {'n': 3}}).",
            id="declarations-unpacked",
        ),
        pytest.param(
            'def gap(bars: pl.LazyFrame) -> pl.Expr:\n    return pl.col("close")\n\n\n'
            "gap = ff.feature()(gap)\n",
            "Expected feature gap defined with def under its decorator, @ff.feature(...), whose "
            "declarations its version keeps, got a function without it.",
            id="no-decorator",
        ),
    ],
)
def test_a_declaration_its_version_could_not_keep_is_refused(source: str, refusal: str) -> None:
    with pytest.raises(ValueError, match=re.escape(refusal)):
        features_of_cell(source)


def test_calling_a_feature_binds_its_parameters_and_their_warmup() -> None:
    gap = features_of_cell(GAP)["gap"]

    assert dict(gap().parameters) == {"n": 3}
    assert gap().warmup == 3
    assert dict(gap(n=7).parameters) == {"n": 7}
    assert gap(n=7).warmup == 7


@pytest.mark.parametrize(
    ("parameters", "refusal"),
    [
        ({"n": "14"}, "got n='14': Input should be a valid integer."),
        ({"n": 14.5}, "got n=14.5: Input should be a valid integer."),
        ({"n": True}, "got n=True: Input should be a valid integer."),
        ({"k": 3}, "got k=3: Extra inputs are not permitted."),
    ],
)
def test_parameters_of_a_wrong_type_are_refused_with_a_readable_message(
    parameters: dict[str, object], refusal: str
) -> None:
    gap = features_of_cell(GAP)["gap"]
    expected = f"Expected the parameters of feature gap as {{n: int}}, {refusal}"

    with pytest.raises(ValueError, match=re.escape(expected)):
        gap(**parameters)


def test_a_parameter_without_a_default_is_required() -> None:
    gap = features_of_cell(cell("@ff.feature()", "bars: pl.LazyFrame, n: int"))["gap"]
    expected = "Expected the parameters of feature gap as {n: int}, got no n: Field required."

    with pytest.raises(ValueError, match=re.escape(expected)):
        gap()
    assert dict(gap(n=5).parameters) == {"n": 5}


def test_a_warmup_that_gives_no_whole_number_of_bars_is_refused() -> None:
    gap = features_of_cell(GAP.replace("lambda n: n", "lambda n: n / 2"))["gap"]
    expected = (
        "Expected the warm-up of feature gap as a whole number of bars, at least 0, got 1.5 "
        "from lambda n: n / 2"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        gap(n=3)


def test_a_feature_evaluates_on_the_bars_rows_with_its_warmup_flagged() -> None:
    frame = features_of_cell(GAP)["gap"](n=2).evaluate(BARS).collect()

    assert frame.columns == ["ts_close", "gap", "warmup"]
    assert frame["ts_close"].to_list() == BARS["ts_close"].to_list()
    assert frame["gap"].to_list() == [None, 0.5, 0.5, 0.5]
    assert frame["warmup"].to_list() == [True, True, False, False]


def test_a_nan_that_arithmetic_gives_is_null() -> None:
    source = """\
@ff.feature()
def no_change(bars: pl.LazyFrame) -> pl.Expr:
    change = pl.col("close") - pl.col("close")
    return change / change
"""
    frame = features_of_cell(source)["no_change"]().evaluate(BARS).collect()

    assert frame.schema["no_change"] == pl.Float64
    assert frame["no_change"].to_list() == [None, None, None, None]


def test_an_output_is_named_after_its_feature_and_of_kind_other_by_default() -> None:
    gap = features_of_cell(cell("@ff.feature()"))["gap"]

    assert gap.outputs == {"gap": OutputKind.OTHER}
    assert gap().evaluate(BARS).collect().columns == ["ts_close", "gap", "warmup"]


@pytest.mark.parametrize(
    ("kind", "expression", "column"),
    [
        ("flag", 'pl.col("close") * 1.0', "Float64"),
        ("count", 'pl.col("close") * 1.0', "Float64"),
        ("price", 'pl.col("close") > 0', "Boolean"),
        ("other", 'pl.col("close").cast(pl.String)', "String"),
    ],
)
def test_an_output_of_a_column_its_kind_does_not_admit_is_refused(
    kind: str, expression: str, column: str
) -> None:
    source = (
        f'@ff.feature(outputs={{"value": "{kind}"}})\n'
        f"def value(bars: pl.LazyFrame) -> pl.Expr:\n    return {expression}\n"
    )
    spec = features_of_cell(source)["value"]()
    expected = (
        f"Expected the output value of feature value, a {kind}, as "
        f"{OutputKind(kind).columns_text}, got a column of {column}."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        spec.expressions(BARS)


def test_several_outputs_evaluate_from_a_mapping() -> None:
    frame = features_of_cell(CHANNEL)["channel"]().evaluate(BARS).collect()

    assert frame.columns == ["ts_close", "upper", "lower", "warmup"]
    assert frame["upper"].to_list() == [None, 12, 13, 14]
    assert frame["lower"].to_list() == [None, 9, 10, 11]


def test_a_return_that_misses_an_output_is_refused() -> None:
    lopsided = CHANNEL.replace(', "lower": pl.col("low").rolling_min(n)', "")
    channel = features_of_cell(lopsided)["channel"]
    expected = (
        "Expected feature channel to return a mapping of its outputs upper, lower to "
        "expressions, got a mapping of upper."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        channel().expressions(BARS)


def test_a_feature_that_reads_other_inputs_waits_for_the_runtime_of_step_3_2() -> None:
    source = cell('@ff.feature(inputs=[ff.features.InstrumentInput(root="MNQ")])')
    spec = features_of_cell(source)["gap"]()

    assert spec.definition.inputs == (InstrumentInput(root="MNQ"),)
    with pytest.raises(ValueError, match=re.escape("waits for the runtime of step 3.2")):
        spec.expressions(BARS)


def test_bars_that_are_not_one_series_are_refused() -> None:
    """Contracts stacked as `load(continuous=False)` gives them: the second contract's first
    rows would read the first contract's last close, a later bar, as the bar before."""
    stacked = pl.concat([BARS, BARS])
    expected = "Expected the bars of feature gap as one series, their closes strictly increasing"

    with pytest.raises(ValueError, match=re.escape(expected)):
        features_of_cell(GAP)["gap"]().evaluate(stacked)


def test_a_back_adjusted_import_is_refused() -> None:
    adjusted = BARS.with_columns(close_raw=pl.lit(None, dtype=pl.Int64))

    with pytest.raises(ValueError, match=re.escape("got a back-adjusted import")):
        features_of_cell(GAP)["gap"]().evaluate(adjusted)


def test_a_column_the_bars_lack_is_refused_naming_the_feature() -> None:
    source = cell("@ff.feature()").replace('pl.col("close")', 'pl.col("vwap")')
    expected = (
        "Expected the expressions of feature gap to evaluate over the bars, got: unable to find "
        'column "vwap"'
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        features_of_cell(source)["gap"]().evaluate(BARS)


def strategy(features: dict[str, object]) -> ff.SignalStrategy:
    """A strategy of ES's 5-minute bars with `features`, which never enters."""
    return ff.SignalStrategy.model_validate(
        {
            "instrument": "ES",
            "timeframe": "5m",
            "features": features,
            "long_entry": pl.lit(False),
            "short_entry": pl.lit(False),
            "execution": ff.Execution(
                entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)
            ),
        }
    )


def test_a_feature_takes_a_slot_of_a_signal_strategy_beside_an_expression() -> None:
    """A feature's slot holds its one output, null on the rows of its declared warm-up, a value
    it cannot give yet; an expression after it reads it as it reads the bars."""
    store_with("ohlcv-1m")
    gap = features_of_cell(GAP)["gap"]
    features = {"gap": gap(n=3), "doubled": pl.col("gap") * 2}
    bars = ff.market.load("ES", "5m", "2026-03-05", "2026-03-06")

    signals = strategy(features).signals(bars).collect()

    warmed = pl.int_range(pl.len()) >= 3
    gap_by_hand = pl.col("close") - pl.col("close").rolling_mean(3)
    by_hand = bars.select(gap=pl.when(warmed).then(gap_by_hand)).collect()["gap"]
    assert signals.schema["gap"] == pl.Float64
    assert signals["gap"].equals(by_hand)
    assert signals["gap"].null_count() == 3
    assert signals["doubled"].equals((by_hand * 2).alias("doubled"))


def test_a_feature_in_a_slot_reads_the_bars_alone() -> None:
    """What else a feature reads it declares, for the runtime of step 3.2 to evaluate, so an
    earlier slot's column is not one of its inputs."""
    store_with("ohlcv-1m")
    source = cell("@ff.feature()").replace('pl.col("close")', 'pl.col("close") > pl.col("mean")')
    features = {"mean": pl.col("close").rolling_mean(3), "gap": features_of_cell(source)["gap"]()}
    bars = ff.market.load("ES", "5m", "2026-03-05", "2026-03-06")
    expected = 'Expected the expressions of feature gap to evaluate over the bars, got: unable to find column "mean"'

    with pytest.raises(ValueError, match=re.escape(expected)):
        strategy(features).signals(bars)


def test_a_feature_of_several_outputs_waits_for_step_3_2_in_a_strategy_slot() -> None:
    store_with("ohlcv-1m")
    channel = features_of_cell(CHANNEL)["channel"]
    bars = ff.market.load("ES", "5m", "2026-03-05", "2026-03-06")

    with pytest.raises(ValueError, match=re.escape("several outputs wait for the runtime")):
        strategy({"channel": channel()}).signals(bars)


def test_a_mapping_in_a_strategy_slot_is_refused() -> None:
    gap = features_of_cell(GAP)["gap"]
    lookalike = {"definition": gap, "parameters": gap().parameters, "warmup": 3}

    with pytest.raises(ValidationError, match="instance of FeatureSpec"):
        strategy({"gap": lookalike})
