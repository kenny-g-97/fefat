"""How the reference engine books what happens to the money (`docs/spec/fill-semantics.md` §13 to
§16, step 2.9): what every fill records (F-TAG-01, F-QTY-01), the cash its value moves and the fee
it pays by the fee table in force on its trade date (F-FEE-01 to F-FEE-03), and a perpetual's
funding payments (F-FND-01), each counting in the profit and loss of the trade open (§20). Each
rule is a small function named after its identifier, as in `fefat.reference.engine`, which calls
these at each fill and each funding time."""

from typing import TYPE_CHECKING

from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe
from fefat.reference.costs import fee_of
from fefat.reference.ledger import Fill, FillFlag, FundingPayment
from fefat.reference.money import f_fee_03, f_fnd_01
from fefat.reference.tape import FundingRate
from fefat.reference.timeline import Execution
from fefat.reference.units import instant_text

if TYPE_CHECKING:
    from fefat.reference.engine import ReferenceEngine


def f_qty_01(lots: int, shown_size: int | None) -> tuple[FillFlag, ...]:
    """Orders fill whole; on trades and TBBO a fill larger than its record shows is flagged."""
    return (FillFlag.SIZE_EXCEEDED,) if shown_size is not None and lots > shown_size else ()


def f_tag_01(
    execution: Execution,
    ts: int,
    fidelity: TickFidelity | Timeframe,
    tick: int,
    contract: str,
) -> Fill:
    """Every fill records its contract, its fidelity, the rule that priced it, its liquidity, its
    flags, and its slippage, the ticks it is worse than its reference by; its money is booked
    after."""
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
        contract=contract,
        flags=f_qty_01(order.lots, execution.shown_size),
    )


def book_fill(
    engine: "ReferenceEngine",
    ts: int,
    execution: Execution,
    flags: tuple[FillFlag, ...] = (),
    contract: str | None = None,
) -> None:
    """Books a fill on the front, or on `contract`, a roll's close leg's (F-ROL-02): its value
    moves the cash and it pays the fee in force on its trade date, each rounded once (F-FEE-01 to
    F-FEE-03), and the fill goes to the log, after a warning the first time the fee table's first
    schedule prices a fill before its date (F-FEE-01)."""
    order, instrument = execution.order, engine.instrument
    value = instrument.value(execution.price, order.lots)
    booked = f"the money of order {order.id}'s fill at {instant_text(ts)}"
    cash = f_fee_03(-order.side.sign() * value, booked)
    quantity = order.lots * instrument.lot_step
    exact, extended = fee_of(engine.fees, engine.trade_date, value, quantity, execution.liquidity)
    fee = -f_fee_03(-exact, booked)
    on = engine.front if contract is None else contract
    fill = f_tag_01(execution, ts, engine.fidelity, engine.tick, on)
    fill = fill.model_copy(update={"flags": (*flags, *fill.flags), "fee": fee, "cash": cash})
    if extended and not engine.warned:
        engine.warned = True
        before = "the fee table's first schedule prices a fill of a trade date before it"
        engine.log.warning(ts, f"order {order.id}: {before}", order.id, "F-FEE-01")
    engine.fills.append(fill)
    engine.book.booked(cash - fee, ts, execution.flat_after)
    engine.log.filled(fill, execution.cancelled, execution.bracket, execution.reduced)


def pay_funding(engine: "ReferenceEngine", rate: FundingRate) -> None:
    """A funding time: an open position pays or receives at the mark (F-FND-01), which counts in
    the profit and loss of the trade open (§20)."""
    book, mark = engine.book, engine.book.mark
    if book.position == 0:
        return
    if mark is None:
        raise ValueError(f"Expected a mark at the funding {instant_text(rate.ts)}, got none.")
    owed = f_fnd_01(book.position, mark, engine.instrument, rate.rate)
    change = f_fee_03(owed, f"the funding at {instant_text(rate.ts)}")
    engine.funding.append(FundingPayment(ts=rate.ts, amount=change))
    book.cash += change
    book.trade_cash += change
    engine.log.funded(rate.ts, change, mark)
