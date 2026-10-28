"""The tape the reference engine reads: trade prints, TBBO records, or stored bars, as its
fidelity says, in the order the engine reads them (`docs/spec/fill-semantics.md`, F-CLK-01),
and a perpetual's funding rates. A scenario writes its tape (`fefat.reference.scenarios`);
`tape_of_bars` and `tape_of_trades` build one from the store's frames (step 2.2)."""

import itertools
from collections.abc import Sequence
from typing import Annotated, Self

import polars as pl
from pydantic import Field, TypeAdapter, ValidationError, model_validator

from fefat.market.calendar import SessionTable
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import FrozenModel, Timeframe, TimeUnit
from fefat.reference.orders import Side
from fefat.reference.units import Instant, Price, QuotedDecimal, instant_text, price_text

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

    def quote(self, side: Side) -> tuple[int, int]:
        """The quote an order of `side` takes, the ask for a buy, and its size, read no better than
        the record's trade (F-SLP-01): the later prints of a sweep carry the quote from before the
        sweep, so an ask below the trade counts as that trade, its price and its size, as does a
        bid above it."""
        quoted = (self.ask, self.ask_size) if side is Side.BUY else (self.bid, self.bid_size)
        if side.worse(quoted[0], self.price) == quoted[0]:
            return quoted
        return (self.price, self.size)


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
Record = TradeRecord | TbboRecord | BarRecord
"""A record of a tape: a trade print, a TBBO record, or a stored bar."""

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


class FundingRate(FrozenModel):
    """A perpetual's funding rate, paid at `ts` (F-FND-01): "0.0001" is 0.01 %."""

    ts: Instant
    rate: QuotedDecimal


NANOSECONDS_PER_DAY = 86_400 * 1_000_000_000


def trade_dates_of(records: Sequence[Record], sessions: SessionTable | None) -> list[int]:
    """Each record's trade date in days since 1970-01-01, which prices its fills' fees
    (F-FEE-01): that of the session it falls in, or of the last one opened before it, by the
    instant it starts at (`SessionTable.assign_trade_dates_or_previous`, as `load` dates them);
    the UTC day without a session table."""
    starts = [record.starts_at() for record in records]
    if sessions is None or not starts:
        return [start // NANOSECONDS_PER_DAY for start in starts]
    frame = pl.DataFrame(
        {"ts": starts, "order": range(len(starts))}, schema_overrides={"ts": pl.Int64}
    )
    dated = sessions.assign_trade_dates_or_previous(frame, "ts").sort("order")
    return dated.get_column("trade_date").cast(pl.Int32).cast(pl.Int64).to_list()


_RAW_PRICES = ("open", "high", "low", "close")


def tape_of_bars(frame: pl.DataFrame) -> tuple[BarRecord, ...]:
    """The stored bars of a frame `load` returned (`SIGNAL_BAR_COLUMNS`), as the engine replays
    them: without the rows of empty buckets, which have no stored bar (F-BAR-07), at the
    contract's raw prices, a spliced bar's open, high, low, and close less its `adj_offset`
    (D-09), and in the order of their closes. A back-adjusted import, without raw prices
    (D-49), the bars of more than one contract, and a window without trades are refused.
    The store checked each row when it was written (ADR-0019), so the records are built
    without parsing it again."""
    contracts = sorted(frame.get_column("contract").unique().to_list())
    if frame.get_column("close_raw").null_count() > 0:
        raise ValueError(
            f"Expected a series with raw prices, got a back-adjusted import of {', '.join(contracts)}, "
            "whose prices no order traded at (D-49)."
        )
    if len(contracts) > 1:
        raise ValueError(
            f"Expected the bars of one contract, got {', '.join(contracts)}: positions and "
            "working orders across a roll arrive in step 2.9, so choose a window inside one "
            "contract."
        )
    stored = frame.filter(~pl.col("zero_volume")).sort("ts_close")
    if stored.is_empty():
        raise ValueError(
            f"Expected stored bars with trades, got none in {frame.height} rows (F-BAR-07): "
            "choose a window with trades."
        )
    raw = stored.select(
        "ts_open",
        "ts_close",
        *(pl.col(price) - pl.col("adj_offset") for price in _RAW_PRICES),
        "volume",
    )
    return tuple(BarRecord.model_construct(**bar) for bar in raw.iter_rows(named=True))


def tape_of_trades(frame: pl.DataFrame) -> tuple[TradeRecord, ...]:
    """The trade prints of a frame of the store's trades, as the engine reads them: by
    `ts_recv`, the engine's clock (F-CLK-01), and at one instant by the vendor's `sequence`
    (F-CLK-03). A frame without trades, or with those of more than one contract, is refused.
    The store checked each row when it was written (ADR-0019)."""
    if frame.is_empty():
        raise ValueError("Expected trades, got none: choose a window with trades.")
    instruments = sorted(frame.get_column("instrument_id").unique().to_list())
    if len(instruments) > 1:
        raise ValueError(
            f"Expected the trades of one contract, got instruments {instruments}: a tape is one "
            "contract's, so choose its trades first."
        )
    ordered = frame.sort("ts_recv", "sequence", maintain_order=True)
    ordered = ordered.select("ts_recv", "ts_event", "price", "size")
    return tuple(
        TradeRecord.model_construct(ts=ts, ts_event=ts_event, price=price, size=size)
        for ts, ts_event, price, size in ordered.iter_rows()
    )
