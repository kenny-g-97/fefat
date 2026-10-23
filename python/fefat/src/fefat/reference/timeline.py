"""A reference run in time (`fefat.reference.engine`): its events in the order of F-CLK-02, the
moment of each, and what the engine makes of them, the executions it books and the result it
returns."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import NamedTuple

from fefat.reference.event_log import EventLog
from fefat.reference.ledger import Fill, FundingPayment, Liquidity, Mark
from fefat.reference.orders import WorkingOrder
from fefat.reference.strategy import Decision
from fefat.reference.tape import FundingRate, Record


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
    """What happens at `ts`, in `phase`: a record arriving, a funding time, or a decision."""

    ts: int
    phase: Phase
    subject: Record | FundingRate | Decision


@dataclass(frozen=True, slots=True)
class Moment:
    """When a fill happens, and its place in the run's timeline, after which its bracket's legs
    see records (F-OCO-02)."""

    ts: int
    index: int


class Priced(NamedTuple):
    """How a fill is priced: its price, the rule that priced it, its reference before ticks
    (F-TAG-01), and the size its record shows (F-QTY-01), none on bars."""

    price: int
    rule: str
    reference: int
    shown_size: int | None


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
    """A run's fills, each with its cash and fee, its funding payments, the marks of its open
    position once every event of an instant is done (F-MRK-01), its event log, and the position
    it ends with, in lots."""

    fills: tuple[Fill, ...]
    funding: tuple[FundingPayment, ...]
    marks: tuple[Mark, ...]
    log: EventLog
    position: int
