"""What the reference engine books: each fill with what F-TAG-01 has it record, the funding
payments of a perpetual, the marks of an open position (F-MRK-01), and the flat-to-flat trades
a run's fills make. Money counts micro-units of the instrument's currency, rounded once, where
it is booked (F-FEE-03)."""

from collections.abc import Iterable
from enum import StrEnum

from fefat.market.fidelity import Fidelity
from fefat.market.schema import FrozenModel
from fefat.reference.orders import OrderRole, PositionSide, Side


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
    than its reference it is, its flags, the fee it paid, and what its value moved the cash by,
    both in micro-units (F-FEE-03)."""

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
    """One flat-to-flat trade: its side and lots, its entry and exit, why it closed, what its
    fills' values made, before fees, and the fees, both in micro-units."""

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
    """The trades of a run that starts flat and holds one position at a time, each opened by
    one fill and closed whole by the next; a position still open is no trade yet."""
    trades = []
    entry: Fill | None = None
    for fill in fills:
        if entry is None:
            entry = fill
            continue
        if fill.side is entry.side or fill.lots != entry.lots:
            raise ValueError(
                f"Expected each trade closed whole by one fill, got order {fill.order}'s "
                f"{fill.side} of {fill.lots} after order {entry.order}'s {entry.side} of "
                f"{entry.lots}."
            )
        side = PositionSide.LONG if entry.side is Side.BUY else PositionSide.SHORT
        trades.append(
            Trade(
                side=side,
                lots=entry.lots,
                entry_ts=entry.ts,
                entry_price=entry.price,
                exit_ts=fill.ts,
                exit_price=fill.price,
                exit_reason=fill.role,
                pnl=entry.cash + fill.cash,
                fees=entry.fee + fill.fee,
            )
        )
        entry = None
    return tuple(trades)
