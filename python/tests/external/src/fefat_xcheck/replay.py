"""What each engine's documented rules give a trade on the 1-minute bars both engines filled on:
the entry's fill, the rest of the entry's bar, every later bar until a leg of the bracket fills,
and the flat-by. The classifier holds each engine's observed trade to this replay, so that a
difference between the engines is explained only where both fills are what the rules give, and
a fill the rules do not give stays `unknown`.

FEFAT (`docs/spec/fill-semantics.md`): a market order decided at a close fills at the next bar's
open (F-MKT-03, F-ACT-02); flat, a bar's first extreme is the one favourable to the working
entry, the high for a buy (F-BAR-03); a limit fills at its price where the path touches it
(F-LMT-02, F-LMT-03) and a stop at its price where the path reaches it, or at the open when the
bar opens through it (F-STP-04); after the fill the extremes not yet reached come adverse first,
then the close (F-BAR-04), the exit plan working from the entry's point (F-OCO-02); holding a
position, the adverse extreme comes first (F-BAR-02); a stop through the market at the entry's
point fills at once there (F-STP-05); a leg the path reaches fills at its level, a stop a bar
opens through at the open (F-STP-04), a limit a bar opens through at its price (F-LMT-03); the
flat-by closes at the market at its decision, the next bar's open (F-TIM-01).

NautilusTrader (its backtesting documentation and the runs of step 2.14): a market order from
`on_bar` settles at the last bar's close, and its legs meet the next bar whole; a bar is four
ticks, the open, the high, the low, and the close, in that order or with the extreme nearer the
open first and the low on a tie; a limit or stop entry fills on the first tick that satisfies it,
a limit at its price, a stop at its trigger price or at the open's price when the open is
through it; its legs are released on that tick, and a leg whose level that tick's price is
already past fills at that price; on later ticks a leg fills at its level, a stop a bar opens
through at the open.

NinjaTrader 8 (the builder's spec, H1 to H4): a market order fills at the next bar's open; the
bar is walked open, the extreme nearer the open, the other, close, the high on a tie; a stop
fills at its price, or at the open when the bar opens through it; a limit fills at its price
clamped into the bar's range."""

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from fefat_xcheck.conventions import BarOrder, EngineConventions, Extreme, LimitGap, MarketFill
from fefat_xcheck.units import MINUTE, NANOSECONDS_PER_SECOND


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


class EntryKind(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class ExitReason(StrEnum):
    STOP = "stop"
    TARGET = "target"
    FLAT_BY = "flat_by"


@dataclass(frozen=True)
class Bar:
    ts_close: int
    open: int
    high: int
    low: int
    close: int

    def extreme(self, which: Extreme) -> int:
        return self.high if which == Extreme.HIGH else self.low


@dataclass(frozen=True)
class Rules:
    """How a strategy was run, as far as the replay needs it: the engine's conventions, the
    tick, a limit or stop entry's ticks from the close and the minutes between the decisions
    it rests between, and the flat-by time of the strategy's time zone."""

    conventions: EngineConventions
    tick: int
    offset_ticks: int
    flat_by: time
    zone: ZoneInfo
    decision_minutes: int = 5

    def flat_by_decision(self, decision: int) -> int:
        """The decision at the flat-by time on the decision's local date, on the grid."""
        local = datetime.fromtimestamp(decision / NANOSECONDS_PER_SECOND, tz=self.zone)
        at = datetime.combine(local.date(), self.flat_by, tzinfo=self.zone)
        return int(at.timestamp()) * NANOSECONDS_PER_SECOND


@dataclass(frozen=True)
class Legs:
    long: bool
    stop: int
    target: int

    def level_of(self, reason: ExitReason) -> int:
        return self.stop if reason == ExitReason.STOP else self.target

    def past(self, price: int, reason: ExitReason) -> bool:
        """Whether a price lies at the leg or beyond it: a long's stop from above, its target
        from below."""
        level = self.level_of(reason)
        return price <= level if self.reached_downward(reason) else price >= level

    def reached_downward(self, reason: ExitReason) -> bool:
        return (reason == ExitReason.STOP) == self.long


@dataclass(frozen=True)
class Expected:
    """A trade as the engine's rules give it."""

    entry_ts: int
    entry_price: int
    exit_ts: int
    exit_price: int
    exit_reason: ExitReason


@dataclass(frozen=True)
class _Entered:
    """The entry's fill: the bar it filled in, its stamp, its price, the price the legs are
    judged against at the fill, the price of the tick that released them, if one did, and the
    prices the path visits after the fill on the entry's bar."""

    bar: Bar
    ts: int
    price: int
    market: int
    release_price: int | None
    remaining: list[int]


Exit = tuple[int, int, ExitReason]
"""An exit's stamp, price, and reason."""


class Bars:
    """The 1-minute bars, looked up by close and around an instant."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = sorted(bars, key=lambda bar: bar.ts_close)
        self._closes = [bar.ts_close for bar in self._bars]

    @classmethod
    def of_rows(cls, rows: list[tuple[int, int, int, int, int]]) -> "Bars":
        return cls([Bar(*row) for row in rows])

    def at(self, ts_close: int) -> Bar | None:
        index = self._first_after(ts_close) - 1
        if index >= 0 and self._closes[index] == ts_close:
            return self._bars[index]
        return None

    def after(self, instant: int) -> Bar | None:
        """The first bar closing after the instant: the first an order decided then sees
        (F-ACT-02)."""
        index = self._first_after(instant)
        return self._bars[index] if index < len(self._bars) else None

    def at_or_before(self, instant: int) -> Bar | None:
        """The last bar closing at or before the instant, the market a decision there found."""
        index = self._first_after(instant)
        return self._bars[index - 1] if index else None

    def between(self, after: int, through: int) -> list[Bar]:
        """The bars closing after one instant and at or before another."""
        return self._bars[self._first_after(after) : self._first_after(through)]

    def _first_after(self, instant: int) -> int:
        low, high = 0, len(self._closes)
        while low < high:
            middle = (low + high) // 2
            if self._closes[middle] <= instant:
                low = middle + 1
            else:
                high = middle
        return low


def expected_trade(
    decision: int, side: Side, kind: EntryKind, legs: Legs, rules: Rules, bars: Bars
) -> Expected | None:
    """The trade the engine's rules give an entry decided at `decision`, or None when a limit
    or stop entry never fills before the next decision cancels it, or the bars run out."""
    entered = _entry(decision, side, kind, rules, bars)
    if entered is None:
        return None
    flat_by = rules.flat_by_decision(decision)
    conventions = rules.conventions
    exit = _exit_on_the_entry_bar(entered, legs, conventions)
    if exit is None:
        later = bars.between(entered.bar.ts_close, flat_by)
        exit = _exit_on_later_bars(legs, conventions, later)
    if exit is None:
        exit = _flat_by_exit(flat_by, conventions, bars)
    if exit is None:
        return None
    exit_ts, exit_price, reason = exit
    return Expected(entered.ts, entered.price, exit_ts, exit_price, reason)


def _entry(decision: int, side: Side, kind: EntryKind, rules: Rules, bars: Bars) -> _Entered | None:
    long = side == Side.LONG
    conventions = rules.conventions
    if kind == EntryKind.MARKET:
        return _market_entry(decision, long, conventions, bars)
    decided_on = bars.at_or_before(decision)
    if decided_on is None:
        return None
    offset = rules.offset_ticks * rules.tick
    away = offset if long else -offset
    level = decided_on.close - away if kind == EntryKind.LIMIT else decided_on.close + away
    for bar in bars.between(decision, decision + rules.decision_minutes * MINUTE):
        entered = (
            _fefat_resting_entry(bar, long, kind, level)
            if conventions.bar_order == BarOrder.ADVERSE_FIRST
            else _tick_resting_entry(bar, long, kind, level, conventions)
        )
        if entered is not None:
            return entered
    return None


def _market_entry(
    decision: int, long: bool, conventions: EngineConventions, bars: Bars
) -> _Entered | None:
    """A market order: at the deciding bar's close, its legs meeting the next bar whole with
    the rules of a later bar, or at the next bar's open, its legs working on the rest of it."""
    if conventions.market_fill == MarketFill.AT_DECISION_CLOSE:
        decided_on = bars.at_or_before(decision)
        if decided_on is None:
            return None
        # shortcut: legs already past the deciding close at submission, which Nautilus fills at
        # once, are not judged; unreachable while the levels are set from that close.
        return _Entered(decided_on, decision, decided_on.close, decided_on.close, None, [])
    next_bar = bars.after(decision)
    if next_bar is None:
        return None
    after_the_open = _after_the_open(next_bar, long, conventions)
    return _Entered(next_bar, next_bar.ts_close, next_bar.open, next_bar.open, None, after_the_open)


def _after_the_open(bar: Bar, long: bool, conventions: EngineConventions) -> list[int]:
    """The prices after a bar's open, in the engine's order for a position held from the open."""
    first = conventions.first_extreme(bar.open, bar.high, bar.low, long)
    other = Extreme.LOW if first == Extreme.HIGH else Extreme.HIGH
    return [bar.extreme(first), bar.extreme(other), bar.close]


def _fefat_resting_entry(bar: Bar, long: bool, kind: EntryKind, level: int) -> _Entered | None:
    """A limit or stop entry on FEFAT's path: the favourable extreme first (F-BAR-03), then
    after the fill the extremes not yet reached adverse first, then the close (F-BAR-04)."""
    favourable, adverse = (bar.high, bar.low) if long else (bar.low, bar.high)
    upward = long if kind == EntryKind.STOP else not long
    if _at_or_past(bar.open, level, upward):
        price = bar.open if kind == EntryKind.STOP else level
        return _Entered(bar, bar.ts_close, price, bar.open, None, [adverse, favourable, bar.close])
    if kind == EntryKind.LIMIT and _at_or_past(adverse, level, upward):
        return _Entered(bar, bar.ts_close, level, level, None, [adverse, bar.close])
    if kind == EntryKind.STOP and _at_or_past(favourable, level, upward):
        return _Entered(bar, bar.ts_close, level, level, None, [adverse, favourable, bar.close])
    return None


def _tick_resting_entry(
    bar: Bar, long: bool, kind: EntryKind, level: int, conventions: EngineConventions
) -> _Entered | None:
    """A limit or stop entry on an engine that walks the bar as ticks: the first tick that
    satisfies it fills it, and the ticks after it are what the legs see."""
    ticks = [bar.open, *_after_the_open(bar, long, conventions)]
    upward = long if kind == EntryKind.STOP else not long
    for index, price in enumerate(ticks):
        if not _at_or_past(price, level, upward):
            continue
        filled_at = price if kind == EntryKind.STOP and index == 0 else level
        return _Entered(bar, bar.ts_close, filled_at, price, price, ticks[index + 1 :])
    return None


def _at_or_past(price: int, level: int, upward: bool) -> bool:
    """Whether `price` lies at `level` or past it, upward or downward."""
    return price >= level if upward else price <= level


def _exit_on_the_entry_bar(
    entered: _Entered, legs: Legs, conventions: EngineConventions
) -> Exit | None:
    """The leg the rest of the entry's bar fills, and its price. Legs released on a tick fill
    at that tick's price when it is past them; legs placed at the entry's point of a path are
    judged there at once, a stop through it filling there (F-STP-05) and a target it reaches at
    its price (F-LMT-03, clamped where the engine clamps), as the reference engine's `fill`
    does."""
    if entered.release_price is not None:
        for reason in (ExitReason.STOP, ExitReason.TARGET):
            if legs.past(entered.release_price, reason):
                return entered.bar.ts_close, entered.release_price, reason
    elif entered.remaining and legs.past(entered.market, ExitReason.STOP):
        return entered.bar.ts_close, entered.market, ExitReason.STOP
    elif entered.remaining and legs.past(entered.market, ExitReason.TARGET):
        price = _limit_price(entered.bar, legs.target, conventions)
        return entered.bar.ts_close, price, ExitReason.TARGET
    leg = _first_leg_crossed(entered.market, entered.remaining, legs)
    if leg is None:
        return None
    reason, price = leg
    return entered.bar.ts_close, price, reason


def _first_leg_crossed(start: int, points: list[int], legs: Legs) -> tuple[ExitReason, int] | None:
    """The first leg a segment of the path covers, the nearer first where a segment covers
    both, at its level."""
    previous = start
    for point in points:
        low, high = min(previous, point), max(previous, point)
        covered = [
            reason
            for reason in (ExitReason.STOP, ExitReason.TARGET)
            if low <= legs.level_of(reason) <= high and legs.level_of(reason) != previous
        ]
        if covered:
            nearest = min(covered, key=lambda reason: abs(legs.level_of(reason) - previous))
            return nearest, legs.level_of(nearest)
        previous = point
    return None


def _exit_on_later_bars(legs: Legs, conventions: EngineConventions, bars: list[Bar]) -> Exit | None:
    """The first later bar that reaches a leg: a bar opening through a stop fills it at the
    open, one opening through a target fills it at its price (clamped into the bar where the
    engine clamps); otherwise the engine's first extreme decides which leg fills, at its level."""
    for bar in bars:
        if legs.past(bar.open, ExitReason.STOP):
            return bar.ts_close, bar.open, ExitReason.STOP
        if legs.past(bar.open, ExitReason.TARGET):
            return bar.ts_close, _limit_price(bar, legs.target, conventions), ExitReason.TARGET
        first = conventions.first_extreme(bar.open, bar.high, bar.low, legs.long)
        for which in (first, Extreme.LOW if first == Extreme.HIGH else Extreme.HIGH):
            reason = _leg_on_the_side_of(which, legs)
            if legs.past(bar.extreme(which), reason):
                return bar.ts_close, legs.level_of(reason), reason
    return None


def _leg_on_the_side_of(which: Extreme, legs: Legs) -> ExitReason:
    """The leg an extreme can reach: the low a long's stop, the high its target."""
    downward = which == Extreme.LOW
    return (
        ExitReason.STOP if legs.reached_downward(ExitReason.STOP) == downward else ExitReason.TARGET
    )


def _limit_price(bar: Bar, level: int, conventions: EngineConventions) -> int:
    if conventions.limit_gap == LimitGap.CLAMPED_INTO_THE_BAR:
        return min(max(level, bar.low), bar.high)
    return level


def _flat_by_exit(flat_by: int, conventions: EngineConventions, bars: Bars) -> Exit | None:
    if conventions.market_fill == MarketFill.AT_DECISION_CLOSE:
        decided_on = bars.at_or_before(flat_by)
        return None if decided_on is None else (flat_by, decided_on.close, ExitReason.FLAT_BY)
    next_bar = bars.after(flat_by)
    return None if next_bar is None else (next_bar.ts_close, next_bar.open, ExitReason.FLAT_BY)
