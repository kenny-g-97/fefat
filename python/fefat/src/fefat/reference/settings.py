"""The settings a run fills under, which every run records (`docs/spec/fill-semantics.md` §2):
the latency (F-ACT-01), the slippage ticks per order class (F-SLP-01), and when limits fill
(F-LMT-01, F-LMT-02). A fill scenario may state its own; left out, the specification's
defaults apply (D-51)."""

from enum import StrEnum
from typing import Self

from pydantic import Field

from fefat.market.fidelity import TickFidelity
from fefat.market.schema import FrozenModel, Timeframe

DEFAULT_LATENCY_MS = 100
"""How long after the decision that placed it an order becomes active (F-ACT-01, D-51)."""


class LimitFill(StrEnum):
    """When a limit fills: once the market trades through its price (F-LMT-01, the default)
    or once it touches it (F-LMT-02)."""

    THROUGH = "through"
    TOUCH = "touch"


class SlippageTicks(FrozenModel):
    """Ticks by which market and stop-market fills are worse than their reference (F-SLP-01)."""

    market: int = Field(ge=0)
    stop: int = Field(ge=0)


def default_slippage_ticks(fidelity: object) -> SlippageTicks:
    """The specification's ticks on a fidelity, or its text: none on TBBO, which fills at the
    quote, and one on every other (F-SLP-01, D-51)."""
    ticks = 0 if fidelity == TickFidelity.TBBO else 1
    return SlippageTicks(market=ticks, stop=ticks)


class RunSettings(FrozenModel):
    """The run settings of F-ACT-01, F-SLP-01, F-LMT-01, and F-LMT-02."""

    latency_ms: int = Field(default=DEFAULT_LATENCY_MS, ge=0)
    slippage_ticks: SlippageTicks
    limit_fill: LimitFill = LimitFill.THROUGH

    @classmethod
    def for_fidelity(cls, fidelity: TickFidelity | Timeframe) -> Self:
        """The specification's defaults on `fidelity`."""
        return cls(slippage_ticks=default_slippage_ticks(fidelity))

    def latency_nanoseconds(self) -> int:
        return self.latency_ms * 1_000_000
