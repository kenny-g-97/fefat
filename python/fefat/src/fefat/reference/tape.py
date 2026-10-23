"""The tape of a fill scenario: trade prints, TBBO records, or stored bars, as its fidelity
says, in the order the engine reads them (`docs/spec/fill-semantics.md`, F-CLK-01)."""

import itertools
from typing import Annotated, Self

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from fefat.market.fidelity import TickFidelity
from fefat.market.schema import FrozenModel, Timeframe, TimeUnit
from fefat.reference.units import Instant, Price, instant_text, price_text

Count = Annotated[int, Field(gt=0)]
"""A size or a volume, in the dataset's size unit."""


class TradeRecord(FrozenModel):
    """A trade print of a `trades` tape, received at `ts`; `ts_event`, the exchange's time
    of the trade, may be given to show that the engine never reads it (F-CLK-01)."""

    ts: Instant
    ts_event: Instant | None = None
    price: Price
    size: Count

    def starts_at(self) -> int:
        return self.ts

    def available_at(self) -> int:
        return self.ts

    def prices(self) -> tuple[int, ...]:
        return (self.price,)


class TbboRecord(TradeRecord):
    """A trade of a `tbbo` tape with the best bid and ask just before it."""

    bid: Price
    ask: Price
    bid_size: Count
    ask_size: Count

    @model_validator(mode="after")
    def _bid_below_ask(self) -> Self:
        if self.bid >= self.ask:
            raise ValueError(
                f"Expected a bid below the ask, got {price_text(self.bid)} and "
                f"{price_text(self.ask)}."
            )
        return self

    def prices(self) -> tuple[int, ...]:
        return (self.price, self.bid, self.ask)


class BarRecord(FrozenModel):
    """A stored bar of the trades received in `[ts_open, ts_close)`, available at `ts_close`."""

    ts_open: Instant
    ts_close: Instant
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Count

    @model_validator(mode="after")
    def _a_bar_holds_its_prices(self) -> Self:
        if self.ts_open >= self.ts_close:
            raise ValueError(
                f"Expected a bar to open before it closes, got ts_open "
                f"{instant_text(self.ts_open)} and ts_close {instant_text(self.ts_close)}."
            )
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            prices = ", ".join(price_text(price) for price in self.prices())
            raise ValueError(
                "Expected a bar's low and high around its open and close, got open, high, low, "
                f"and close {prices}."
            )
        return self

    def starts_at(self) -> int:
        return self.ts_open

    def available_at(self) -> int:
        return self.ts_close

    def prices(self) -> tuple[int, ...]:
        return (self.open, self.high, self.low, self.close)


Tape = tuple[TradeRecord, ...] | tuple[TbboRecord, ...] | tuple[BarRecord, ...]
"""The records of one fidelity, in the order the engine reads them."""

_TRADES = TypeAdapter(tuple[TradeRecord, ...])
_TBBO_RECORDS = TypeAdapter(tuple[TbboRecord, ...])
_BARS = TypeAdapter(tuple[BarRecord, ...])


def parse_tape(fidelity: TickFidelity | Timeframe, raw: object) -> Tape:
    """`raw` read as the records `fidelity` names: bars of a timeframe, TBBO records, or
    trades, so that an error names the record and the field that break it."""
    if isinstance(fidelity, Timeframe):
        return _parsed(_BARS, "bars", fidelity, raw)
    if fidelity is TickFidelity.TBBO:
        return _parsed(_TBBO_RECORDS, "TBBO records", fidelity, raw)
    return _parsed(_TRADES, "trades", fidelity, raw)


def _parsed[Records](
    adapter: TypeAdapter[Records], words: str, fidelity: TickFidelity | Timeframe, raw: object
) -> Records:
    try:
        return adapter.validate_python(raw)
    except ValidationError as error:
        raise ValueError(
            f"Expected a tape of {words} for fidelity {fidelity}, got: {error}"
        ) from None


def check_tape(fidelity: TickFidelity | Timeframe, tape: Tape) -> None:
    """Refuse an empty tape, a bar longer than its timeframe (a daily bar is a session, which a
    holiday can stretch past a day), and records out of time order: each record starts no
    earlier than the one before it is received."""
    if not tape:
        raise ValueError("Expected a tape of one record or more, got none.")
    if isinstance(fidelity, Timeframe) and fidelity.unit is not TimeUnit.DAY:
        longest = fidelity.nominal_nanoseconds()
        spans = (record.available_at() - record.starts_at() for record in tape)
        longer = [str(number) for number, span in enumerate(spans, start=1) if span > longest]
        if longer:
            raise ValueError(
                f"Expected bars of {fidelity} at most, got record {', '.join(longer)} longer."
            )
    for number, (earlier, later) in enumerate(itertools.pairwise(tape), start=2):
        if later.starts_at() < earlier.available_at():
            raise ValueError(
                f"Expected the tape in time order, got record {number} starting before record "
                f"{number - 1} is received."
            )
