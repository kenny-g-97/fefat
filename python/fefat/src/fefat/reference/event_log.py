"""The reference engine's event log: every decision it makes, in order, with the rule of
`docs/spec/fill-semantics.md` behind it, so that a fill can be followed from the record that
priced it back to the decision that placed its order (step 2.2, `run.explain` from 2.11)."""

from collections.abc import Iterable
from enum import StrEnum

from fefat.market.schema import FrozenModel
from fefat.reference.ledger import Fill
from fefat.reference.orders import WorkingOrder
from fefat.reference.units import instant_text, money_text, price_text


class EventKind(StrEnum):
    """What happened: an order placed or active, a stop triggered, a fill, a cancellation, a
    funding payment, a break the working orders stay through, an ambiguous bar, a stop moved or
    reduced by its exit plan (F-PLN-02, F-PLN-03), or an entry signal the template could not
    act on (F-ENT-02, F-SIZ-04)."""

    PLACED = "placed"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FUNDING = "funding"
    BREAK = "break"
    AMBIGUOUS = "ambiguous"
    MOVED = "moved"
    REDUCED = "reduced"
    SKIPPED = "skipped"


class LogEntry(FrozenModel):
    """One event at `ts`, of `order` where it concerns one, under `rule`."""

    ts: int
    kind: EventKind
    order: int | None
    rule: str | None
    text: str


class EventLog:
    """The entries of one run, in the order they happened."""

    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def note(
        self, ts: int, kind: EventKind, text: str, order: int | None = None, rule: str | None = None
    ) -> None:
        self.entries.append(LogEntry(ts=ts, kind=kind, order=order, rule=rule, text=text))

    def filled(
        self,
        fill: Fill,
        cancelled: Iterable[WorkingOrder],
        bracket: Iterable[WorkingOrder],
        reduced: tuple[int, int] | None = None,
    ) -> None:
        """A fill, by the rule that priced it; the orders of its OCO group or its exit plan it
        cancelled (F-OCO-01); the stop of its plan it reduced (F-PLN-02); and the legs of its
        exit plan it placed (F-OCO-02)."""
        details = "".join(f", {detail}" for detail in (fill.liquidity, *fill.flags))
        filled = f"order {fill.order}: {fill.side} {fill.lots} at {price_text(fill.price)}"
        self.note(fill.ts, EventKind.FILLED, filled + details, fill.order, fill.rule)
        for other in cancelled:
            text = f"order {other.id}: order {fill.order} of its group filled"
            self.note(fill.ts, EventKind.CANCELLED, text, other.id, "F-OCO-01")
        if reduced is not None:
            stop, lots = reduced
            text = f"order {stop}: reduced to {lots}, order {fill.order} of its plan filled"
            self.note(fill.ts, EventKind.REDUCED, text, stop, "F-PLN-02")
        for leg in bracket:
            text = f"order {leg.id}: {leg.described()}, the exit plan of order {fill.order}"
            self.note(fill.ts, EventKind.PLACED, text, leg.id, "F-OCO-02")

    def moved(self, ts: int, order: int, before: int, after: int, rule: str) -> None:
        """A stop its exit plan moved, by breakeven or a trailing stop (F-PLN-03)."""
        text = f"order {order}: the stop moved from {price_text(before)} to {price_text(after)}"
        self.note(ts, EventKind.MOVED, text, order, rule)

    def skipped(self, ts: int, why: str, rule: str) -> None:
        """An entry signal the template could not act on (F-ENT-02, F-SIZ-04)."""
        self.note(ts, EventKind.SKIPPED, f"no entry: {why}", rule=rule)

    def active(self, ts: int, order: int, sees: str, rule: str) -> None:
        """An order that sees its first record or bar (F-ACT-01, F-ACT-02)."""
        self.note(ts, EventKind.ACTIVE, f"order {order} sees its first {sees}", order, rule)

    def ambiguous(self, ts: int) -> None:
        """A bar whose extremes, swapped, would fill otherwise (F-BAR-05)."""
        otherwise = "with its extremes swapped the bar fills otherwise"
        self.note(ts, EventKind.AMBIGUOUS, otherwise, rule="F-BAR-05")

    def triggered(self, ts: int, order: WorkingOrder, price: int) -> None:
        """A stop the trade at `price` reached (F-STP-01)."""
        reached = (
            f"the trade at {price_text(price)} reached the stop at {price_text(order.level())}"
        )
        self.note(ts, EventKind.TRIGGERED, f"order {order.id}: {reached}", order.id, "F-STP-01")

    def funded(self, ts: int, change: int, mark: int) -> None:
        """A funding payment, the change to the cash, at the mark (F-FND-01)."""
        paid = f"{money_text(change)} at the mark {price_text(mark)}"
        self.note(ts, EventKind.FUNDING, paid, rule="F-FND-01")

    def lines(self) -> list[str]:
        """Each entry as a line: its UTC time, its kind, what happened, and its rule."""
        return [
            f"{instant_text(entry.ts):<27} {entry.kind:<9}  {entry.text}"
            + (f" [{entry.rule}]" if entry.rule else "")
            for entry in self.entries
        ]
