"""The canonical market-data schemas: what each kind of file holds, in which units (ADR-0019).

Every price is an int64 count of 1e-9 units of the quote currency (5,432.25 is
5_432_250_000_000) and every timestamp an int64 count of nanoseconds since the Unix
epoch in UTC, as Databento ships them. The store keeps both as integers; views
convert them. A vendor's "undefined" value (Databento's largest integers) is stored
as null, and vendor flags are not stored: the importer counts, per day, the records
whose flags mark an unreliable `ts_recv`.

Records keep both clocks: `ts_recv`, when the capture server received the record,
which is the engine's clock (ADR-0006), and `ts_event`, the venue's time. Each
record type names the time from which it may be used, its availability: `ts_recv`
for trades, TBBO, definitions, statistics, and funding, and `ts_close` for bars.
Columns keep the vendor's spelling, an external contract (`08-code-design.md` §2).
Where the files live is `fefat.market.layout`.
"""

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, NoReturn, Self

import polars as pl
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)


class FrozenModel(BaseModel):
    """A value: validated when it is built, immutable after, and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _refused(self: object, *arguments: object, **named: object) -> NoReturn:
    raise TypeError(
        f"Expected a record left as it was read, got a change to its {type(self).__name__}: "
        "build a new value from a copy, `dict(...)` or `list(...)`."
    )


class FrozenDict[Key, Value](dict[Key, Value]):
    """A dict no one can change once it is built, which a model's mapping holds (`frozen`): it
    equals, writes, and pickles as the dict it was built from."""

    __setitem__ = _refused
    __delitem__ = _refused
    __ior__ = _refused
    clear = _refused
    pop = _refused
    popitem = _refused
    setdefault = _refused
    update = _refused

    def __reduce__(self) -> tuple[type["FrozenDict[Key, Value]"], tuple[dict[Key, Value]]]:
        return (FrozenDict, (dict(self),))


class FrozenList[Item](list[Item]):
    """A list no one can change once it is built, which a model's mapping holds (`frozen`): it
    equals, writes, and pickles as the list it was built from."""

    __setitem__ = _refused
    __delitem__ = _refused
    __iadd__ = _refused
    __imul__ = _refused
    append = _refused
    extend = _refused
    insert = _refused
    pop = _refused
    remove = _refused
    clear = _refused
    sort = _refused
    reverse = _refused

    def __reduce__(self) -> tuple[type["FrozenList[Item]"], tuple[list[Item]]]:
        return (FrozenList, (list(self),))


def frozen(value: object) -> object:
    """`value` with each mapping and list in it, at every depth, held as a `FrozenDict` or a
    `FrozenList`, so that a model's field annotated `Annotated[Mapping[...],
    AfterValidator(frozen)]` holds what its file says, and writes it as a `dict` field did."""
    if isinstance(value, Mapping):
        return FrozenDict({key: frozen(each) for key, each in value.items()})
    if isinstance(value, list):
        return FrozenList(frozen(each) for each in value)
    if isinstance(value, tuple):
        return tuple(frozen(each) for each in value)
    return value


FrozenDocument = Annotated[Mapping[str, Any], AfterValidator(frozen)]
"""A JSON document as a model's field, such as a strategy's specification, held read-only at
every depth (`frozen`)."""


class SchemaKind(StrEnum):
    """What a dataset's records are; bars (`ohlcv`) also name their timeframe."""

    TRADES = "trades"
    TBBO = "tbbo"
    OHLCV = "ohlcv"
    DEFINITIONS = "definitions"
    STATISTICS = "statistics"
    FUNDING = "funding"


class AggressorSide(StrEnum):
    """The side a print's aggressor took, as the trades' `side` column writes it: `B` bought,
    `A` sold, and `N` none known, as an opening auction's prints or IBKR's."""

    BUY = "B"
    SELL = "A"
    UNKNOWN = "N"


class TimeUnit(StrEnum):
    """The unit of a bar timeframe, as the schema name writes it."""

    SECOND = "s"
    MINUTE = "m"
    HOUR = "h"
    DAY = "d"


_TIMEFRAME_TEXT = "([1-9][0-9]*)([smhd])"
"""A timeframe as schema names write it: a count without leading zeros and a unit."""
_UNIT_WORDS = {
    TimeUnit.SECOND: "second",
    TimeUnit.MINUTE: "minute",
    TimeUnit.HOUR: "hour",
    TimeUnit.DAY: "day",
}
_SECONDS_PER_TIME_UNIT = {
    TimeUnit.SECOND: 1,
    TimeUnit.MINUTE: 60,
    TimeUnit.HOUR: 3_600,
    TimeUnit.DAY: 86_400,
}


class Timeframe(FrozenModel):
    """A bar's length, written `1s`, `5m`, `1h`, or `1d`; a daily bar spans its trade date."""

    count: int = Field(ge=1)
    unit: TimeUnit

    def __str__(self) -> str:
        return f"{self.count}{self.unit}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read a timeframe written `<count><s|m|h|d>`, such as `5m`, as schema names write it."""
        found = re.fullmatch(_TIMEFRAME_TEXT, text)
        if found is None:
            raise ValueError(f"Expected a timeframe such as 1s, 5m, 1h, or 1d, got {text!r}.")
        return cls(count=int(found[1]), unit=TimeUnit(found[2]))

    def in_words(self) -> str:
        """The timeframe as prose writes it before a noun, such as `1-minute` or `5-second`."""
        return f"{self.count}-{_UNIT_WORDS[self.unit]}"

    def nominal_seconds(self) -> int:
        """The length in seconds, nominal for daily bars, whose sessions differ in length."""
        return self.count * _SECONDS_PER_TIME_UNIT[self.unit]

    def nominal_nanoseconds(self) -> int:
        """The length in nanoseconds, the unit of the store's clock."""
        return self.nominal_seconds() * 1_000_000_000


class RecordSchemaName(FrozenModel):
    """The schema of records other than bars, named by its kind alone."""

    kind: SchemaKind

    @model_validator(mode="after")
    def _names_records_other_than_bars(self) -> Self:
        if self.kind is SchemaKind.OHLCV:
            raise ValueError(
                "Expected a schema of records other than bars, got ohlcv; bars name their "
                "timeframe (BarSchemaName)."
            )
        return self

    def __str__(self) -> str:
        return self.kind.value


class BarSchemaName(FrozenModel):
    """The schema of bars of one timeframe, such as `ohlcv-1m`."""

    timeframe: Timeframe

    @property
    def kind(self) -> SchemaKind:
        return SchemaKind.OHLCV

    def __str__(self) -> str:
        return f"{SchemaKind.OHLCV}-{self.timeframe}"


BAR_SCHEMA_NAME = re.compile(f"ohlcv-{_TIMEFRAME_TEXT}")
RECORD_KINDS = tuple(kind for kind in SchemaKind if kind is not SchemaKind.OHLCV)


def parse_schema_name(text: str) -> RecordSchemaName | BarSchemaName:
    """Read a schema's folder name: `trades`, `tbbo`, `definitions`, `statistics`, `funding`,
    or `ohlcv-<count><s|m|h|d>`."""
    bars = BAR_SCHEMA_NAME.fullmatch(text)
    if bars is not None:
        return BarSchemaName(timeframe=Timeframe(count=int(bars[1]), unit=TimeUnit(bars[2])))
    if text in {kind.value for kind in RECORD_KINDS}:
        return RecordSchemaName(kind=SchemaKind(text))
    names = ", ".join(kind.value for kind in RECORD_KINDS)
    raise ValueError(f"Expected a schema name ({names}, or ohlcv-<count><s|m|h|d>), got {text!r}.")


def _parsed_when_text(value: object) -> object:
    return parse_schema_name(value) if isinstance(value, str) else value


SchemaName = Annotated[
    RecordSchemaName | BarSchemaName,
    BeforeValidator(_parsed_when_text),
    PlainSerializer(str, return_type=str),
]
"""A schema as a model field: built from its folder name, written as it."""

_TRADES_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "instrument_id": pl.UInt32,
        "price": pl.Int64,
        "size": pl.UInt32,
        "side": pl.String,
        "sequence": pl.UInt32,
    }
)
"""One row per trade print, available at `ts_recv`. `side` is the aggressor (`AggressorSide`:
`A` sells, `B` buys, `N` none), and `size` counts the dataset's size unit."""

_TBBO_COLUMNS = pl.Schema(
    {
        **_TRADES_COLUMNS,
        "bid_px_00": pl.Int64,
        "ask_px_00": pl.Int64,
        "bid_sz_00": pl.UInt32,
        "ask_sz_00": pl.UInt32,
    }
)
"""A trade with the best bid and ask just before it (Databento's TBBO, level 0 of `Mbp1Msg`),
available at `ts_recv`."""

_BARS_COLUMNS = pl.Schema(
    {
        "ts_open": pl.Int64,
        "ts_close": pl.Int64,
        "trade_date": pl.Date,
        "instrument_id": pl.UInt32,
        "open": pl.Int64,
        "high": pl.Int64,
        "low": pl.Int64,
        "close": pl.Int64,
        "volume": pl.UInt64,
        "trade_count": pl.UInt32,
        "vwap": pl.Int64,
    }
)
"""One row per bar of the trades received in `[ts_open, ts_close)`, sparse (a bar exists only
where trades do), with its session's `trade_date`; a bar is available at `ts_close`. `volume`
counts the dataset's size unit; `trade_count` and `vwap`, the volume-weighted average price in
the prices' 1e-9 units rounded down, are null for a vendor's bars that carry neither (D-43).
`ohlcv-1d` holds session bars by trade date, built from finer bars or imported with `ts_open`
and `ts_close` from the calendar's session for their date; a vendor's daily bars cut on UTC
dates are not session bars and are not stored as it. `fefat.market.bars` builds bars."""

_DEFINITIONS_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "instrument_id": pl.UInt32,
        "raw_symbol": pl.String,
        "asset": pl.String,
        "exchange": pl.String,
        "currency": pl.String,
        "instrument_class": pl.String,
        "security_type": pl.String,
        "min_price_increment": pl.Int64,
        "display_factor": pl.Int64,
        "unit_of_measure": pl.String,
        "unit_of_measure_qty": pl.Int64,
        "expiration": pl.Int64,
        "activation": pl.Int64,
        "maturity_year": pl.UInt16,
        "maturity_month": pl.UInt8,
    }
)
"""An instrument definition as the vendor published it (fields of Databento's
`InstrumentDefMsg`), applying from `ts_recv`: `min_price_increment` and `unit_of_measure_qty`
in 1e-9 units, `expiration` and `activation` in nanoseconds."""

_STATISTICS_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "ts_ref": pl.Int64,
        "instrument_id": pl.UInt32,
        "stat_type": pl.UInt16,
        "price": pl.Int64,
        "quantity": pl.Int64,
        "update_action": pl.UInt8,
        "stat_flags": pl.UInt8,
        "sequence": pl.UInt32,
    }
)
"""A venue statistic (Databento's `StatMsg`): `stat_type` 3 is the settlement price, 6 the
cleared volume, and 9 the open interest. `ts_ref` is the vendor's reference time (the
settlement's trade date), and `ts_recv` is when the value became available, the first moment
a backtest may use it. Every update is kept: a final settlement that revises a preliminary
one is a new row (`stat_flags` tells them apart), read as of `ts_recv`, never a replacement
keyed on `ts_ref`."""

_FUNDING_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "instrument_id": pl.UInt32,
        "funding_rate": pl.Int64,
    }
)
"""A perpetual's funding event, its rate in 1e-9 units (0.0001 is 100_000). An archive's one
time column goes to `ts_event`; `ts_recv` is when the rate was fixed (the funding time on
Binance and Bybit), never earlier than `ts_event`."""

_COLUMNS_BY_KIND = {
    SchemaKind.TRADES: _TRADES_COLUMNS,
    SchemaKind.TBBO: _TBBO_COLUMNS,
    SchemaKind.OHLCV: _BARS_COLUMNS,
    SchemaKind.DEFINITIONS: _DEFINITIONS_COLUMNS,
    SchemaKind.STATISTICS: _STATISTICS_COLUMNS,
    SchemaKind.FUNDING: _FUNDING_COLUMNS,
}


def polars_schema(schema_name: SchemaName) -> pl.Schema:
    """The columns, in order and with their types, that every partition of the schema holds."""
    return pl.Schema(_COLUMNS_BY_KIND[schema_name.kind])


def require_columns(expected: pl.Schema, actual: pl.Schema, source: str) -> None:
    """Refuse columns other than `expected`, in its order and with its types, naming `source`."""
    if actual != expected:
        raise ValueError(
            f"Expected the columns {_described(expected)}, got {_described(actual)} in {source}."
        )


def _described(columns: pl.Schema) -> str:
    return ", ".join(f"{name} {dtype}" for name, dtype in columns.items())
