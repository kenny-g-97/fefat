"""A saved run's reproduction as the app keeps it (step 5.10, D-126): the `reproduce` job's
result, which says whether the run made again from its pinned version and data
(`ff.backtest.reproduce`) gave the saved run's trades, by their tables' hashes, or why it could not
be made again, in words that name no folder of this PC (D-80). A reproduction whose trades differ
is kept in FEFAT's cache folder, which the result names in words alone."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from fefat.backtest.record import Hash

REPRODUCTIONS_FOLDER = "reproductions"
"""The folder of FEFAT's cache that holds each run's latest reproduction, by its run key, while
its trades differ from the run's."""


class ReproductionVerdict(StrEnum):
    """How a reproduction ended: its trades the saved run's, other trades, or refused before the
    engine ran, since something the run read changed since it was saved."""

    MATCHED = "matched"
    DIFFERED = "differed"
    REFUSED = "refused"


class ReproductionMatched(BaseModel):
    """A reproduction whose trades table hashes as the saved run's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[ReproductionVerdict.MATCHED] = ReproductionVerdict.MATCHED
    trades_hash: Hash


class ReproductionDiffered(BaseModel):
    """A reproduction whose trades table hashes otherwise than the saved run's: something the run
    read is not pinned; its folder is kept in FEFAT's cache folder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[ReproductionVerdict.DIFFERED] = ReproductionVerdict.DIFFERED
    saved_trades_hash: Hash
    reproduced_trades_hash: Hash


class ReproductionRefused(BaseModel):
    """A reproduction refused before the engine ran, with why, as the SDK says it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal[ReproductionVerdict.REFUSED] = ReproductionVerdict.REFUSED
    reason: str


type Reproduction = Annotated[
    ReproductionMatched | ReproductionDiffered | ReproductionRefused,
    Field(discriminator="verdict"),
]
"""A reproduction's end, told apart by its `verdict`."""
