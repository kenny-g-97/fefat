"""Cases for the differential tests of steps 2.6 and 2.7, drawn by Hypothesis (the amendments
of 2026-10-21), a development tool of the repository: on ticks, tapes of trades or TBBO records
that walk a tick or two at a time with planted jumps as wide as a session's range, so that gaps
cross stops and limits; on bars, the bars of 1 second, 1 minute, 5 minutes, or a UTC day that
such a walk of trades makes; records received at one instant; tapes across a UTC midnight; a
break of the market inside some tapes; and the run settings. An order case places one to four
market, stop, and limit orders at one to three decision instants, with OCO pairs, brackets, and
an opening position; a template case runs the execution template's basic subset over one to
five drawn signal rows. Each case is an `EngineCase` that the reference engine and `fefat-cli run` both
run, the Rust engine in full or skipping by the coarser bars of its records. Every value is
drawn as a small number relative to the one before, so that ten cases fit one example and a
failure shrinks to its smallest tape. Hypothesis is imported when a strategy is built:

    @given(cases=st.lists(drawn_cases(), min_size=10, max_size=10))
    def test_the_engines_agree(cases): ...
"""

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from fefat.market.calendar import Session
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe, TimeUnit
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
from fefat.reference.rust_batch import EngineCase, Replay, coarser_bars
from fefat.reference.scenarios import Expected, Scenario, TemplateScenario
from fefat.reference.settings import LimitFill, RunSettings, SlippageTicks
from fefat.reference.signal_rows import SignalRow
from fefat.reference.tape import Tape, TbboRecord, TradeRecord
from fefat.reference.units import InlineInstrument, utc_date
from fefat.strategy.spec import StrategySpec

if TYPE_CHECKING:
    from hypothesis.strategies import DrawFn, SearchStrategy

FIRST = 1_772_807_400 * 1_000_000_000
"""2026-03-06T14:30:00Z, the first record's instant before its drawn gap."""
MILLISECOND = 1_000_000
DAY = 86_400 * 1_000_000_000
GAPS_MS = (100, 0, 1, 50, 250, 900, 5_000, 60_000, 36_000_000)
"""Milliseconds from one record to the next: 0 puts two at one instant (F-CLK-03), and ten
hours take a tape past a UTC midnight, onto a second trade date of the batch."""
STEPS = (0, 1, -1, 2, -2, 1, -1, 0, 12, -12, 40, -40, 200, -200)
"""Ticks from one trade to the next: a walk with planted jumps up to a session's range."""
OFFSETS_MS = (0, -100, 100, -1, 1, -1_000, 1_000)
"""Milliseconds from a record to a decision instant drawn beside it."""
BAR_TIMEFRAMES = (
    Timeframe(count=1, unit=TimeUnit.SECOND),
    Timeframe(count=1, unit=TimeUnit.MINUTE),
    Timeframe(count=5, unit=TimeUnit.MINUTE),
    Timeframe(count=1, unit=TimeUnit.DAY),
)
"""The bars a drawn walk of trades may be replayed as: each bucket of the UTC clock that holds a
trade, a day's bucket being the UTC day."""


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


class DrawnTapes(StrEnum):
    """What drawn cases replay: trades or TBBO records, or the bars of 1 second, 1 minute,
    5 minutes, or a UTC day that a walk of trades makes."""

    TICKS = "ticks"
    BARS = "bars"


def drawn_cases(tapes: DrawnTapes = DrawnTapes.TICKS) -> "SearchStrategy[EngineCase]":
    """The strategy of one drawn case of either kind on `tapes`."""
    from hypothesis import strategies as st

    return st.one_of(order_cases(tapes), template_cases(tapes))


def order_cases(tapes: DrawnTapes) -> "SearchStrategy[EngineCase]":
    """The strategy of one drawn order case on `tapes`."""
    from hypothesis import strategies as st

    @st.composite
    def drawn_case(draw: "DrawFn") -> EngineCase:
        drawn = draw(st.sampled_from(INSTRUMENTS))
        fidelity, tape = _fidelity_and_tape(draw, drawn, tapes)
        scenario = Scenario.model_construct(
            id="a drawn case",
            title="a drawn case",
            fidelity=fidelity,
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
        replay = draw(st.sampled_from(tuple(Replay)))
        return EngineCase(scenario, _hours(draw, tape), replay=replay)

    return drawn_case()


def template_cases(tapes: DrawnTapes) -> "SearchStrategy[EngineCase]":
    """The strategy of one drawn template case on `tapes`: the execution template's basic
    subset (`fefat.reference.template`) over drawn signal rows."""
    from hypothesis import strategies as st

    @st.composite
    def drawn_template(draw: "DrawFn") -> EngineCase:
        drawn = draw(st.sampled_from(INSTRUMENTS))
        fidelity, tape = _fidelity_and_tape(draw, drawn, tapes)
        spec, at_columns = _template_spec(draw, drawn)
        scenario = TemplateScenario.model_construct(
            id="a drawn template",
            title="a drawn template",
            fidelity=fidelity,
            instrument=drawn.instrument,
            settings=_settings(draw),
            fees=None,
            position=None,
            tape=tape,
            funding=(),
            expected=Expected.model_construct(fills=(), marks=(), funding=()),
            rules=("F-CLK-01",),
            strategy=spec,
            signals=_signal_rows(draw, drawn, tape, at_columns),
        )
        replay = draw(st.sampled_from(tuple(Replay)))
        return EngineCase(scenario, _hours(draw, tape), replay=replay)

    return drawn_template()


def _fidelity_and_tape(
    draw: "DrawFn", drawn: DrawnInstrument, tapes: DrawnTapes
) -> tuple[TickFidelity | Timeframe, Tape]:
    """On ticks, a tape of TBBO records or of trades; on bars, the bars of a drawn timeframe that
    a walk of trades makes; with its fidelity."""
    from hypothesis import strategies as st

    if tapes is DrawnTapes.TICKS:
        if draw(st.booleans()):
            return TickFidelity.TBBO, _tape(draw, drawn, tbbo=True)
        return TickFidelity.TRADES, _tape(draw, drawn, tbbo=False)
    trades = _tape(draw, drawn, tbbo=False)
    timeframe = draw(st.sampled_from(BAR_TIMEFRAMES))
    return timeframe, coarser_bars(trades, timeframe)


def _template_spec(draw: "DrawFn", drawn: DrawnInstrument) -> tuple[StrategySpec, bool]:
    """A spec of the basic subset: a market entry, a stop in ticks or at the `stop_price` column,
    a target in ticks, as an R multiple of a stop in ticks, or at the `target_price` column, one
    or two lots, and signal exits on or off; and whether a leg reads a column."""
    from hypothesis import strategies as st

    stop = draw(
        st.sampled_from(({"kind": "ticks", "ticks": draw(st.integers(1, 12))}, {"kind": "column"}))
    )
    targets: list[dict[str, object]] = [
        {"kind": "ticks", "ticks": draw(st.integers(1, 12))},
        {"kind": "column"},
    ]
    if stop["kind"] == "ticks":
        targets.append({"kind": "r_multiple", "multiple": draw(st.sampled_from((1.0, 2.0, 3.0)))})
    target = draw(st.sampled_from(targets))
    execution = {
        "entry": {"kind": "market"},
        "stop": stop,
        "targets": [{"price": target}],
        "sizing": {"kind": "fixed", "units": float(drawn.quantity(draw(st.integers(1, 2))))},
        "signal_exit": draw(st.booleans()),
    }
    document = {"spec_version": 1, "instrument": "ES", "timeframe": "1m", "execution": execution}
    at_columns = stop["kind"] == "column" or target["kind"] == "column"
    return StrategySpec.model_validate(document), at_columns


def _signal_rows(
    draw: "DrawFn", drawn: DrawnInstrument, tape: Tape, at_columns: bool
) -> tuple[SignalRow, ...]:
    """One to five signal closes beside the tape's records, each with at most one entry signal,
    its exit signals, and its wake; prices for the column legs, a stop on the losing side of its
    target, on every row when a leg reads a column; and a size multiple on every row or none."""
    from hypothesis import strategies as st

    beside = st.tuples(st.integers(0, len(tape) - 1), st.sampled_from(OFFSETS_MS))
    drawn_closes = draw(st.lists(beside, min_size=1, max_size=5))
    closes = sorted(
        {tape[record].available_at() + offset * MILLISECOND for record, offset in drawn_closes}
    )
    sized = draw(st.booleans())
    rows = []
    for ts_close in closes:
        entry = draw(st.sampled_from(("long", "none", "short")))
        away = (Side.SELL if entry == "short" else Side.BUY).sign() * drawn.tick
        stop_price = target_price = None
        if at_columns:
            stop_price = drawn.opening - draw(st.integers(1, 12)) * away
            target_price = drawn.opening + draw(st.integers(1, 12)) * away
        rows.append(
            SignalRow.model_construct(
                ts_close=ts_close,
                trade_date=utc_date(ts_close),
                contract="DRAWN",
                long_entry=entry == "long",
                short_entry=entry == "short",
                long_exit=draw(st.booleans()),
                short_exit=draw(st.booleans()),
                entry_price=None,
                stop_price=stop_price,
                target_price=target_price,
                trail_ref=None,
                size_mult=float(draw(st.integers(1, 2))) if sized else None,
                wake=draw(st.sampled_from((True, True, False))),
            )
        )
    return tuple(rows)


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


def _orders(draw: "DrawFn", drawn: DrawnInstrument, tape: Tape) -> tuple[Order, ...]:
    from hypothesis import strategies as st

    beside = st.tuples(st.integers(0, len(tape) - 1), st.sampled_from(OFFSETS_MS))
    instants = sorted(
        {
            tape[record].available_at() + offset * MILLISECOND
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


def _hours(draw: "DrawFn", tape: Tape) -> AlwaysOpen | CalendarHours:
    """Always open, or closed from one record's instant to another's, both included: on bars,
    from one bar's close to another's."""
    from hypothesis import strategies as st

    if not draw(st.booleans()):
        return AlwaysOpen()
    first, second = draw(st.integers(0, len(tape) - 1)), draw(st.integers(0, len(tape) - 1))
    closes = tape[min(first, second)].available_at()
    opens = tape[max(first, second)].available_at() + 1
    before = Session.model_construct(
        trade_date=utc_date(FIRST) - timedelta(days=1), open=FIRST - DAY, close=closes, halts=()
    )
    after = Session.model_construct(
        trade_date=utc_date(FIRST), open=opens, close=tape[-1].available_at() + DAY, halts=()
    )
    return CalendarHours([before, after])
