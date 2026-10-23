"""A reference run in time (`fefat.reference.engine`): its events in the order of F-CLK-02, the
moment of each, and what the engine makes of them, the executions it books and the result it
returns."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from fefat.reference.event_log import EventLog
from fefat.reference.ledger import Fill, FundingPayment, Liquidity, Mark
from fefat.reference.orders import WorkingOrder
from fefat.reference.strategy import Decision
from fefat.reference.tape import BarRecord, FundingRate, TbboRecord, TradeRecord

Record = TradeRecord | TbboRecord | BarRecord
"""A record of a tape: a trade print, a TBBO record, or a stored bar."""


class Phase(IntEnum):
    """The order of events at one instant (F-CLK-02): the bars closing then, timers such as
    funding, the records received then, and the bar-close decision. Activations need no event of
    their own, since an order is active at a record that comes at or after its activation."""

    BARS = 0
    TIMERS = 1
    RECORDS = 3
    DECISIONS = 4


class Extreme(StrEnum):
    """One of a bar's two extremes, replayed in the order F-BAR-02 to F-BAR-04 give."""

    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Event:
    ts: int
    phase: Phase
    item: Record | FundingRate | Decision


@dataclass(frozen=True, slots=True)
class Moment:
    """When a fill happens, and its place in the run's timeline, after which its bracket's legs
    see records (F-OCO-02)."""

    ts: int
    index: int


@dataclass(frozen=True, slots=True)
class Execution:
    """A fill as the rules give it, before it is booked: the order, its price, the rule that
    priced it, its reference before ticks (F-TAG-01), its liquidity, the size its record shows
    (F-QTY-01), and what it set off: the orders it cancelled and its bracket's legs."""

    order: WorkingOrder
    price: int
    rule: str
    reference: int
    liquidity: Liquidity
    shown_size: int | None
    cancelled: tuple[WorkingOrder, ...]
    bracket: tuple[WorkingOrder, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    """A run's fills, funding payments, and marks, its event log, its cash in micro-units, and
    the position it ends with, in lots."""

    fills: tuple[Fill, ...]
    funding: tuple[FundingPayment, ...]
    marks: tuple[Mark, ...]
    log: EventLog
    cash: int
    position: int
