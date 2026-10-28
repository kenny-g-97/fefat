"""The entries of an execution template as the reference engine places them
(`docs/spec/fill-semantics.md` §25): the sides a row enters (F-ENT-01), the order each places
(F-ENT-02), the instant up to which a resting entry's time to live has ended (F-ENT-03), and what
an entry signal against the position does (F-ENT-04)."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from typing import Any

from fefat.reference.orders import OrderKind, Side
from fefat.reference.template.exits import column_price
from fefat.strategy.spec import (
    EntryOrder,
    LimitEntryAtColumn,
    LimitEntryOffset,
    MarketEntry,
    OppositeSignal,
    StopEntryAtColumn,
    StopEntryOffset,
)


def f_ent_01(bar: Mapping[str, Any]) -> list[Side]:
    """The sides a row enters, in order: `long_entry` buys, then `short_entry` sells. Under a
    market entry a row gives one of them, the frame being refused otherwise; under a limit or a
    stop entry a row that gives both places the pair, as one OCO group."""
    sides = [Side.BUY] if bar["long_entry"] else []
    return [*sides, Side.SELL] if bar["short_entry"] else sides


def f_ent_02(
    entry: EntryOrder, side: Side, bar: Mapping[str, Any], mark: int | None, tick: int
) -> tuple[OrderKind, int | None] | None:
    """The order an entry on `side` places, its class and price: a market order; a limit or a stop
    at the row's `entry_price`, which must be there and on the tick; or a limit or a stop `ticks`
    from the mark at the decision, a buy's limit under it and its stop above it. With no mark yet
    an offset entry places nothing (None), and the template logs why."""
    if isinstance(entry, MarketEntry):
        return OrderKind.MARKET, None
    if isinstance(entry, LimitEntryAtColumn | StopEntryAtColumn):
        kind = OrderKind.LIMIT if isinstance(entry, LimitEntryAtColumn) else OrderKind.STOP
        return kind, column_price(bar, "entry_price", tick)
    if mark is None:
        return None
    if isinstance(entry, LimitEntryOffset):
        return OrderKind.LIMIT, side.opposite().moved(mark, entry.ticks, tick)
    if isinstance(entry, StopEntryOffset):
        return OrderKind.STOP, side.moved(mark, entry.ticks, tick)
    raise ValueError(f"Expected an entry of a known kind, got {entry}.")


def f_ent_03(entry: EntryOrder, closes: Sequence[int], now: int) -> int | None:
    """The instant up to which the entries still live have reached their time to live at the
    decision `now`: an entry with `time_to_live_bars` n is cancelled at the n-th decision after
    the one that placed it, so those placed at or before the decision n before `now` go; none
    without a time to live or before n decisions."""
    time_to_live = None if isinstance(entry, MarketEntry) else entry.time_to_live_bars
    if time_to_live is None:
        return None
    placed_by = bisect_right(closes, now) - 1 - time_to_live
    return closes[placed_by] if placed_by >= 0 else None


def f_ent_04(on_opposite: OppositeSignal, bar: Mapping[str, Any], position: int) -> Side | None:
    """The side an entry signal against the position turns to: holding a long, a `short_entry`
    closes it under `close` and `reverse`, the second entering short after the exit; a short
    mirrors it. None when no such signal comes, or under `ignore`."""
    if on_opposite is OppositeSignal.IGNORE or position == 0:
        return None
    against = Side.SELL if position > 0 else Side.BUY
    opposite = bar["short_entry"] if position > 0 else bar["long_entry"]
    return against if opposite else None
