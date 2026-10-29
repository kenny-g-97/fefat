"""What the reference engine books: each fill with what F-TAG-01 has it record, the funding
payments of a perpetual, the marks of an open position (F-MRK-01), and the flat-to-flat trades
a run's fills make. Money counts micro-units of the instrument's currency, rounded once, where
it is booked (F-FEE-03)."""

import math
from collections.abc import Iterable
from enum import StrEnum
from fractions import Fraction

from fefat.market.fidelity import Fidelity
from fefat.market.schema import FrozenModel
from fefat.reference.orders import ROLL_ROLES, OrderRole, PositionSide, Side


class Liquidity(StrEnum):
    """Whether a fill rested on the book or took liquidity (F-LMT-04)."""

    MAKER = "maker"
    TAKER = "taker"


class FillFlag(StrEnum):
    """What a fill is flagged with: a bar's fills that depend on the order of its extremes
    (F-BAR-05), or a size above the size its record shows (F-QTY-01)."""

    AMBIGUOUS = "ambiguous"
    SIZE_EXCEEDED = "size_exceeded"


class Fill(FrozenModel):
    """One fill, as F-TAG-01 has it recorded: the order, when, at what price, the rule that
    priced it, the fidelity of the data it filled on, its liquidity, how many ticks worse
    than its reference it is, the contract it is of (F-ROL-01), its flags, the fee it paid, and
    what its value moved the cash by, both in micro-units (F-FEE-03)."""

    order: int
    role: OrderRole
    side: Side
    lots: int
    ts: int
    price: int
    rule: str
    fidelity: Fidelity
    liquidity: Liquidity
    slippage_ticks: int
    contract: str
    flags: tuple[FillFlag, ...] = ()
    fee: int = 0
    cash: int = 0


class FundingPayment(FrozenModel):
    """A funding payment at `ts`, as the change to the trader's cash in micro-units: positive
    when received (F-FND-01)."""

    ts: int
    amount: int


class Mark(FrozenModel):
    """The price an open position is marked at once the events at `ts` are done (F-MRK-01)."""

    ts: int
    price: int


class Trade(FrozenModel):
    """One exit of a flat-to-flat trade: its side and the lots this exit closed, its entry and
    this exit, why the exit closed them, its role (F-TAG-01), what the fills' values made on
    those lots, before fees, and the fees, both in micro-units. A trade an exit plan closes in
    parts (F-PLN-02) gives one of these per exit, each with the entry of the whole trade."""

    side: PositionSide
    lots: int
    entry_ts: int
    entry_price: int
    exit_ts: int
    exit_price: int
    exit_reason: OrderRole
    pnl: int
    fees: int


def trades_of(fills: Iterable[Fill]) -> tuple[Trade, ...]:
    """The exits of the trades of a run that starts flat and holds one position at a time, each
    opened by one fill and closed by one or more: each exit's share of the entry's cash and fee is
    rounded against the trader (F-FEE-03), so a whole exit makes exactly what its two fills moved.
    A position still open is no trade yet."""
    trades = []
    entry: Fill | None = None
    open_lots = 0
    for fill in fills:
        if fill.role in ROLL_ROLES:
            raise ValueError(
                f"Expected fills without a roll's legs, which the trades of step 2.10 pair, got "
                f"order {fill.order}'s {fill.role}."
            )
        if entry is None:
            entry, open_lots = fill, fill.lots
            continue
        if fill.side is entry.side or fill.lots > open_lots:
            raise ValueError(
                f"Expected each exit to close some of the open {open_lots} lots, got order "
                f"{fill.order}'s {fill.side} of {fill.lots} after order {entry.order}'s "
                f"{entry.side} of {entry.lots}."
            )
        share = Fraction(fill.lots, entry.lots)
        side = PositionSide.LONG if entry.side is Side.BUY else PositionSide.SHORT
        trades.append(
            Trade(
                side=side,
                lots=fill.lots,
                entry_ts=entry.ts,
                entry_price=entry.price,
                exit_ts=fill.ts,
                exit_price=fill.price,
                exit_reason=fill.role,
                pnl=math.floor(entry.cash * share) + fill.cash,
                fees=math.ceil(entry.fee * share) + fill.fee,
            )
        )
        open_lots -= fill.lots
        if open_lots == 0:
            entry = None
    return tuple(trades)
