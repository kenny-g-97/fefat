"""A feature with its parameters bound (step 3.1, D-71): a `FeatureSpec` evaluates over the signal
bars to its outputs, Polars expressions on the bars' rows and so aligned to their `ts_close`, or
to a frame of `ts_close`, its outputs, and its warm-up flag.

    spec = rsi(n=14)
    spec.expressions(bars)  # {"rsi": <expression>}, a NaN that arithmetic gives made null
    spec.evaluate(bars)  # ts_close, rsi, and warmup, true on the first 140 rows

A value a feature cannot give yet is null, never NaN, which `SignalStrategy.signals()` refuses
(D-53); the rows inside the declared warm-up keep the values the feature gives there, flagged. A
feature that reads inputs beside the bars waits for the runtime of step 3.2."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from pydantic import BaseModel

if TYPE_CHECKING:
    from fefat.features.definition import FeatureDef


@dataclass(frozen=True)
class FeatureSpec:
    """A feature's definition with its parameters, validated, and the warm-up they give in bars."""

    definition: "FeatureDef"
    parameters: BaseModel
    warmup: int

    def expressions(self, bars: pl.DataFrame | pl.LazyFrame) -> dict[str, pl.Expr]:
        """The feature's outputs over `bars`, `load`'s signal bars, as expressions named after
        them, each refused unless its column is one its kind admits (`OutputKind`), and a NaN in
        a column of floats made null."""
        definition = self.definition
        if definition.inputs:
            kinds = ", ".join(declared.kind for declared in definition.inputs)
            raise ValueError(
                f"Expected feature {definition.name} to read the bars alone, got inputs of kind "
                f"{kinds}: a feature that reads other inputs waits for the runtime of step 3.2."
            )
        frame = bars.lazy()
        outputs = _named(definition, definition.function(frame, **dict(self.parameters)))
        schema = frame.select(*outputs.values()).collect_schema()
        for output, kind in definition.outputs.items():
            if not kind.admits(schema[output]):
                raise ValueError(
                    f"Expected the output {output} of feature {definition.name}, a {kind}, as "
                    f"{kind.columns_text}, got a column of {schema[output]}."
                )
        return {
            output: (expression.fill_nan(None) if schema[output].is_float() else expression).alias(
                output
            )
            for output, expression in outputs.items()
        }

    def evaluate(self, bars: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
        """The feature over `bars` as a frame on their rows: `ts_close`, its outputs, and
        `warmup`, true on the rows its declared warm-up counts."""
        return bars.lazy().select(
            "ts_close",
            *self.expressions(bars).values(),
            warmup=pl.int_range(pl.len()) < self.warmup,
        )


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
