"""Cases for the differential test of step 2.6, drawn by Hypothesis (the step's amendment of
2026-10-21): tapes of trades or TBBO records that walk a tick or two at a time with planted jumps
as wide as a session's range, so that gaps cross stops and limits; records received at one
instant; a break of the market inside some tapes; one to four market, stop, and limit orders
placed at one to three decision instants, with OCO pairs and brackets; an opening position; and
the run settings. Each case is an `EngineCase` that the reference engine and `fefat-cli run` both
run. Every value is drawn as a small number relative to the one before, so that ten cases fit
one example and a failure shrinks to its smallest tape. Hypothesis is a development tool, imported
when the strategy is built:

    @given(cases=st.lists(tick_cases(), min_size=10, max_size=10))
    def test_the_engines_agree(cases): ...
"""

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from fefat.market.calendar import Session
from fefat.market.fidelity import TickFidelity
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.orders import (
    Bracket,
    BracketLeg,
    LimitOrder,
    MarketOrder,
    OpenPosition,
    Order,
    PositionSide,
    Side,
    StopOrder,
)
from fefat.reference.rust_run import EngineCase
from fefat.reference.scenarios import Expected, Scenario
from fefat.reference.settings import LimitFill, RunSettings, SlippageTicks
from fefat.reference.tape import TbboRecord, TradeRecord
from fefat.reference.units import InlineInstrument, utc_date

if TYPE_CHECKING:
    from hypothesis.strategies import DrawFn, SearchStrategy

FIRST = 1_772_807_400 * 1_000_000_000
"""2026-03-06T14:30:00Z, the first record's instant before its drawn gap."""
MILLISECOND = 1_000_000
DAY = 86_400 * 1_000_000_000
GAPS_MS = (100, 0, 1, 50, 250, 900, 5_000, 60_000)
"""Milliseconds from one record to the next: 0 puts two at one instant (F-CLK-03)."""
STEPS = (0, 1, -1, 2, -2, 1, -1, 0, 12, -12, 40, -40, 200, -200)
"""Ticks from one trade to the next: a walk with planted jumps up to a session's range."""
OFFSETS_MS = (0, -100, 100, -1, 1, -1_000, 1_000)
"""Milliseconds from a record to a decision instant drawn beside it."""


class DrawnInstrument:
    """An instrument without a calendar, its tick and an opening price in 1e-9 units."""

    def __init__(self, instrument: InlineInstrument, tick: int, opening: int) -> None:
        self.instrument, self.tick, self.opening = instrument, tick, opening

    def quantity(self, lots: int) -> Decimal:
        return lots * self.instrument.lot_step


INSTRUMENTS = (
    DrawnInstrument(
        InlineInstrument.model_construct(
            tick_size=Decimal("0.25"), point_value=Decimal("50"), lot_step=Decimal("1")
        ),
        250_000_000,
        5_000_000_000_000,
    ),
    DrawnInstrument(
        InlineInstrument.model_construct(
            tick_size=Decimal("0.10"), point_value=Decimal("1"), lot_step=Decimal("0.001")
        ),
        100_000_000,
        65_000_000_000_000,
    ),
)
"""An ES-like future and a BTC-like perpetual with lots of 0.001."""


def tick_cases() -> "SearchStrategy[EngineCase]":
    """The strategy of one drawn case."""
    from hypothesis import strategies as st

    @st.composite
    def drawn_case(draw: "DrawFn") -> EngineCase:
        drawn = draw(st.sampled_from(INSTRUMENTS))
        tbbo = draw(st.booleans())
        tape = _tape(draw, drawn, tbbo)
        scenario = Scenario.model_construct(
            id="a drawn case",
            title="a drawn case",
            fidelity=TickFidelity.TBBO if tbbo else TickFidelity.TRADES,
            instrument=drawn.instrument,
            settings=_settings(draw),
            fees=None,
            position=_position(draw, drawn),
            tape=tape,
            funding=(),
            expected=Expected.model_construct(fills=(), marks=(), funding=()),
            rules=("F-CLK-01",),
            orders=_orders(draw, drawn, tape),
        )
        return EngineCase(scenario, _hours(draw, tape))

    return drawn_case()


def _tape(draw: "DrawFn", drawn: DrawnInstrument, tbbo: bool) -> tuple[TradeRecord, ...]:
    from hypothesis import strategies as st

    move = st.tuples(st.sampled_from(GAPS_MS), st.sampled_from(STEPS), st.integers(1, 9))
    quote = st.tuples(st.integers(-3, 2), st.integers(1, 3), st.integers(1, 9), st.integers(1, 9))
    record = st.tuples(move, quote) if tbbo else st.tuples(move, st.just((0, 1, 1, 1)))
    ts, price, tape = FIRST, drawn.opening, []
    for (gap, step, size), (bid_ticks, spread, bid_size, ask_size) in draw(
        st.lists(record, min_size=1, max_size=25)
    ):
        ts, price = ts + gap * MILLISECOND, price + step * drawn.tick
        if not tbbo:
            tape.append(TradeRecord.model_construct(ts=ts, ts_event=None, price=price, size=size))
            continue
        bid = price + bid_ticks * drawn.tick
        tape.append(
            TbboRecord.model_construct(
                ts=ts,
                ts_event=None,
                price=price,
                size=size,
                bid=bid,
                ask=bid + spread * drawn.tick,
                bid_size=bid_size,
                ask_size=ask_size,
            )
        )
    return tuple(tape)


def _orders(
    draw: "DrawFn", drawn: DrawnInstrument, tape: tuple[TradeRecord, ...]
) -> tuple[Order, ...]:
    from hypothesis import strategies as st

    beside = st.tuples(st.integers(0, len(tape) - 1), st.sampled_from(OFFSETS_MS))
    instants = sorted(
        {
            tape[record].ts + offset * MILLISECOND
            for record, offset in draw(st.lists(beside, min_size=1, max_size=3))
        }
    )
    orders: list[Order] = []
    group: str | None = None
    for number in range(1, draw(st.integers(1, 4)) + 1):
        placed_at = draw(st.sampled_from(instants))
        paired = draw(st.booleans())
        joins = group if group is not None else (f"pair {number}" if paired else None)
        orders.append(_order(draw, drawn, number, placed_at, joins))
        group = joins if group is None and paired else None
    return tuple(orders)


def _order(
    draw: "DrawFn", drawn: DrawnInstrument, number: int, placed_at: int, oco: str | None
) -> Order:
    from hypothesis import strategies as st

    side = draw(st.sampled_from((Side.BUY, Side.SELL)))
    kind = draw(st.sampled_from(("market", "stop", "limit")))
    level = drawn.opening + draw(st.integers(-12, 12)) * drawn.tick
    quantity = drawn.quantity(draw(st.integers(1, 3)))
    bracket = None
    if draw(st.booleans()):
        stop_ticks, target_ticks = draw(st.integers(1, 20)), draw(st.integers(1, 20))
        away = side.sign() * drawn.tick
        bracket = Bracket.model_construct(
            stop=BracketLeg.model_construct(id=100 + number, price=level - stop_ticks * away),
            target=BracketLeg.model_construct(id=200 + number, price=level + target_ticks * away),
        )
    common = {
        "id": number,
        "placed_at": placed_at,
        "side": side,
        "quantity": quantity,
        "oco": oco,
        "bracket": bracket,
    }
    if kind == "market":
        return MarketOrder.model_construct(kind="market", **common)
    if kind == "stop":
        return StopOrder.model_construct(kind="stop", price=level, **common)
    return LimitOrder.model_construct(kind="limit", price=level, **common)


def _position(draw: "DrawFn", drawn: DrawnInstrument) -> OpenPosition | None:
    from hypothesis import strategies as st

    if not draw(st.booleans()):
        return None
    side = draw(st.sampled_from((PositionSide.LONG, PositionSide.SHORT)))
    quantity = drawn.quantity(draw(st.integers(1, 3)))
    return OpenPosition.model_construct(side=side, quantity=quantity, price=drawn.opening)


def _settings(draw: "DrawFn") -> RunSettings:
    from hypothesis import strategies as st

    ticks = SlippageTicks.model_construct(
        market=draw(st.integers(0, 2)), stop=draw(st.integers(0, 2))
    )
    return RunSettings.model_construct(
        latency_ms=draw(st.sampled_from((100, 0, 1_000))),
        slippage_ticks=ticks,
        limit_fill=draw(st.sampled_from((LimitFill.THROUGH, LimitFill.TOUCH))),
    )


def _hours(draw: "DrawFn", tape: tuple[TradeRecord, ...]) -> AlwaysOpen | CalendarHours:
    """Always open, or closed from one record's instant to another's, both included."""
    from hypothesis import strategies as st

    if not draw(st.booleans()):
        return AlwaysOpen()
    first, second = draw(st.integers(0, len(tape) - 1)), draw(st.integers(0, len(tape) - 1))
    closes, opens = tape[min(first, second)].ts, tape[max(first, second)].ts + 1
    before = Session.model_construct(
        trade_date=utc_date(FIRST) - timedelta(days=1), open=FIRST - DAY, close=closes, halts=()
    )
    after = Session.model_construct(
        trade_date=utc_date(FIRST), open=opens, close=tape[-1].ts + DAY, halts=()
    )
    return CalendarHours([before, after])
