"""What each engine does where the fill specification (`docs/spec/fill-semantics.md`) makes a
choice FEFAT's own: when a market order decided at a bar close fills, and in which order a
bar's extremes are visited. The replay (`fefat_xcheck.replay`) reads these to give each engine
its own fills."""

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
    nearer the open first; on a tie, the engine's `tie` extreme."""


class Extreme(StrEnum):
    HIGH = "high"
    LOW = "low"


class LimitGap(StrEnum):
    """Where a resting limit fills when a bar opens past its price in its favour."""

    AT_THE_LIMIT = "at_the_limit"
    """FEFAT (F-LMT-03, never better, and never clamped into the bar's range, F-SLP-01) and
    NautilusTrader (a resting limit uses its price when a market move matches it)."""

    CLAMPED_INTO_THE_BAR = "clamped_into_the_bar"
    """NinjaTrader 8 (H4): the limit's price clamped into the bar's range, so a buy limit above
    the whole bar fills at its high and a sell limit below it at its low."""


@dataclass(frozen=True)
class EngineConventions:
    """One engine's choices, named as the report names the engine."""

    name: str
    market_fill: MarketFill
    bar_order: BarOrder
    tie: Extreme = Extreme.HIGH
    """The extreme visited first when the open lies halfway between them, where the order is
    the nearest extreme first: NinjaTrader 8 takes the high (H2), NautilusTrader the low (a run
    of step 2.14 on a bar whose open sat halfway filled the long's stop)."""
    limit_gap: LimitGap = LimitGap.AT_THE_LIMIT

    def first_extreme(self, open: int, high: int, low: int, long: bool) -> Extreme:
        """The extreme the engine's path visits first after the bar's open, for a position of
        the side given."""
        if self.bar_order == BarOrder.ADVERSE_FIRST:
            return Extreme.LOW if long else Extreme.HIGH
        if self.bar_order == BarOrder.OPEN_HIGH_LOW_CLOSE:
            return Extreme.HIGH
        if high - open == open - low:
            return self.tie
        return Extreme.HIGH if high - open < open - low else Extreme.LOW


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
    tie=Extreme.LOW,
)
NINJATRADER = EngineConventions(
    "NinjaTrader 8",
    MarketFill.NEXT_BAR_OPEN,
    BarOrder.NEAREST_EXTREME_FIRST,
    limit_gap=LimitGap.CLAMPED_INTO_THE_BAR,
)
