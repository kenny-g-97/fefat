"""Signal strategies (`02-engine-and-data.md` §2.1 and §5, D-53): features and signals written as
Polars expressions over the signal bars, `load`'s frame, and an execution template written as a
`StrategySpec`. Until `@ff.feature` and `fefat.indicators` arrive in Phase 3, a feature is a plain
expression, such as `pl.col("close").ewm_mean(span=20)`, in the same slot:

    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"mean": pl.col("close").rolling_mean(20)},
        long_entry=pl.col("close") > pl.col("mean"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(), stop=ff.Stop(ticks=12), targets=[ff.Target(ticks=24)], sizing=ff.Fixed(1)
        ),
    )
    strategy.to_spec().document_json()  # the document the builder, the SDK, and the engine share
    strategy.signals(ff.market.load("ES", "5m", "2026-03-05", "2026-03-09"))  # its signal frame
"""

import polars as pl
from pydantic import ConfigDict, Field, field_validator

from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import counted, utc_text
from fefat.market.schema import FrozenModel
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


class SignalStrategy(FrozenModel):
    """A signal strategy on `instrument`, deciding at the closes of its `timeframe` bars: its
    `features` (each evaluated in turn over the bars and the features before it), its signals,
    the optional columns its execution template reads (`entry_price`, `stop_price`,
    `target_price`, and `trail_ref` in 1e-9 units of the bars' prices, `size_mult`, and `wake`),
    and the `execution` template itself."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    instrument: InstrumentRoot
    timeframe: TimeframeText
    features: dict[str, pl.Expr] = Field(default_factory=dict)
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
    def _features_named_apart(cls, features: dict[str, pl.Expr]) -> dict[str, pl.Expr]:
        frame_columns = {*SIGNAL_BAR_COLUMNS, *REQUIRED_SIGNAL_COLUMNS, *OPTIONAL_SIGNAL_COLUMNS}
        taken = sorted(set(features) & frame_columns)
        if taken:
            raise ValueError(
                "Expected feature names apart from the bars' and the signal frame's columns, got "
                f"{', '.join(taken)}."
            )
        return features

    def to_spec(self) -> StrategySpec:
        """The strategy's specification: the document the builder, the SDK, and the engine share."""
        return StrategySpec(
            spec_version=1,
            instrument=self.instrument,
            timeframe=self.timeframe,
            execution=self.execution,
        )

    def signals(self, bars: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
        """The signal frame of `bars`, `load`'s frame of the strategy's signal bars
        (`fefat.strategy.signal_frame`). A null signal, as in a feature's warm-up, is no signal,
        and a null `wake` wakes; each price column becomes raw prices of its row's contract, its
        values less the row's `adj_offset` (D-09). A back-adjusted import (D-49), a price that is
        not a whole number of units, and, with a market entry, a bar with both entry signals are
        refused, and the frame is checked as the engine reads it (`validated_signal_frame`)."""
        frame = _with_raw_prices(bars.lazy().collect())
        for name, feature in self.features.items():
            frame = frame.with_columns(feature.alias(name))
        signal_columns = self._signal_columns()
        frame = frame.with_columns(**signal_columns)
        prices = [name for name in PRICE_COLUMNS if name in signal_columns]
        frame = frame.with_columns(_raw_price(frame, name) for name in prices)
        signal_frame = frame.select(*_CARRIED_COLUMNS, *self.features, *signal_columns)
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
