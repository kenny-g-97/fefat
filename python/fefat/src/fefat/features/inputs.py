"""What a feature gives and what it reads beside its bars (`02-engine-and-data.md` §6, D-71): the
kinds of its outputs, and the inputs it may declare, which the runtime of step 3.2 evaluates."""

from enum import StrEnum
from typing import Annotated, Literal

import polars as pl
from pydantic import AfterValidator, Field, JsonValue

from fefat.market.schema import FrozenModel, Timeframe


class OutputKind(StrEnum):
    """What an output's values are (D-71), which its column must admit and its version keeps; the
    leak detector compares values by their column's type. A `price` (a level, such as a moving
    average) and a `price_distance` (such as an ATR) are in the bars' 1e-9 units, the units in
    which the execution template reads them (F-RND-01, D-60), never in points."""

    PRICE = "price"
    PRICE_DISTANCE = "price_distance"
    RATIO = "ratio"
    COUNT = "count"
    FLAG = "flag"
    OTHER = "other"

    def admits(self, dtype: pl.DataType) -> bool:
        """Whether an output of this kind may be a column of `dtype` (`columns_text`)."""
        if self is OutputKind.FLAG:
            return dtype == pl.Boolean
        if self is OutputKind.COUNT:
            return dtype.is_integer()
        numeric = dtype.is_float() or dtype.is_integer()
        return numeric or (self is OutputKind.OTHER and dtype == pl.Boolean)

    @property
    def columns_text(self) -> str:
        """The columns an output of this kind may be, in words."""
        if self is OutputKind.FLAG:
            return "a Boolean column"
        if self is OutputKind.COUNT:
            return "an integer column"
        if self is OutputKind.OTHER:
            return "a float, integer, or Boolean column"
        return "a float or integer column"


def _timeframe_text(text: str) -> str:
    """`text` once it reads as a timeframe, such as `15m`."""
    Timeframe.parse(text)
    return text


class FeatureInput(FrozenModel):
    """Another feature the feature reads, by its name and its content hash; with the
    `parameters` it reads it with, where its reader binds them, as a combination does, else those
    of the slot given for it, or its defaults; and under the columns of an `alias`, as a slot's,
    where its reader names one, else under its outputs' names (step 3.7)."""

    kind: Literal["feature"] = "feature"
    name: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, JsonValue] | None = None
    alias: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class InstrumentInput(FrozenModel):
    """Another instrument's signal bars at the feature's timeframe, such as MNQ's for a feature
    of MES, each column suffixed with its root, as `close_MNQ`, with `staleness_MNQ`, the
    nanoseconds from that bar's close, joined as of each row's close (step 3.2)."""

    kind: Literal["instrument"] = "instrument"
    root: str = Field(min_length=1)


class TimeframeInput(FrozenModel):
    """The timeframe of the bars the feature is evaluated on, such as `15m` for a feature that a
    strategy of 5-minute bars reads, which sees each value from its bar's close (step 3.2)."""

    kind: Literal["timeframe"] = "timeframe"
    timeframe: Annotated[str, AfterValidator(_timeframe_text)]


class DatasetInput(FrozenModel):
    """A dataset of alternative data by its name, reserved for Phase 10."""

    kind: Literal["dataset"] = "dataset"
    name: str = Field(min_length=1)


class TradesInput(FrozenModel):
    """The instrument's prints of each bucket of the feature's bars by aggressor side, available
    at the bucket's close, as `buy_volume`, `sell_volume`, and `unknown_side_volume`, null where
    no prints are in hand (step 3.6, `fefat.market.aggressor`), as cumulative delta reads them."""

    kind: Literal["trades"] = "trades"


DeclaredInput = Annotated[
    FeatureInput | InstrumentInput | TimeframeInput | DatasetInput | TradesInput,
    Field(discriminator="kind"),
]
"""An input a feature declares beside its bars, which every feature reads first."""
