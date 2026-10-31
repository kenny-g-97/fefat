"""What each engine does where the fill specification (`docs/spec/fill-semantics.md`) makes a
choice FEFAT's own: when a market order decided at a bar close fills, and in which order a
bar's extremes are visited. The classifier's predicates read these to explain a difference."""

from dataclasses import dataclass
from enum import StrEnum


class MarketFill(StrEnum):
    """Where a market order decided at a 5-minute close fills."""

    AT_DECISION_CLOSE = "at_decision_close"
    """NautilusTrader: an order submitted from `on_bar` settles against the book the bar left,
    at that bar's close, with no latency model (its backtesting documentation)."""

    NEXT_BAR_OPEN = "next_bar_open"
    """FEFAT with no latency: the open of the first bar after the decision (F-MKT-03, F-ACT-02);
    NinjaTrader 8: the open of the bar after the one it was submitted on (the builder's spec, H1)."""


class BarOrder(StrEnum):
    """The order in which a bar's two extremes are visited after its open."""

    ADVERSE_FIRST = "adverse_first"
    """FEFAT holding a position (F-BAR-02): the low for a long, the high for a short."""

    OPEN_HIGH_LOW_CLOSE = "open_high_low_close"
    """NautilusTrader by default: the high first, whatever the position."""

    NEAREST_EXTREME_FIRST = "nearest_extreme_first"
    """NautilusTrader with `bar_adaptive_high_low_ordering`, and NinjaTrader 8 (H2): the extreme
    nearer the open first, the high on a tie."""


class Extreme(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class EngineConventions:
    """One engine's choices, named as the report names the engine."""

    name: str
    market_fill: MarketFill
    bar_order: BarOrder

    def first_extreme(self, open: int, high: int, low: int, long: bool) -> Extreme:
        """The extreme the engine's path visits first after the bar's open, for a position of
        the side given."""
        if self.bar_order == BarOrder.ADVERSE_FIRST:
            return Extreme.LOW if long else Extreme.HIGH
        if self.bar_order == BarOrder.OPEN_HIGH_LOW_CLOSE:
            return Extreme.HIGH
        return Extreme.HIGH if high - open <= open - low else Extreme.LOW


FEFAT = EngineConventions("FEFAT", MarketFill.NEXT_BAR_OPEN, BarOrder.ADVERSE_FIRST)
NAUTILUS_OHLC = EngineConventions(
    "NautilusTrader, open-high-low-close",
    MarketFill.AT_DECISION_CLOSE,
    BarOrder.OPEN_HIGH_LOW_CLOSE,
)
NAUTILUS_ADAPTIVE = EngineConventions(
    "NautilusTrader, nearest extreme first",
    MarketFill.AT_DECISION_CLOSE,
    BarOrder.NEAREST_EXTREME_FIRST,
)
NINJATRADER = EngineConventions(
    "NinjaTrader 8", MarketFill.NEXT_BAR_OPEN, BarOrder.NEAREST_EXTREME_FIRST
)
