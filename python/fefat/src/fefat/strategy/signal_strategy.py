"""Signal strategies (`02-engine-and-data.md` §2.1 and §5, D-53): features and signals written as
Polars expressions over the signal bars, `load`'s frame, and an execution template written as a
`StrategySpec`. A feature's slot takes a plain expression, such as
`pl.col("close").ewm_mean(span=20)`, or a feature with its parameters, a `FeatureSpec` such as
`rsi(n=14)` (`fefat.features`, step 3.1), which the feature runtime evaluates with what it reads
(`fefat.features.runtime`, step 3.2), a column for each of its outputs:

    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={
            "mean": pl.col("close").rolling_mean(20),
            "rsi": rsi(n=14),
        },
        long_entry=pl.col("close") > pl.col("mean"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(), stop=ff.Stop(ticks=12), targets=[ff.Target(ticks=24)], sizing=ff.Fixed(1)
        ),
    )
    strategy.to_spec().document_json()  # the document the builder, the SDK, and the engine share
    strategy.signals(ff.market.load("ES", "5m", "2026-03-05", "2026-03-09"))  # its signal frame
"""

from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Annotated

import polars as pl
from pydantic import AfterValidator, ConfigDict, Field, InstanceOf, field_validator

from fefat.features.evaluation import FeatureSpec
from fefat.features.runtime import NO_INPUTS, FeatureGraph, InputBars, clashing, slot_columns
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import counted, utc_text
from fefat.market.schema import FrozenModel, Timeframe
from fefat.strategy.signal_frame import (
    OPTIONAL_SIGNAL_COLUMNS,
    PRICE_COLUMNS,
    REQUIRED_SIGNAL_COLUMNS,
    require_column_types,
    require_one_entry_per_bar,
    validated_signal_frame,
)
from fefat.strategy.spec import Execution, InstrumentRoot, MarketEntry, StrategySpec, TimeframeText

_CARRIED_COLUMNS = ("ts_close", "trade_date", "contract", "adj_offset")
_BAR_COLUMNS_READ = pl.Schema(
    {
        "ts_close": pl.Int64,
        "trade_date": pl.Date,
        "contract": pl.String,
        "close_raw": pl.Int64,
        "adj_offset": pl.Int64,
    }
)


def _read_only(
    features: Mapping[str, pl.Expr | FeatureSpec],
) -> Mapping[str, pl.Expr | FeatureSpec]:
    """The features as a mapping no one can change after the strategy is built."""
    return MappingProxyType(dict(features))


class SignalStrategy(FrozenModel):
    """A signal strategy on `instrument`, deciding at the closes of its `timeframe` bars: its
    `features` (each expression evaluated in turn over the bars and the features before it, and
    the `FeatureSpec`s by the feature runtime over the bars and what they declare, each output a
    column, null in its warm-up), its signals,
    the optional columns its execution template reads (`entry_price`, `stop_price`,
    `target_price`, and `trail_ref` in 1e-9 units of the bars' prices, `size_mult`, and `wake`),
    and the `execution` template itself."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    instrument: InstrumentRoot
    timeframe: TimeframeText
    features: Annotated[
        Mapping[str, pl.Expr | InstanceOf[FeatureSpec]], AfterValidator(_read_only)
    ] = Field(default_factory=lambda: MappingProxyType({}))
    long_entry: pl.Expr
    short_entry: pl.Expr
    long_exit: pl.Expr = Field(default_factory=lambda: pl.lit(False))
    short_exit: pl.Expr = Field(default_factory=lambda: pl.lit(False))
    entry_price: pl.Expr | None = None
    stop_price: pl.Expr | None = None
    target_price: pl.Expr | None = None
    trail_ref: pl.Expr | None = None
    size_mult: pl.Expr | None = None
    wake: pl.Expr | None = None
    execution: Execution

    @field_validator("features")
    @classmethod
    def _features_named_apart(
        cls, features: Mapping[str, pl.Expr | FeatureSpec]
    ) -> Mapping[str, pl.Expr | FeatureSpec]:
        frame_columns = {*SIGNAL_BAR_COLUMNS, *REQUIRED_SIGNAL_COLUMNS, *OPTIONAL_SIGNAL_COLUMNS}
        columns = [
            column for name, feature in features.items() for column in _columns(name, feature)
        ]
        taken = clashing(columns, frame_columns)
        if taken:
            raise ValueError(
                "Expected feature names apart from the bars' and the signal frame's columns and "
                f"from each other's, got {', '.join(taken)}."
            )
        return features

    def feature_columns(self) -> tuple[str, ...]:
        """The signal frame's columns of the features, in their slots' order: an expression's
        slot, and a column for each output of a `FeatureSpec` (`slot_columns`)."""
        return tuple(
            column for name, feature in self.features.items() for column in _columns(name, feature)
        )

    def feature_graph(self) -> FeatureGraph:
        """The graph of the strategy's `FeatureSpec`s on its signal grid, which the feature
        runtime evaluates (`fefat.features.runtime`)."""
        specs = {
            name: feature
            for name, feature in self.features.items()
            if isinstance(feature, FeatureSpec)
        }
        return FeatureGraph.of(specs, self.instrument, Timeframe.parse(self.timeframe))

    def to_spec(self) -> StrategySpec:
        """The strategy's specification: the document the builder, the SDK, and the engine share."""
        return StrategySpec(
            spec_version=1,
            instrument=self.instrument,
            timeframe=self.timeframe,
            execution=self.execution,
        )

    def signals(
        self,
        bars: pl.DataFrame | pl.LazyFrame,
        inputs: InputBars = NO_INPUTS,
        *,
        start: date | None = None,
    ) -> pl.LazyFrame:
        """The signal frame of `bars`, `load`'s frame of the strategy's signal bars
        (`fefat.strategy.signal_frame`), its `FeatureSpec`s reading the bars of the other grids
        they declare in `inputs` (`fefat.features.runtime.load_inputs`), and its rows those of
        the trade dates from `start` on, where it is given, the bars before it read for the
        features' warm-up, which the expressions read too, so that an expression's first values
        in the window follow the warm-up the strategy's `FeatureSpec`s need. A null signal, as where a feature has no value yet, is no signal, and a
        null `wake` wakes; each price column becomes raw prices of its row's contract, its values
        less the row's `adj_offset` (D-09). A back-adjusted import (D-49), a price that is not a
        whole number of units, and, with a market entry, a bar with both entry signals are
        refused, and the frame is checked as the engine reads it (`validated_signal_frame`)."""
        frame = signal_bars = _with_raw_prices(bars.lazy().collect())
        graph = self.feature_graph()
        computed = graph.evaluate({**inputs, graph.signal_grid: signal_bars})
        for name, feature in self.features.items():
            frame = frame.with_columns(_feature_columns(computed, name, feature))
        signal_columns = self._signal_columns()
        frame = frame.with_columns(**signal_columns)
        if start is not None:
            frame = frame.filter(pl.col("trade_date") >= start)
        prices = [name for name in PRICE_COLUMNS if name in signal_columns]
        frame = frame.with_columns(_raw_price(frame, name) for name in prices)
        signal_frame = frame.select(*_CARRIED_COLUMNS, *self.feature_columns(), *signal_columns)
        if isinstance(self.execution.entry, MarketEntry):
            require_one_entry_per_bar(signal_frame)
        return validated_signal_frame(signal_frame).lazy()

    def _signal_columns(self) -> dict[str, pl.Expr]:
        """The signal frame's own columns, in its order, as expressions over the bars and the
        features: a null signal is false, a null `wake` true, and `size_mult` a float."""
        optional = {
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "trail_ref": self.trail_ref,
            "size_mult": None if self.size_mult is None else self.size_mult.cast(pl.Float64),
            "wake": None if self.wake is None else self.wake.fill_null(True),
        }
        signals = {
            "long_entry": self.long_entry.fill_null(False),
            "short_entry": self.short_entry.fill_null(False),
            "long_exit": self.long_exit.fill_null(False),
            "short_exit": self.short_exit.fill_null(False),
        }
        return signals | {name: column for name, column in optional.items() if column is not None}


def _columns(name: str, feature: pl.Expr | FeatureSpec) -> list[str]:
    """The columns of the slot `name`: its name for an expression, and a column for each output
    of a `FeatureSpec` (`slot_columns`)."""
    if isinstance(feature, pl.Expr):
        return [name]
    return list(slot_columns(name, feature).values())


def _feature_columns(
    computed: pl.DataFrame, name: str, feature: pl.Expr | FeatureSpec
) -> list[pl.Expr] | list[pl.Series]:
    """The columns of the slot `name`: an expression as it is, over the bars and the features
    before it; and a feature's outputs as the runtime gives them on the signal bars' rows
    (`FeatureGraph.evaluate`), a NaN made null and the rows of its warm-up null, a value it
    cannot give yet (D-71)."""
    if isinstance(feature, pl.Expr):
        return [feature.alias(name)]
    return [computed.get_column(column) for column in slot_columns(name, feature).values()]


def _with_raw_prices(bars: pl.DataFrame) -> pl.DataFrame:
    """`bars` once they hold the columns a signal frame carries and their raw closes: a
    back-adjusted import has none (D-49)."""
    require_column_types(bars, _BAR_COLUMNS_READ, "the signal bars'")
    if bars.get_column("close_raw").null_count() > 0:
        raise ValueError(
            "Expected a series with raw prices, got a back-adjusted import, whose prices no "
            "order traded at (D-49)."
        )
    return bars


def _raw_price(frame: pl.DataFrame, name: str) -> pl.Expr:
    """The price column `name`, in whole 1e-9 units of the bars' prices, as raw prices of each
    row's contract (D-09)."""
    dtype = frame.schema[name]
    if dtype.is_float():
        price = pl.col(name)
        off = frame.filter(~price.is_finite() | (price != price.floor()))
        if not off.is_empty():
            raise ValueError(
                f"Expected {name} in whole 1e-9 units, got {off.item(0, name)} on "
                f"{counted(off.height, 'bar')}, the first closing at "
                f"{utc_text(off.item(0, 'ts_close'))}: round it to the instrument's tick."
            )
    elif not dtype.is_integer():
        raise ValueError(f"Expected {name} as prices in 1e-9 units, got a column of {dtype}.")
    return (pl.col(name).cast(pl.Int64) - pl.col("adj_offset")).alias(name)
