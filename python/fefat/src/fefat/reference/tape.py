"""The tape of a fill scenario: trade prints, TBBO records, or stored bars, as its fidelity
says, in the order the engine reads them (`docs/spec/fill-semantics.md`, F-CLK-01)."""

import itertools
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator

from fefat.market.schema import FrozenModel, Timeframe
from fefat.reference.units import Instant, Price, price_text

Count = Annotated[int, Field(gt=0)]
"""A size or a volume, in the dataset's size unit."""


class TickFidelity(StrEnum):
    """Tick data a scenario fills on: trades with the quote just before each, or trades."""

    TBBO = "tbbo"
    TRADES = "trades"


def _fidelity(value: object) -> object:
    """A fidelity's text as its value: `tbbo` and `trades` stay, a bar timeframe is parsed."""
    if not isinstance(value, str) or value in frozenset(TickFidelity):
        return value
    try:
        return Timeframe.parse(value)
    except ValueError:
        raise ValueError(
            "Expected a fidelity: tbbo, trades, or a bar timeframe such as 1s, 1m, 5m, or 1d, "
            f"got {value!r}."
        ) from None


Fidelity = Annotated[TickFidelity | Timeframe, BeforeValidator(_fidelity)]
"""The data a scenario fills on: `tbbo`, `trades`, or bars of a timeframe, `1s` to `1d`."""


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
            raise ValueError("Expected a bar to open before it closes.")
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

_TICK_RECORDS: dict[TickFidelity, type[TradeRecord]] = {
    TickFidelity.TBBO: TbboRecord,
    TickFidelity.TRADES: TradeRecord,
}
_RECORD_WORDS: dict[type[FrozenModel], str] = {
    TradeRecord: "trades",
    TbboRecord: "TBBO records",
    BarRecord: "bars",
}


def check_tape(fidelity: TickFidelity | Timeframe, tape: Tape) -> None:
    """Refuse a tape whose records are not those of `fidelity`, or out of time order: each
    record starts no earlier than the one before it is received."""
    wanted = BarRecord if isinstance(fidelity, Timeframe) else _TICK_RECORDS[fidelity]
    found = {type(record) for record in tape}
    if found != {wanted}:
        got = " and ".join(sorted(_RECORD_WORDS[kind] for kind in found)) or "no records"
        raise ValueError(
            f"Expected a tape of {_RECORD_WORDS[wanted]} for fidelity {fidelity}, got {got}."
        )
    for number, (earlier, later) in enumerate(itertools.pairwise(tape), start=2):
        if later.starts_at() < earlier.available_at():
            raise ValueError(
                f"Expected the tape in time order, got record {number} starting before record "
                f"{number - 1} is received."
            )
