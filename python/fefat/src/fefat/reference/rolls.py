"""Rolls in the reference engine (`docs/spec/fill-semantics.md` §29, step 2.9): a futures run
trades one contract at a time, its front, and passes to the next at each roll the roll calendar
gives (`RollCalendar.rolls()`, D-44), its tape holding each session's records of that session's
front at their raw prices. A roll is a session event at its open: the front changes, every price
the run holds moves by the gap, and an open position's legs are sent, which fill before any other
order on the first record or bar after it. Each rule is a small function named after its
identifier, as in `fefat.reference.engine`, which calls `on_roll` at each roll and `fill_legs`
at the first tradeable record or bar after it."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Annotated

import polars as pl
from pydantic import Field

from fefat.market.continuous import RollCalendar
from fefat.market.roll_decisions import RollReason
from fefat.market.schema import FrozenModel
from fefat.reference.booking import book_fill
from fefat.reference.event_log import EventKind, EventLog
from fefat.reference.orders import (
    EXIT_ROLES,
    Book,
    OrderKind,
    OrderRole,
    OrderState,
    Side,
    WorkingOrder,
)
from fefat.reference.settings import RollHandling
from fefat.reference.tape import BarRecord, Record, stored_bars
from fefat.reference.timeline import Moment, Priced
from fefat.reference.units import Instant, Price, instant_text

if TYPE_CHECKING:
    from fefat.reference.engine import ReferenceEngine

_ROLES = {
    RollReason.VOLUME: OrderRole.ROLL_VOLUME,
    RollReason.OPEN_INTEREST: OrderRole.ROLL_OPEN_INTEREST,
    RollReason.CALENDAR: OrderRole.ROLL_CALENDAR,
    RollReason.EXPIRY: OrderRole.ROLL_EXPIRY,
}


class RollRow(FrozenModel):
    """A roll as the roll calendar gives it: the trade date of the session whose open it comes at,
    that open, the contract rolled from, the new front, the gap, the new contract's close less the
    old one's in the latest bar both traded in before the session, and why (D-44)."""

    trade_date: date
    session_open: Instant
    rolled_from: Annotated[str, Field(min_length=1)]
    contract: Annotated[str, Field(min_length=1)]
    gap: Price
    reason: RollReason

    def role(self) -> OrderRole:
        """The role its legs record (F-ROL-02, F-TAG-01)."""
        return _ROLES[self.reason]


@dataclass(frozen=True, slots=True)
class Transfer:
    """A roll's legs on their way (F-ROL-02): the close leg, the open leg, none when the roll
    flattens (F-ROL-04), the gap, the contract rolled from, and the instant the position opened,
    which a transfer keeps (F-TIM-02)."""

    close: WorkingOrder
    open: WorkingOrder | None
    gap: int
    rolled_from: str
    opened_at: int | None


def rolls_within(calendar: RollCalendar, tape: Sequence[Record]) -> tuple[RollRow, ...]:
    """The rolls of `calendar` that `tape` crosses, as the engines take them, never worked out
    again (F-ROL-01): those whose session opens after the tape's first record starts and by the
    time its last one starts, so that a record follows each, a trade at the open itself coming
    after the roll and a bar that closes at it before (F-CLK-02)."""
    first, last = tape[0].starts_at(), tape[-1].starts_at()
    crossed = pl.col("session_open").is_between(first, last, closed="right")
    rows = calendar.rolls().filter(crossed).iter_rows(named=True)
    return tuple(
        RollRow.model_construct(**{**row, "reason": RollReason(row["reason"])}) for row in rows
    )


def tape_across_rolls(
    frame: pl.DataFrame, calendar: RollCalendar
) -> tuple[tuple[BarRecord, ...], tuple[RollRow, ...]]:
    """A series `load` spliced with `calendar` (`SIGNAL_BAR_COLUMNS`), as the engines replay it:
    its stored bars, each session's front at its own raw prices (`stored_bars`), and the rolls
    between them (`rolls_within`), which a run across them must be given (F-ROL-01). A bar of
    another contract than the front `calendar` gives its session is refused: the bars of every
    contract, which a load without splicing returns, or a series another provider's calendar
    spliced, whose rolls fall on other days."""
    fronts = calendar.rows.select("trade_date", front=pl.col("contract"))
    others = (
        frame.join(fronts, on="trade_date", how="left")
        .filter(pl.col("front").is_null() | (pl.col("contract") != pl.col("front")))
        .sort("ts_close")
    )
    if not others.is_empty():
        other = others.row(0, named=True)
        front = "none" if other["front"] is None else other["front"]
        raise ValueError(
            f"Expected the bars of the front the roll calendar of {calendar.root} gives each "
            f"session, got {other['contract']} on {other['trade_date']}, where it gives {front}: "
            "load the series from the calendar's own datasets (D-44)."
        )
    tape = stored_bars(frame)
    return tape, rolls_within(calendar, tape)


def f_rol_01(rolls: Sequence[RollRow], contract: str) -> None:
    """A run takes its rolls from the roll calendar, in the order of their opens, each rolling
    from the front the one before it left, the first from the run's first front, `contract`."""
    front, opens = contract, [roll.session_open for roll in rolls]
    if opens != sorted(set(opens)):
        listed = ", ".join(instant_text(at) for at in opens)
        raise ValueError(
            f"Expected the rolls in the order of their opens, each once, got {listed}."
        )
    for roll in rolls:
        if roll.rolled_from != front or roll.contract == front:
            raise ValueError(
                f"Expected the roll at {instant_text(roll.session_open)} to roll from {front} to "
                f"another contract, got {roll.rolled_from} to {roll.contract}."
            )
        front = roll.contract


def f_rol_02(side: Side, price: int, shown: int | None, gap: int, ticks: int, tick: int) -> Priced:
    """A roll's leg fills at `price`, the price a market order of its side takes on the first
    record after the roll, or that bar's open, less `gap` for the close leg, the old contract's
    price, moved by the market slippage ticks against the trader; flagged against `shown`, the
    size its record shows (F-QTY-01)."""
    reference = price - gap
    return Priced(side.moved(reference, ticks, tick), "F-ROL-02", reference, shown)


def f_rol_03(book: Book, gap: int, log: EventLog, ts: int) -> None:
    """At a roll every live stop and limit moves by the gap, a stop triggered on TBBO among them,
    and the log records each move; so do each live exit plan's fill and best prices, the prices
    an entry still to fill names for its plan, and the mark."""
    for order in book.live():
        if order.plan is not None:
            order.plan = order.plan.shifted_by(gap)
        if order.price is None:
            continue
        before, order.price = order.price, order.price + gap
        log.shifted(ts, order.id, before, order.price)
    for plan in book.plans_in_order():
        plan.shifted_by(gap)
    if book.mark is not None:
        book.mark += gap


def f_rol_04(book: Book, log: EventLog, ts: int, exiting: WorkingOrder | None) -> None:
    """With `roll_handling: flatten`, the position's exit plan and any exit on its way out of part
    of it are cancelled, the close leg doing their work; `exiting`, an order on its way out of all
    its lots, does the close leg's work instead (F-ROL-02)."""
    for order in book.live():
        if order is exiting:
            continue
        if order.leg_of is not None or order.role in EXIT_ROLES:
            book.close(order, OrderState.CANCELLED)
            text = f"order {order.id}: the roll's close leg closes the position"
            log.note(ts, EventKind.CANCELLED, text, order.id, "F-ROL-04")


def on_roll(engine: "ReferenceEngine", at: Moment, roll: RollRow) -> None:
    """A roll (§29): the front passes to the new contract, every price the run holds moves by the
    gap, and an open position's legs are sent, both to transfer it, the close leg alone to flatten
    it, or none when an order on its way out of all its lots does the close leg's work (F-ROL-01
    to F-ROL-04)."""
    book, log = engine.book, engine.log
    if engine.transfer is not None:
        raise ValueError(
            f"Expected the legs of the roll before {instant_text(roll.session_open)} to fill "
            "before it, got them still on their way (F-ROL-01)."
        )
    log.rolled(at.ts, roll.rolled_from, roll.contract, roll.gap, roll.reason)
    held, flattens = book.position, engine.settings.roll_handling is RollHandling.FLATTEN
    exiting = _on_its_way_out(book)
    if held and flattens:
        f_rol_04(book, log, at.ts, exiting)
    f_rol_03(book, roll.gap, log, at.ts)
    engine.front = roll.contract
    if not held:
        return
    if exiting is not None:
        engine.transfer = Transfer(exiting, None, roll.gap, roll.rolled_from, book.opened_at)
        return
    closing = Side.SELL if held > 0 else Side.BUY
    close = _sent(book, log, closing, abs(held), roll, at)
    opening = None if flattens else _sent(book, log, closing.opposite(), abs(held), roll, at)
    engine.transfer = Transfer(close, opening, roll.gap, roll.rolled_from, book.opened_at)


def _on_its_way_out(book: Book) -> WorkingOrder | None:
    """A market order already on its way out of all the position's lots, an exit the strategy
    placed or a stop triggered on TBBO, which does a roll's close leg's work (F-ROL-02); none
    while flat."""
    if not book.position:
        return None
    closing = Side.SELL if book.position > 0 else Side.BUY
    on_its_way = [
        order
        for order in book.live()
        if order.side is closing
        and order.lots == abs(book.position)
        and (order.role in EXIT_ROLES or (order.state is OrderState.TRIGGERED and order.leg_of))
    ]
    return min(on_its_way, key=lambda order: order.id, default=None)


def _sent(
    book: Book, log: EventLog, side: Side, lots: int, roll: RollRow, at: Moment
) -> WorkingOrder:
    """A leg of a roll: a market order already sent, which no decision cancels (F-ROL-02)."""
    order = WorkingOrder(
        id=book.new_id(),
        side=side,
        kind=OrderKind.MARKET,
        price=None,
        lots=lots,
        role=roll.role(),
        placed_at=at.ts,
        activation=at.ts,
        seen_after=at.index,
        state=OrderState.TRIGGERED,
    )
    book.orders.append(order)
    placed = f"order {order.id}: {order.described()}, a leg of the roll"
    log.note(at.ts, EventKind.PLACED, placed, order.id, "F-ROL-02")
    return order


def fill_legs(
    engine: "ReferenceEngine",
    at: Moment,
    priced: Callable[[Side], tuple[int, int | None]],
    market: int,
) -> None:
    """The roll's legs fill on the first tradeable record or bar after it, before any other
    order's turn, the close leg first, each at the price a market order of its side takes there,
    `priced` giving it with the size its record shows (F-ROL-02); a transfer leaves the trade open
    and its open where it was (§20, F-TIM-02)."""
    transfer = engine.transfer
    if transfer is None:
        return
    engine.transfer = None
    legs = [(transfer.close, transfer.gap, transfer.rolled_from)]
    if transfer.open is not None:
        legs.append((transfer.open, 0, engine.front))
    ticks = engine.ticks(OrderKind.MARKET)
    for order, gap, contract in legs:
        price, shown = priced(order.side)
        filled = f_rol_02(order.side, price, shown, gap, ticks, engine.tick)
        execution = engine.execute(engine.book, order, filled, at, market)
        if order is transfer.close and transfer.open is not None:
            execution = replace(execution, flat_after=False)
        book_fill(engine, at.ts, execution, contract=contract)
    if transfer.open is not None:
        engine.book.opened_at = transfer.opened_at
