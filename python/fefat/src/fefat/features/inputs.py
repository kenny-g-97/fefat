"""What a feature gives and what it reads beside its bars (`02-engine-and-data.md` §6, D-71): the
kinds of its outputs, and the inputs it may declare, which the runtime of step 3.2 evaluates."""

from enum import StrEnum
from typing import Annotated, Literal

import polars as pl
from pydantic import AfterValidator, Field

from fefat.market.schema import FrozenModel, Timeframe


class OutputKind(StrEnum):
    """What an output's values are (D-71), which the leak detector's tolerance (step 3.4) and the
    golden tests (step 3.5) read. A `price` (a level, such as a moving average) and a
    `price_distance` (such as an ATR) are in the bars' 1e-9 units, the units in which the
    execution template reads them (F-RND-01, D-60), never in points."""

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
    """Another feature the feature reads, by its name and its content hash."""

    kind: Literal["feature"] = "feature"
    name: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class InstrumentInput(FrozenModel):
    """Another instrument's signal bars, such as MNQ's for a feature of MES."""

    kind: Literal["instrument"] = "instrument"
    root: str = Field(min_length=1)


class TimeframeInput(FrozenModel):
    """The bars of a higher timeframe, such as `15m` for a feature of 5-minute bars, each visible
    from its close (step 3.2)."""

    kind: Literal["timeframe"] = "timeframe"
    timeframe: Annotated[str, AfterValidator(_timeframe_text)]


class DatasetInput(FrozenModel):
    """A dataset of alternative data by its name, reserved for Phase 10."""

    kind: Literal["dataset"] = "dataset"
    name: str = Field(min_length=1)


DeclaredInput = Annotated[
    FeatureInput | InstrumentInput | TimeframeInput | DatasetInput, Field(discriminator="kind")
]
"""An input a feature declares beside its bars, which every feature reads first."""
