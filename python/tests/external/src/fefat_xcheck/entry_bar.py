"""What each engine does on the rest of a bar after an entry fills inside it: the pseudo-ticks it
visits after the fill and the leg of the bracket, stop or target, those ticks fill, at which
price. The classifier compares each engine's observed exit on its entry's bar with this
expectation, so that a difference of the two orders of extremes, or of the price a released leg
takes, is explained only where the bars support it.

FEFAT (`docs/spec/fill-semantics.md`): flat, a bar's first extreme is the one favourable to the
working entry, the high for a buy (F-BAR-03); a limit fills at its price where the path touches
it (F-LMT-02, F-LMT-03) and a stop at its price where the path reaches it, or at the open when
the bar opens through it (F-STP-04); after the fill the extremes not yet reached come adverse
first, then the close (F-BAR-04), the legs working from the entry's point (F-OCO-02); a leg the
path then reaches fills at its level, and a stop already through the market at the fill fills at
once at the entry's point (F-STP-05).

NautilusTrader (its backtesting documentation, and the runs of step 2.14): a bar is four ticks,
the open, the high, the low, and the close, in that order or with the extreme nearer the open
first; the entry fills on the first tick that satisfies it, a limit at its price, a stop at its
trigger price, or at the open's price when the open is through it; its legs are released on that
tick, and a leg whose level that tick's price is already past fills at that price; on the later
ticks a leg fills at its level."""

from dataclasses import dataclass

from fefat_xcheck.conventions import BarOrder, EngineConventions, Extreme

MARKET, LIMIT, STOP, TARGET = "market", "limit", "stop", "target"


@dataclass(frozen=True)
class EntryBar:
    """The bar an entry filled in, with the entry and its bracket."""

    open: int
    high: int
    low: int
    close: int
    long: bool
    entry_kind: str
    entry_price: int
    stop_price: int
    target_price: int

    def favourable(self) -> int:
        return self.high if self.long else self.low

    def adverse(self) -> int:
        return self.low if self.long else self.high


def fefat_exit(bar: EntryBar) -> tuple[str, int] | None:
    """The leg FEFAT's path fills on the rest of the entry's bar and its price, or None when the
    position leaves the bar open."""
    remaining = _fefat_points_after_the_entry(bar)
    if remaining is None:
        return None
    if _stop_through_the_market(bar):
        return STOP, bar.entry_price
    return _first_leg_crossed(bar, bar.entry_price, remaining)


def _fefat_points_after_the_entry(bar: EntryBar) -> list[int] | None:
    """The points of the path after the entry's fill: none reached when it filled at the open,
    the favourable extreme reached when a limit filled on the way to the adverse one, and both
    still ahead when a stop filled on the way to the favourable one (F-BAR-04)."""
    if bar.entry_kind == LIMIT:
        if _at_or_beyond(bar.open, bar.entry_price, favourable=not bar.long):
            return [bar.adverse(), bar.favourable(), bar.close]
        if _at_or_beyond(bar.adverse(), bar.entry_price, favourable=not bar.long):
            return [bar.adverse(), bar.close]
        return None
    if bar.entry_kind == STOP:
        if _at_or_beyond(bar.open, bar.entry_price, favourable=bar.long):
            return [bar.adverse(), bar.favourable(), bar.close]
        if _at_or_beyond(bar.favourable(), bar.entry_price, favourable=bar.long):
            return [bar.adverse(), bar.favourable(), bar.close]
        return None
    raise ValueError(f"Expected a limit or stop entry inside the bar, got {bar.entry_kind}.")


def _at_or_beyond(price: int, level: int, favourable: bool) -> bool:
    """Whether `price` lies at `level` or past it upward (`favourable` to a long) or downward."""
    return price >= level if favourable else price <= level


def _stop_through_the_market(bar: EntryBar) -> bool:
    """A bracket's stop at or through the market at its entry's fill fills at once (F-STP-05)."""
    return bar.stop_price >= bar.entry_price if bar.long else bar.stop_price <= bar.entry_price


def _first_leg_crossed(bar: EntryBar, start: int, points: list[int]) -> tuple[str, int] | None:
    """The first leg a monotonic segment of the path covers, at its level."""
    previous = start
    for point in points:
        low, high = min(previous, point), max(previous, point)
        for reason, level in ((STOP, bar.stop_price), (TARGET, bar.target_price)):
            if low <= level <= high and level != previous:
                return reason, level
        previous = point
    return None


def other_exit(bar: EntryBar, conventions: EngineConventions) -> tuple[str, int] | None:
    """The leg NautilusTrader fills on the rest of the entry's bar and its price, or None."""
    ticks = _ticks(bar, conventions)
    released = _entry_tick(bar, ticks)
    if released is None:
        return None
    index, _ = released
    release_price = ticks[index]
    for reason, level in ((STOP, bar.stop_price), (TARGET, bar.target_price)):
        if _past(release_price, level, reason, bar.long):
            return reason, release_price
    for price in ticks[index + 1 :]:
        for reason, level in ((STOP, bar.stop_price), (TARGET, bar.target_price)):
            if _past(price, level, reason, bar.long):
                return reason, level
    return None


def _ticks(bar: EntryBar, conventions: EngineConventions) -> list[int]:
    if conventions.bar_order == BarOrder.ADVERSE_FIRST:
        raise ValueError("Expected NautilusTrader's or NinjaTrader's bar order, got FEFAT's.")
    first = conventions.first_extreme(bar.open, bar.high, bar.low, bar.long)
    extremes = [bar.high, bar.low] if first == Extreme.HIGH else [bar.low, bar.high]
    return [bar.open, *extremes, bar.close]


def _entry_tick(bar: EntryBar, ticks: list[int]) -> tuple[int, int] | None:
    """The index of the tick the entry fills on and the fill price."""
    for index, price in enumerate(ticks):
        if bar.entry_kind == LIMIT and _at_or_beyond(
            price, bar.entry_price, favourable=not bar.long
        ):
            return index, bar.entry_price
        if bar.entry_kind == STOP and _at_or_beyond(price, bar.entry_price, favourable=bar.long):
            return index, (price if index == 0 else bar.entry_price)
    return None


def _past(price: int, level: int, reason: str, long: bool) -> bool:
    """Whether a tick's price reaches a leg: a long's stop from above, its target from below."""
    downward = (reason == STOP) == long
    return price <= level if downward else price >= level
