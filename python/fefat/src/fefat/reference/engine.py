"""The reference engine (step 2.2; D-10, ADR-0008): a slow, readable implementation of
`docs/spec/fill-semantics.md`, which the Rust engine must match integer for integer.

`ReferenceEngine.run` reads one tape (trades, TBBO records, or stored bars) with a perpetual's
funding times and a strategy's decisions, in the order of F-CLK-02. At each decision it calls
the strategy (`fefat.reference.strategy`). It fills orders by the rules of the specification,
each a small function below named after its identifier (`f_stp_03` is F-STP-03), and logs each
placement, activation, trigger, fill, and cancellation with its rule, so that a fill can be
followed from the tape to the log. Prices count 1e-9 units, money micro-units, quantities lots,
and instants nanoseconds since the Unix epoch, UTC (`fefat.reference.units`):

    engine = ReferenceEngine(settings, instrument_parameters(instrument), fidelity, hours)
    result = engine.run(tape, decisions, on_bar)
    result.fills, result.log.lines()
"""

from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction

from fefat.market.fees import CryptoFee, FuturesFee
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe
from fefat.reference.event_log import EventKind, EventLog
from fefat.reference.exit_plan import Move, f_pln_02, f_pln_04, place_exit_plan
from fefat.reference.hours import TradingHours
from fefat.reference.ledger import Fill, FillFlag, FundingPayment, Liquidity, Mark
from fefat.reference.money import f_fee_01, f_fee_02, f_fee_03, f_fnd_01
from fefat.reference.orders import Book, OrderKind, OrderState, Side, WorkingOrder
from fefat.reference.settings import LimitFill, RunSettings
from fefat.reference.strategy import Decision, DecisionContext, OnBar
from fefat.reference.tape import BarRecord, FundingRate, Record, TbboRecord, TradeRecord
from fefat.reference.timeline import Event, Execution, Extreme, Moment, Phase, Priced, RunResult
from fefat.reference.units import InstrumentParameters, instant_text

STOP, MARKET, LIMIT = OrderKind.STOP, OrderKind.MARKET, OrderKind.LIMIT
WAITING, WORKING, TRIGGERED = OrderState.WAITING, OrderState.WORKING, OrderState.TRIGGERED
BUY = Side.BUY


# §3 Clock and order of events
def f_clk_01(record: Record) -> int:
    """The clock is when a record became available: `ts_recv` for trades and TBBO records,
    never the exchange's `ts_event`, and `ts_close` for bars."""
    return record.available_at()


def f_clk_02(event: Event) -> tuple[int, int]:
    """At one instant: the bars closing then, timers, activations, the records received then,
    and last the bar-close decision (`Phase`)."""
    return (event.ts, event.phase)


def f_clk_03(events: list[Event]) -> list[Event]:
    """Records received at one instant keep the tape's order, the vendor's: the sort is stable."""
    return sorted(events, key=f_clk_02)


# §4 Activation
def f_act_01(order: WorkingOrder, record_ts: int, index: int) -> bool:
    """On trades and TBBO an order sees the records after the decision that placed it (or the
    record that filled its entry) received at or after its activation."""
    return index > order.seen_after and record_ts >= order.activation


def f_act_02(order: WorkingOrder, bar: BarRecord) -> bool:
    """On bars an order sees the first bar closing after its activation, whole, and every later."""
    return bar.ts_close > order.activation


# §5 Market orders
def f_mkt_01(side: Side, record: TbboRecord, ticks: int, tick: int) -> int:
    """On TBBO, at the quote of the first record it sees, plus the ticks."""
    return side.moved(record.quote(side)[0], ticks, tick)


def f_mkt_02(side: Side, record: TradeRecord, ticks: int, tick: int) -> int:
    """On trades, at the price of the first trade it sees, plus the ticks."""
    return side.moved(record.price, ticks, tick)


def f_mkt_03(side: Side, bar_open: int, ticks: int, tick: int) -> int:
    """On bars, at the open of the first bar it sees, plus the ticks."""
    return side.moved(bar_open, ticks, tick)


# §6 Stop-market orders
def f_stp_01(side: Side, stop: int, price: int) -> bool:
    """A buy stop triggers on a price at or above it, a sell stop at or below it (CME)."""
    return price >= stop if side is BUY else price <= stop


def f_stp_02(side: Side, stop: int, record: TbboRecord, ticks: int, tick: int) -> int:
    """On TBBO, a triggered stop fills at the next tradeable record's quote, never better than
    the stop plus the ticks."""
    return side.worse(side.moved(stop, ticks, tick), record.quote(side)[0])


def f_stp_03(side: Side, stop: int, trade_price: int, ticks: int, tick: int) -> int:
    """On trades, at the worse of the stop plus the ticks and the trigger trade's price: a gap
    fills at the gap price, with no ticks beyond it."""
    return side.worse(side.moved(stop, ticks, tick), trade_price)


def f_stp_04(side: Side, stop: int, reached_at: int, ticks: int, tick: int) -> int:
    """On bars, at the stop plus the ticks where the path reaches it, and at the worse of that
    and the open when the bar opens past it (`reached_at` is the open then, else the stop)."""
    return side.worse(side.moved(stop, ticks, tick), reached_at)


def f_stp_05(side: Side, stop: int, market: int | None) -> bool:
    """A stop at or through the market when it becomes active fills at once as a market order,
    with the larger class's ticks; with no price seen yet it is on the right side."""
    return market is not None and (stop <= market if side is BUY else stop >= market)


# §7 Limit orders
def f_lmt_01(side: Side, limit: int, price: int) -> bool:
    """A limit fills when the market trades through it: a buy on a price below its limit."""
    return price < limit if side is BUY else price > limit


def f_lmt_02(side: Side, limit: int, price: int) -> bool:
    """With `limit_fill: touch` a price at the limit is enough; on TBBO a quote at or past the
    limit fills it whatever the setting (F-LMT-01)."""
    return price <= limit if side is BUY else price >= limit


def f_lmt_03(order: WorkingOrder) -> int:
    """A limit fills at its own price, never better, even when the market jumps past it."""
    return order.level()


def f_lmt_04(order: WorkingOrder) -> Liquidity:
    """A limit filled on the first price it sees is a taker, one filled later rested and is a
    maker; market and stop fills are takers."""
    return Liquidity.MAKER if order.kind is LIMIT and order.rested else Liquidity.TAKER


# §8 Replaying bars
def f_bar_01(order: WorkingOrder, point: int, extreme: int, touch: bool) -> int | None:
    """Between two pseudo-ticks the path passes every price: it reaches a stop at its price and
    a limit where it trades through it (or touches it); only the open can jump past a level.
    The level the path from `point` to `extreme` reaches `order` at, or None."""
    low, high, level = min(point, extreme), max(point, extreme), order.level()
    if order.kind is STOP:
        return level if low <= level <= high else None
    fills = f_lmt_02 if touch else f_lmt_01
    reached = fills(order.side, level, low if order.side is BUY else high)
    return min(max(level, low), high) if reached else None


def f_bar_02(position: int) -> Extreme:
    """Holding a position after the open, the adverse extreme comes first: the low for a long."""
    return Extreme.LOW if position > 0 else Extreme.HIGH


def f_bar_03(working: list[WorkingOrder]) -> Extreme:
    """Flat after the open, the extreme favourable to the earliest placed working entry comes
    first, the lower id at one instant: the high for a buy. With none, the order is moot."""
    if not working:
        return Extreme.LOW
    earliest = min(working, key=lambda order: (order.placed_at, order.id))
    return Extreme.HIGH if earliest.side is BUY else Extreme.LOW


def f_bar_04(remaining: list[Extreme], position: int) -> list[Extreme]:
    """After an entry fills inside a bar, the extremes not yet reached come adverse first for the
    new position (F-BAR-02), and then the close."""
    return sorted(remaining, key=lambda extreme: extreme is not f_bar_02(position))


def f_bar_05(real: list[Execution], swapped: list[Execution]) -> bool:
    """A bar is ambiguous when replaying it with its extremes the other way round gives other
    fills: another order, another price, or none."""
    fills = {(execution.order.id, execution.price) for execution in real}
    return fills != {(execution.order.id, execution.price) for execution in swapped}


def f_bar_06(bar: BarRecord) -> int:
    """A bar's pseudo-ticks happen at its close, when it is available, and its fills carry it."""
    return bar.ts_close


def f_bar_07(bar: BarRecord) -> None:
    """Only stored bars are replayed: a bucket without trades has none, so the `zero_volume`
    rows of the session grid never reach the engine."""
    if bar.volume <= 0:
        at = instant_text(bar.ts_close)
        raise ValueError(f"Expected stored bars with trades (F-BAR-07), got none closing {at}.")


# §10 Sessions and breaks
def f_ses_01(log: EventLog, ts: int, live: list[WorkingOrder]) -> None:
    """Orders are good till cancelled: the engine cancels nothing at a session's close, and the
    working orders stay through the break."""
    if live:
        ids = ", ".join(str(order.id) for order in live)
        log.note(ts, EventKind.BREAK, f"the market is closed; orders {ids} stay", rule="F-SES-01")


def f_ses_02(hours: TradingHours, instant: int) -> bool:
    """Records received in a break or a halt, and bars that open there, are not tradeable:
    nothing triggers or fills on them, and they set no mark."""
    return hours.is_open(instant)


# §11 Brackets and OCO groups
def f_oco_01(book: Book, filled: WorkingOrder) -> tuple[WorkingOrder, ...]:
    """When an order of an OCO group fills, the others are cancelled at once, so the record or
    pseudo-tick that filled it cannot fill them."""
    if filled.oco is None:
        return ()
    group = tuple(order for order in book.live() if order.oco == filled.oco)
    for order in group:
        book.close(order, OrderState.CANCELLED)
    return group


def f_oco_02(
    book: Book, entry: WorkingOrder, price: int, market: int, at: Moment, tick: int
) -> list[WorkingOrder]:
    """An entry's bracket, its exit plan's stop and targets (F-PLN-01), is placed when it fills
    at `price`, the market at `market`, without latency, working from the next record after
    the fill or, on bars, from the entry's point of the path."""
    return place_exit_plan(book, entry, price, market, at.ts, at.index, tick)


# §12 to §16 Slippage, quantities, marks, and what a fill records; money in `fefat.reference.money`
def f_slp_01(settings: RunSettings, kind: OrderKind) -> int:
    """Slippage is whole ticks per order class, market or stop-market, set for the run."""
    return settings.slippage_ticks.market if kind is MARKET else settings.slippage_ticks.stop


def f_qty_01(lots: int, shown_size: int | None) -> tuple[FillFlag, ...]:
    """Orders fill whole; on trades and TBBO a fill larger than its record shows is flagged."""
    return (FillFlag.SIZE_EXCEEDED,) if shown_size is not None and lots > shown_size else ()


def f_mrk_01(book: Book, price: int) -> None:
    """A position is marked at the last trade seen, on bar days the last pseudo-tick; a fill
    does not move the mark, and records that are not tradeable set none."""
    book.mark = price


def f_tag_01(execution: Execution, ts: int, fidelity: TickFidelity | Timeframe, tick: int) -> Fill:
    """Every fill records its fidelity, the rule that priced it, its liquidity, its flags, and
    its slippage, the ticks it is worse than its reference by; its money is booked after."""
    order = execution.order
    return Fill(
        order=order.id,
        role=order.role,
        side=order.side,
        lots=order.lots,
        ts=ts,
        price=execution.price,
        rule=execution.rule,
        fidelity=fidelity,
        liquidity=execution.liquidity,
        slippage_ticks=order.side.sign() * (execution.price - execution.reference) // tick,
        flags=f_qty_01(order.lots, execution.shown_size),
    )


class ReferenceEngine:
    """One run of the reference engine over one instrument (module docstring)."""

    def __init__(
        self,
        settings: RunSettings,
        instrument: InstrumentParameters,
        fidelity: TickFidelity | Timeframe,
        hours: TradingHours,
        fees: FuturesFee | CryptoFee | None = None,
    ) -> None:
        self.settings, self.fidelity, self.hours, self.fees = settings, fidelity, hours, fees
        self.instrument, self.tick = instrument, instrument.tick
        self.touch = settings.limit_fill is LimitFill.TOUCH

    def run(
        self,
        tape: Sequence[Record],
        decisions: Sequence[Decision] = (),
        on_bar: OnBar | None = None,
        funding_rates: Sequence[FundingRate] = (),
        position: int = 0,
    ) -> RunResult:
        """Runs `tape` with the funding times and the decisions, calling `on_bar` at each, from
        `position` lots held when it starts (positive long)."""
        if decisions and on_bar is None:
            raise ValueError("Expected an on_bar strategy for the decisions, got none.")
        self.book, self.log = Book(position=position), EventLog()
        self.in_break = False
        self.fills: list[Fill] = []
        self.funding: list[FundingPayment] = []
        self.marks: list[Mark] = []
        events = self._events(tape, decisions, funding_rates)
        for index, event in enumerate(events):
            self._on_event(Moment(event.ts, index), event, on_bar)
            last_of_instant = index + 1 == len(events) or events[index + 1].ts != event.ts
            if last_of_instant and self.book.position != 0 and self.book.mark is not None:
                self.marks.append(Mark(ts=event.ts, price=self.book.mark))
        fills, funding, marks = tuple(self.fills), tuple(self.funding), tuple(self.marks)
        return RunResult(fills, funding, marks, self.log, self.book.position)

    def _events(
        self, tape: Sequence[Record], decisions: Sequence[Decision], rates: Sequence[FundingRate]
    ) -> list[Event]:
        expected = TradeRecord if self.fidelity is TickFidelity.TRADES else TbboRecord
        expected = BarRecord if isinstance(self.fidelity, Timeframe) else expected
        wrong = [number for number, record in enumerate(tape) if type(record) is not expected]
        if wrong:
            named = f"{expected.__name__} for fidelity {self.fidelity}"
            got = f"a {type(tape[wrong[0]]).__name__} as record {wrong[0] + 1}"
            raise ValueError(f"Expected a tape of {named}, got {got}.")
        phase = Phase.BARS if expected is BarRecord else Phase.RECORDS
        events = [Event(f_clk_01(record), phase, record) for record in tape]
        events += [Event(rate.ts, Phase.TIMERS, rate) for rate in rates]
        events += [Event(decision.ts, Phase.DECISIONS, decision) for decision in decisions]
        return f_clk_03(events)

    def _on_event(self, at: Moment, event: Event, on_bar: OnBar | None) -> None:
        subject = event.subject
        if isinstance(subject, Decision) and on_bar is not None:
            latency = self.settings.latency_nanoseconds()
            context = DecisionContext(
                self.book, at.ts, at.index, latency, self.instrument, self.log
            )
            on_bar(subject.bar, context)
        elif isinstance(subject, FundingRate):
            self._on_funding(subject)
        elif isinstance(subject, BarRecord):
            self._on_bar(at, subject)
        elif isinstance(subject, TradeRecord):
            self._on_record(at, subject)

    def _tradeable(self, instant: int) -> bool:
        tradeable = f_ses_02(self.hours, instant)
        if not tradeable and not self.in_break:
            f_ses_01(self.log, instant, self.book.live())
        self.in_break = not tradeable
        return tradeable

    def ticks(self, kind: OrderKind, through: bool = False) -> int:
        """A class's slippage ticks; a stop through the market takes the larger (F-STP-05)."""
        larger = max(f_slp_01(self.settings, MARKET), f_slp_01(self.settings, STOP))
        return larger if through else f_slp_01(self.settings, kind)

    def limit_past(self, order: WorkingOrder, price: int) -> bool:
        """Whether `price` fills a limit: through it (F-LMT-01), or at it with touch (F-LMT-02)."""
        return (f_lmt_02 if self.touch else f_lmt_01)(order.side, order.level(), price)

    def _on_record(self, at: Moment, record: TradeRecord) -> None:
        """A trade or TBBO record: the stops the record before triggered, market orders since,
        which fill before the orders that become active on this record (F-STP-02); the orders
        that see their first record; the stops this one triggers; then the limits, so that a stop
        beats a limit of its group (F-OCO-01); then the mark."""
        if not self._tradeable(at.ts):
            return
        for order in self.book.each(TRIGGERED):
            if isinstance(record, TbboRecord):
                price = f_stp_02(order.side, order.level(), record, self.ticks(STOP), self.tick)
                shown = record.quote(order.side)[1]
                priced = Priced(price, "F-STP-02", order.level(), shown)
                self._fill(at, order, priced, record.price)
        for order in self.book.each(WAITING):
            if f_act_01(order, at.ts, at.index):
                self._first_record(at, order, record)
        for order in self.book.each(WORKING, STOP):
            if f_stp_01(order.side, order.level(), record.price):
                self._triggered(at, order, record)
        for order in self.book.each(WORKING, LIMIT):
            self._limit_on_record(at, order, record)
        f_mrk_01(self.book, record.price)
        for move in f_pln_04(self.book, record.price, self.tick):
            self._moved(at.ts, move)

    def _first_record(self, at: Moment, order: WorkingOrder, record: TradeRecord) -> None:
        order.state = WORKING
        through = order.kind is STOP and f_stp_05(order.side, order.level(), self.book.mark)
        if order.kind is not MARKET and not through:
            self.log.active(at.ts, order.id, "record", "F-ACT-01")
            return
        ticks = self.ticks(MARKET, through)
        if isinstance(record, TbboRecord):
            (reference, shown), rule = record.quote(order.side), "F-MKT-01"
            price = f_mkt_01(order.side, record, ticks, self.tick)
        else:
            reference, shown, rule = record.price, record.size, "F-MKT-02"
            price = f_mkt_02(order.side, record, ticks, self.tick)
        priced = Priced(price, "F-STP-05" if through else rule, reference, shown)
        self._fill(at, order, priced, record.price)

    def _triggered(self, at: Moment, order: WorkingOrder, record: TradeRecord) -> None:
        stop = order.level()
        self.log.triggered(at.ts, order, record.price)
        if isinstance(record, TbboRecord):
            order.state = TRIGGERED
            return
        price = f_stp_03(order.side, stop, record.price, self.ticks(STOP), self.tick)
        self._fill(at, order, Priced(price, "F-STP-03", stop, record.size), record.price)

    def _limit_on_record(self, at: Moment, order: WorkingOrder, record: TradeRecord) -> None:
        traded, shown = self.limit_past(order, record.price), record.size
        if isinstance(record, TbboRecord) and not traded:
            price, shown = record.quote(order.side)
            traded = f_lmt_02(order.side, order.level(), price)
        if not traded:
            order.rested = True
            return
        priced = Priced(f_lmt_03(order), "F-LMT-03", order.level(), shown)
        self._fill(at, order, priced, record.price)

    def _fill(self, at: Moment, order: WorkingOrder, priced: Priced, market: int) -> None:
        self._book(at.ts, self.execute(self.book, order, priced, at, market))

    def _moved(self, ts: int, move: Move) -> None:
        self.log.moved(ts, move.order, move.before, move.after, move.rule)

    def _on_bar(self, moment: Moment, bar: BarRecord) -> None:
        """A stored bar, replayed as its pseudo-ticks; when it fills anything, replayed again on a
        copy with its extremes the other way round, to tell whether it is ambiguous (F-BAR-05)."""
        f_bar_07(bar)
        if not self._tradeable(bar.ts_open):
            return
        at = Moment(f_bar_06(bar), moment.index)
        for order in self.book.live(WAITING):
            if f_act_02(order, bar):
                self.log.active(at.ts, order.id, "bar", "F-ACT-02")
        trial = self.book.copied()
        events = BarReplay(self, self.book, at).run(bar, swapped=False)
        executions = [event for event in events if isinstance(event, Execution)]
        swapped = BarReplay(self, trial, at).run(bar, swapped=True) if executions else []
        others = [event for event in swapped if isinstance(event, Execution)]
        flags = (FillFlag.AMBIGUOUS,) if f_bar_05(executions, others) else ()
        if flags:
            self.log.ambiguous(at.ts)
        for event in events:
            if isinstance(event, Execution):
                self._book(at.ts, event, flags)
            else:
                self._moved(at.ts, event)

    def execute(
        self, book: Book, order: WorkingOrder, priced: Priced, at: Moment, market: int
    ) -> Execution:
        """Fills `order` in `book` as `priced` says, the market at `market`: the position moves,
        its OCO group is cancelled (F-OCO-01), its exit plan settles its open lots (F-PLN-02),
        and the exit plan of an entry is placed (F-OCO-02)."""
        price, rule, reference, shown = priced
        liquidity = f_lmt_04(order)
        book.close(order, OrderState.FILLED)
        book.take(order.side.sign() * order.lots, at.ts)
        settled = f_pln_02(book, order)
        cancelled = (*f_oco_01(book, order), *settled.cancelled)
        legs = tuple(f_oco_02(book, order, price, market, at, self.tick))
        execution = Execution(order, price, rule, reference, liquidity, shown, cancelled, legs)
        return replace(execution, reduced=settled.reduced)

    def _book(self, ts: int, execution: Execution, flags: tuple[FillFlag, ...] = ()) -> None:
        """Books a fill: its value moves the cash and it pays its fee, each rounded once
        (F-FEE-01 to F-FEE-03), and the fill goes to the log."""
        order = execution.order
        value = self.instrument.value(execution.price, order.lots)
        booked = f"the money of order {order.id}'s fill at {instant_text(ts)}"
        cash = f_fee_03(-order.side.sign() * value, booked)
        fee = -f_fee_03(-self._fee(value, execution), booked)
        fill = f_tag_01(execution, ts, self.fidelity, self.tick)
        fill = fill.model_copy(update={"flags": (*flags, *fill.flags), "fee": fee, "cash": cash})
        self.fills.append(fill)
        self.log.filled(fill, execution.cancelled, execution.bracket, execution.reduced)

    def _fee(self, value: Fraction, execution: Execution) -> Fraction:
        if isinstance(self.fees, FuturesFee):
            return f_fee_01(self.fees, execution.order.lots * self.instrument.lot_step)
        if isinstance(self.fees, CryptoFee):
            return f_fee_02(self.fees, value, execution.liquidity)
        return Fraction(0)

    def _on_funding(self, rate: FundingRate) -> None:
        """A funding time: an open position pays or receives at the mark (F-FND-01)."""
        mark = self.book.mark
        if self.book.position == 0:
            return
        if mark is None:
            raise ValueError(f"Expected a mark at the funding {instant_text(rate.ts)}, got none.")
        owed = f_fnd_01(self.book.position, mark, self.instrument, rate.rate)
        change = f_fee_03(owed, f"the funding at {instant_text(rate.ts)}")
        self.funding.append(FundingPayment(ts=rate.ts, amount=change))
        self.log.funded(rate.ts, change, mark)


class BarReplay:
    """One bar replayed on one book as four pseudo-ticks (F-BAR-01): its open, its extremes in the
    order F-BAR-02 to F-BAR-04 give, and its close; the test of F-BAR-05 replays on a copy, with
    the first choice of extreme swapped."""

    def __init__(self, engine: ReferenceEngine, book: Book, at: Moment) -> None:
        self.engine, self.book, self.at, self.tick = engine, book, at, engine.tick
        self.stop_ticks, self.through_ticks = engine.ticks(STOP), engine.ticks(MARKET, through=True)
        self.events: list[Execution | Move] = []

    def run(self, bar: BarRecord, swapped: bool) -> list[Execution | Move]:
        self.open(bar)
        book = self.book
        first = f_bar_02(book.position) if book.position else f_bar_03(book.live(WORKING))
        remaining = [first, Extreme.HIGH if first is Extreme.LOW else Extreme.LOW]
        if swapped:
            remaining.reverse()
        point = bar.open
        while remaining:
            extreme = bar.low if remaining[0] is Extreme.LOW else bar.high
            point, opened = self.leg(point, extreme)
            if point == extreme:
                self.marked(extreme)
                remaining.pop(0)
            if opened:
                remaining = f_bar_04(remaining, book.position)
        self.leg(point, bar.close)
        self.marked(bar.close)
        return self.events

    def marked(self, price: int) -> None:
        """A point of the path marked (F-MRK-01), and each exit plan's turn at it (F-PLN-04)."""
        f_mrk_01(self.book, price)
        self.events.extend(f_pln_04(self.book, price, self.tick))

    def open(self, bar: BarRecord) -> None:
        """The open's pseudo-tick: market orders and stops through the market that see their first
        bar, then the stops and the limits the open is past, by id in each class."""
        engine, point = self.engine, bar.open
        for order in self.book.each(WAITING):
            if not f_act_02(order, bar):
                continue
            order.state = WORKING
            through = order.kind is STOP and f_stp_05(order.side, order.level(), self.book.mark)
            if order.kind is MARKET or through:
                price = f_mkt_03(order.side, point, engine.ticks(MARKET, through), self.tick)
                self.fill(point, order, price, "F-STP-05" if through else "F-MKT-03", point)
        for order in self.book.each(WORKING, STOP):
            if f_stp_01(order.side, order.level(), point):
                price = f_stp_04(order.side, order.level(), point, self.stop_ticks, self.tick)
                self.fill(point, order, price, "F-STP-04", order.level())
        for order in self.book.each(WORKING, LIMIT):
            if engine.limit_past(order, point):
                self.fill(point, order, f_lmt_03(order), "F-LMT-03", order.level())
        for order in self.book.live(WORKING, kind=LIMIT):
            order.rested = True
        self.marked(point)

    def leg(self, point: int, extreme: int) -> tuple[int, bool]:
        """The path from `point` to `extreme`: the nearest level first, all its orders together,
        stops before limits (F-OCO-01). It ends at the extreme, or where a fill opens a position,
        from flat or by reversing one (F-BAR-04): the point reached, and whether one opened."""
        touch = self.engine.touch
        while True:
            working = self.book.live(WORKING)
            levels = {order.id: f_bar_01(order, point, extreme, touch) for order in working}
            reached = [level for level in levels.values() if level is not None]
            if not reached:
                return extreme, False
            nearest = min(reached, key=lambda level: abs(level - point))
            batch = [order for order in working if levels[order.id] == nearest]
            before = self.book.position
            for order in sorted(batch, key=lambda order: (order.kind is not STOP, order.id)):
                if order.state is WORKING and order.kind is STOP:
                    price = f_stp_04(order.side, nearest, nearest, self.stop_ticks, self.tick)
                    self.fill(nearest, order, price, "F-STP-04", nearest)
                elif order.state is WORKING:
                    self.fill(nearest, order, f_lmt_03(order), "F-LMT-03", order.level())
            point = nearest
            if self.book.position != 0 and self.book.position * before <= 0:
                return point, True

    def fill(self, point: int, order: WorkingOrder, price: int, rule: str, reference: int) -> None:
        """A fill at a point of the path, whose bracket's legs are judged there at once (F-OCO-02,
        F-STP-05): a stop or a target the point is through fills, and the rest work from it."""
        priced = Priced(price, rule, reference, None)
        execution = self.engine.execute(self.book, order, priced, self.at, point)
        self.events.append(execution)
        for leg in execution.bracket:
            if leg.state is not WAITING:
                continue
            leg.state = WORKING
            if leg.kind is STOP and f_stp_05(leg.side, leg.level(), point):
                price = f_mkt_03(leg.side, point, self.through_ticks, self.tick)
                self.fill(point, leg, price, "F-STP-05", point)
            elif leg.kind is LIMIT and self.engine.limit_past(leg, point):
                self.fill(point, leg, f_lmt_03(leg), "F-LMT-03", leg.level())
            elif leg.kind is LIMIT:
                leg.rested = True
