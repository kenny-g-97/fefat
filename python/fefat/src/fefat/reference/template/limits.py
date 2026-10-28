"""The entry limits of an execution template as the reference engine applies them
(`docs/spec/fill-semantics.md` §27): the blackout column (F-LIM-01), the counts of each trade date
(F-LIM-02), the cooldown after a losing trade (F-LIM-03), and fresh signals (F-LIM-04). Amounts of
money count micro-units, a specification's amount rounded down to the micro-unit (F-RND-01)."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any

from fefat.reference.orders import ClosedTrade
from fefat.reference.units import MONEY_DECIMALS
from fefat.strategy.exits import BarsCooldown, Limits


def micro_units(amount: float) -> int:
    """An amount of a specification, as the decimal it prints as, in whole micro-units rounded
    down (F-RND-01)."""
    return math.floor(Fraction(Decimal(repr(amount))) * 10**MONEY_DECIMALS)


@dataclass(slots=True)
class DayCounts:
    """What the template counts on one trade date (F-LIM-02): the entries it placed, a pair
    counting one, and the trades closed: how many lost, and their profit and loss in micro-units."""

    trade_date: date | None = None
    entries: int = 0
    losses: int = 0
    pnl: int = 0


@dataclass(slots=True)
class EntryLimits:
    """A template's entry limits and what they have counted: the day's counts, the trades closed
    so far that a decision has counted, and the cooldown, the last decision it covers by its index
    and the instant before which it covers decisions (F-LIM-03)."""

    limits: Limits
    day: DayCounts = field(default_factory=DayCounts)
    counted: int = 0
    cooled_through: int = -1
    cooled_until: int | None = None

    def count(self, trades: Sequence[ClosedTrade], trade_date: date, decision: int) -> None:
        """The decision of index `decision`, on `trade_date`, counts the trades closed since the
        last decision, `trades` (F-LIM-02), and starts a cooldown after each losing one."""
        if self.day.trade_date != trade_date:
            self.day = DayCounts(trade_date)
        for trade in trades:
            self.day.pnl += trade.pnl
            if trade.pnl < 0:
                self.day.losses += 1
                self._cool_down(trade, decision)
        self.counted += len(trades)

    def allow(self, bar: Mapping[str, Any], decision: int) -> bool:
        """Whether the row `bar`, the decision of index `decision`, may place an entry."""
        blocked = f_lim_01(self.limits, bar) or f_lim_02(self.limits, self.day)
        return not blocked and not f_lim_03(self, bar["ts_close"], decision)

    def entered(self) -> None:
        """An entry placed, or a pair (F-LIM-02)."""
        self.day.entries += 1

    def _cool_down(self, trade: ClosedTrade, decision: int) -> None:
        cooldown = self.limits.cooldown_after_loss
        if isinstance(cooldown, BarsCooldown):
            self.cooled_through = max(self.cooled_through, decision + cooldown.bars - 1)
        elif cooldown is not None:
            until = trade.closed_at + cooldown.minutes * 60 * 1_000_000_000
            later = self.cooled_until is not None and self.cooled_until > until
            self.cooled_until = self.cooled_until if later else until


# §27 Entry limits
def f_lim_01(limits: Limits, bar: Mapping[str, Any]) -> bool:
    """Whether the row's blackout column keeps it from entering: true does, false and null do
    not."""
    return limits.blackout is not None and bool(bar.get(limits.blackout))


def f_lim_02(limits: Limits, day: DayCounts) -> bool:
    """Whether the day's counts keep it from entering: its entries at `max_trades_per_day`, its
    losing trades at `max_losses_per_day`, or its closed trades' profit and loss at or below minus
    `daily_loss_stop` or at or above `profit_lock`."""
    reached = [
        limits.max_trades_per_day is not None and day.entries >= limits.max_trades_per_day,
        limits.max_losses_per_day is not None and day.losses >= limits.max_losses_per_day,
        limits.daily_loss_stop is not None and day.pnl <= -micro_units(limits.daily_loss_stop),
        limits.profit_lock is not None and day.pnl >= micro_units(limits.profit_lock),
    ]
    return any(reached)


def f_lim_03(limits: EntryLimits, now: int, decision: int) -> bool:
    """Whether a cooldown after a losing trade covers the decision of index `decision` at `now`:
    the `bars` decisions from the one that counted the loss on, or those before its closing fill
    plus `minutes`."""
    until = limits.cooled_until
    return decision <= limits.cooled_through or (until is not None and now < until)


def f_lim_04(
    limits: Limits, bar: Mapping[str, Any], before: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The row with its entry signals as they count: with `fresh_signal`, only where they were
    false on the row before, the first row's counting; without it, as they are."""
    if not limits.fresh_signal or before is None:
        return dict(bar)
    fresh = {
        signal: bool(bar[signal]) and not before[signal] for signal in ("long_entry", "short_entry")
    }
    return {**bar, **fresh}
