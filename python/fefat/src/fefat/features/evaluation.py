"""A feature with its parameters bound (step 3.1, D-71): a `FeatureSpec` evaluates over the signal
bars to its outputs, Polars expressions on the bars' rows and so aligned to their `ts_close`, or
to a frame of `ts_close`, its outputs, and its warm-up flag.

    spec = rsi(n=14)
    spec.expressions(bars)  # {"rsi": <expression>}, a NaN that arithmetic gives made null
    spec.evaluate(bars)  # ts_close, rsi, and warmup, true on the first 294 rows

A value a feature cannot give yet is null, never NaN, which `SignalStrategy.signals()` refuses
(D-53); the rows inside the declared warm-up keep the values the feature gives there, flagged:
its whole sessions first, then its bars (`first_warm_row`, D-78).
The bars are one series, as `load` gives a root spliced or one contract, never the contracts
`load(continuous=False)` stacks, and never a back-adjusted import. A feature that reads inputs
beside the bars is evaluated by the runtime of step 3.2 (`fefat.features.runtime`), which gives
`outputs_over` its bars with those inputs joined; and a feature that returns a frame on its
bars' grid, for a join or a group-by, has no expressions, but a frame of values."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from pydantic import BaseModel

from fefat.features.label_columns import refuse_label_columns

if TYPE_CHECKING:
    from fefat.features.definition import FeatureDef


@dataclass(frozen=True)
class FeatureSpec:
    """A feature's definition with its parameters, validated, and the warm-ups they give, in bars
    and in whole sessions."""

    definition: "FeatureDef"
    parameters: BaseModel
    warmup: int
    warmup_sessions: int

    def expressions(self, bars: pl.DataFrame | pl.LazyFrame) -> dict[str, pl.Expr]:
        """The feature's outputs over `bars`, `load`'s signal bars, as expressions named after
        them, each refused unless its column is one its kind admits (`OutputKind`), and a NaN in
        a column of floats made null."""
        definition = self.definition
        _require_the_bars_alone(definition)
        frame = bars.lazy()
        require_one_series_of_raw_prices(frame, f"feature {definition.name}")
        returned = definition.function(frame, **dict(self.parameters))
        if isinstance(returned, pl.DataFrame | pl.LazyFrame):
            raise ValueError(
                f"Expected feature {definition.name} to return expressions over the bars, got a "
                "frame: evaluate it, or compute it with ff.features.compute."
            )
        outputs = _named(definition, returned)
        schema = _schema_of(definition, frame.select(*outputs.values()))
        return {
            output: _without_nan(expression, schema[output]).alias(output)
            for output, expression in outputs.items()
        }

    def outputs_over(self, frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
        """`ts_close` and the feature's outputs over `frame`, its bars with the columns of the
        inputs it declares, as the runtime joins them (`fefat.features.runtime`): what its
        function returns, expressions over the rows or a frame on their grid, each output
        refused unless its column is one its kind admits, and a NaN in a column of floats made
        null."""
        definition = self.definition
        bars = frame.lazy()
        require_one_series_of_raw_prices(bars, f"feature {definition.name}")
        returned = definition.function(bars, **dict(self.parameters))
        values = _values(definition, bars, returned)
        schema = _schema_of(definition, values)
        return values.with_columns(
            _without_nan(pl.col(output), schema[output]) for output in definition.outputs
        )

    def evaluate(self, bars: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
        """The feature over `bars` as a frame on their rows: `ts_close`, its outputs, and
        `warmup`, true on the rows its declared warm-up counts, its sessions then its bars."""
        _require_the_bars_alone(self.definition)
        frame = bars.lazy()
        first = self.warmup
        if self.warmup_sessions:
            held = [name for name in ("ts_close", "trade_date") if name in frame.collect_schema()]
            rows = frame.select(held).collect()
            owner = f"feature {self.definition.name}"
            first = first_warm_row(rows, None, self.warmup_sessions, self.warmup, owner)
        return self.outputs_over(frame).with_columns(warmup=pl.int_range(pl.len()) < first)


def first_warm_row(
    rows: pl.DataFrame, read_from: int | None, sessions: int, bars: int, owner: str
) -> int:
    """The first of `rows`, a feature's bars in order with their `ts_close` and, where `sessions`
    is above 0, their `trade_date`, at which the values of `owner` mean what they say (D-78): from
    the first row closing at or after `read_from`, where the features it reads have their first
    values, or from the first row where None, `sessions` whole sessions on, a session whole where
    its first row lies at or after that row, then `bars` rows on; the number of rows where they
    hold none."""
    start = 0 if read_from is None else int(rows["ts_close"].search_sorted(read_from, "left"))
    if sessions:
        start = _after_whole_sessions(rows, start, sessions, owner)
    return min(start + bars, rows.height)


def _after_whole_sessions(rows: pl.DataFrame, start: int, sessions: int, owner: str) -> int:
    """The first row of the session `sessions` whole sessions after the first that opens at or
    after row `start`; the number of rows where they hold fewer."""
    if "trade_date" not in rows.columns:
        raise ValueError(
            f"Expected trade_date in the bars of {owner}, whose warm-up counts sessions, got none."
        )
    dates = rows.get_column("trade_date")
    opens = (dates != dates.shift(1)).fill_null(True).arg_true()
    whole = opens.filter(opens >= start)
    return int(whole[sessions]) if whole.len() > sessions else rows.height


def _require_the_bars_alone(definition: "FeatureDef") -> None:
    """Refuse a feature that reads inputs beside the bars, which the runtime evaluates."""
    if definition.inputs:
        kinds = ", ".join(declared.kind for declared in definition.inputs)
        raise ValueError(
            f"Expected feature {definition.name} to read the bars alone, got inputs of kind "
            f"{kinds}: compute it with ff.features.compute, which reads them."
        )


def require_one_series_of_raw_prices(bars: pl.LazyFrame, owner: str) -> None:
    """Refuse bars a feature would read across in error, `owner`'s, such as "feature rsi" or
    "MNQ that feature spread reads", since it reads the row above as the bar
    before: bars that are not one series, their closes strictly increasing, such as the contracts
    `load(continuous=False)` stacks, whose next contract's first rows would read the last rows of
    the one before, days later; a back-adjusted import's, whose prices hold the gaps of rolls
    after them (D-09, D-49), as a signal strategy refuses them; and bars that hold a column of
    the labels of `fefat.analytics`, which read the future (`fefat.features.label_columns`)."""
    refuse_label_columns(bars.collect_schema().names(), f"the bars of {owner}")
    checks = {"back": (pl.col("ts_close").diff() <= 0).any()}
    if "close_raw" in bars.collect_schema():
        checks["adjusted"] = pl.col("close_raw").is_null().any()
    found = bars.select(**checks).collect().row(0, named=True)
    if found["back"]:
        raise ValueError(
            f"Expected the bars of {owner} as one series, their closes strictly "
            "increasing, got a close at or before the one above it, as load(continuous=False) "
            "stacks contracts: load the root spliced, or one contract."
        )
    if found.get("adjusted"):
        raise ValueError(
            f"Expected bars with raw closes for {owner}, got a back-adjusted import, whose "
            "prices hold the gaps of rolls after them (D-09, D-49)."
        )


def _values(definition: "FeatureDef", bars: pl.LazyFrame, returned: object) -> pl.LazyFrame:
    """`ts_close` and the outputs the feature returned over `bars`: expressions over their rows,
    or a frame on their grid."""
    if isinstance(returned, pl.DataFrame | pl.LazyFrame):
        return _on_the_grid(definition, bars, returned.lazy())
    return bars.select("ts_close", *_named(definition, returned).values())


def _on_the_grid(
    definition: "FeatureDef", bars: pl.LazyFrame, returned: pl.LazyFrame
) -> pl.LazyFrame:
    """The frame a feature returned, refused unless it holds `ts_close` and each of its outputs
    on its bars' rows, one row for each in their order (BACKLOG.md)."""
    held = _schema_of(definition, returned).names()
    missing = [column for column in ["ts_close", *definition.outputs] if column not in held]
    if missing:
        raise ValueError(
            f"Expected the frame feature {definition.name} returns to hold ts_close and its "
            f"outputs, got none of {', '.join(missing)}."
        )
    closes = bars.select("ts_close").collect().to_series()
    given = returned.select("ts_close").collect().to_series()
    if not given.equals(closes):
        elsewhere = "" if given.len() != closes.len() else " at other closes"
        raise ValueError(
            f"Expected the frame feature {definition.name} returns on the bars' grid of "
            f"{closes.len()} rows, got {given.len()} rows{elsewhere}."
        )
    return returned.select("ts_close", *definition.outputs)


def _schema_of(definition: "FeatureDef", values: pl.LazyFrame) -> pl.Schema:
    """The schema of the feature's values, each output refused unless its column is one its
    kind admits (`OutputKind`); a Polars error names the feature."""
    try:
        schema = values.collect_schema()
    except pl.exceptions.PolarsError as error:
        raise ValueError(
            f"Expected the expressions of feature {definition.name} to evaluate over the bars, "
            f"got: {str(error).splitlines()[0]}"
        ) from error
    for output, kind in definition.outputs.items():
        if output in schema and not kind.admits(schema[output]):
            raise ValueError(
                f"Expected the output {output} of feature {definition.name}, a {kind}, as "
                f"{kind.columns_text}, got a column of {schema[output]}."
            )
    return schema


def _without_nan(expression: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """`expression` with a NaN that arithmetic gives made null, in a column of floats."""
    return expression.fill_nan(None) if dtype.is_float() else expression


def _named(definition: "FeatureDef", returned: object) -> dict[str, pl.Expr]:
    """What the feature's function returned, by output: one expression for its one output, or a
    mapping of its outputs to expressions."""
    names = list(definition.outputs)
    if isinstance(returned, pl.Expr) and len(names) == 1:
        return {names[0]: returned.alias(names[0])}
    if (
        isinstance(returned, Mapping)
        and set(returned) == set(names)
        and all(isinstance(expression, pl.Expr) for expression in returned.values())
    ):
        return {name: returned[name].alias(name) for name in names}
    wanted = (
        f"an expression for its output {names[0]}"
        if len(names) == 1
        else f"a mapping of its outputs {', '.join(names)} to expressions"
    )
    got = (
        f"a mapping of {', '.join(map(str, returned))}"
        if isinstance(returned, Mapping)
        else type(returned).__name__
    )
    raise ValueError(f"Expected feature {definition.name} to return {wanted}, got {got}.")
