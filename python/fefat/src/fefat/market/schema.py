"""The canonical market-data store: its units, schemas, and layout (ADR-0019).

Every price is an int64 count of 1e-9 units of the quote currency (5,432.25 is
5_432_250_000_000) and every timestamp an int64 count of nanoseconds since the Unix
epoch in UTC, as Databento ships them. The store keeps both as integers; views
convert them. Records keep both clocks: `ts_recv`, when the capture server received
the record, which is the engine's clock (ADR-0006), and `ts_event`, the venue's
time. Bars carry `ts_open`, `ts_close`, and the `trade_date` of their session.
Columns keep the vendor's spelling, an external contract (`08-code-design.md` §2).

A store folder holds a folder per provider, a folder per schema in each, and below:

    <provider>/<schema>/root=<root>/dataset.json
    <provider>/<schema>/root=<root>/contract=<contract>/date=<YYYY-MM-DD>/part.parquet
    <provider>/<schema>/root=<root>/contract=<contract>/month=<YYYY-MM>/part.parquet
    <provider>/<schema>/root=<root>/contract=<contract>/part.parquet

Trades, TBBO, and bars finer than a minute are split per trade date, one-minute
bars per month, and coarser bars, definitions, statistics, and funding are one file
per contract (`partitioning`). `dataset.json` holds what every partition of the
dataset shares, such as the unit of its sizes. The folder `raw` beside the providers
keeps the vendors' original files (`fefat.market.store`).
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Self

import polars as pl
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

__all__ = [
    "BARS_COLUMNS",
    "DATASET_METADATA_FILE_NAME",
    "DEFINITIONS_COLUMNS",
    "FUNDING_COLUMNS",
    "PARTITION_FILE_NAME",
    "RAW_FOLDER_NAME",
    "STATISTICS_COLUMNS",
    "TBBO_COLUMNS",
    "TRADES_COLUMNS",
    "BarSchemaName",
    "Dataset",
    "DatasetMetadata",
    "FolderName",
    "FrozenModel",
    "Partition",
    "Partitioning",
    "ProviderName",
    "RecordSchemaName",
    "SchemaKind",
    "SchemaName",
    "SizeUnit",
    "TimeUnit",
    "Timeframe",
    "YearMonth",
    "parse_schema_name",
    "partitioning",
    "polars_schema",
]

RAW_FOLDER_NAME = "raw"
PARTITION_FILE_NAME = "part.parquet"
DATASET_METADATA_FILE_NAME = "dataset.json"
PARTITION_LAYOUT = (
    "<provider>/<schema>/root=<root>/contract=<contract>[/date=<YYYY-MM-DD>|/month=<YYYY-MM>]"
    f"/{PARTITION_FILE_NAME}"
)
SECONDS_PER_MINUTE = 60


class FrozenModel(BaseModel):
    """A value: validated when it is built, immutable after, and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _not_the_raw_folder(name: str) -> str:
    if name.lower() == RAW_FOLDER_NAME:
        raise ValueError(
            f"Expected a provider, got {name!r}, the folder of the vendors' raw files."
        )
    return name


FolderName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
]
"""A provider, root, or contract as a folder name: letters and digits, with dots, dashes,
and underscores inside (Windows drops a trailing dot, and the layout uses `/` and `=`)."""

ProviderName = Annotated[FolderName, AfterValidator(_not_the_raw_folder)]
"""A provider's folder name; `raw`, in any case, is the folder of the vendors' files."""


class SchemaKind(StrEnum):
    """What a dataset's records are; bars (`ohlcv`) also name their timeframe."""

    TRADES = "trades"
    TBBO = "tbbo"
    OHLCV = "ohlcv"
    DEFINITIONS = "definitions"
    STATISTICS = "statistics"
    FUNDING = "funding"


class TimeUnit(StrEnum):
    """The unit of a bar timeframe, as the schema name writes it."""

    SECOND = "s"
    MINUTE = "m"
    HOUR = "h"
    DAY = "d"


SECONDS_PER_TIME_UNIT = {
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

    def nominal_seconds(self) -> int:
        """The length in seconds, nominal for daily bars, whose sessions differ in length."""
        return self.count * SECONDS_PER_TIME_UNIT[self.unit]


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


BAR_SCHEMA_NAME = re.compile(r"ohlcv-([1-9][0-9]*)([smhd])")
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

TRADES_COLUMNS = pl.Schema(
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
"""One row per trade print. `side` is the aggressor (`A` sells, `B` buys, `N` none), and
`size` counts the dataset's size unit."""

TBBO_COLUMNS = pl.Schema(
    {
        **TRADES_COLUMNS,
        "bid_px_00": pl.Int64,
        "ask_px_00": pl.Int64,
        "bid_sz_00": pl.UInt32,
        "ask_sz_00": pl.UInt32,
    }
)
"""A trade with the best bid and ask just before it (Databento's TBBO, level 0 of `Mbp1Msg`)."""

BARS_COLUMNS = pl.Schema(
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
    }
)
"""One row per bar of the trades received in `[ts_open, ts_close)`, sparse (a bar exists only
where trades do), with its session's `trade_date`. `volume` counts the dataset's size unit;
`trade_count` is null for a vendor's bars that carry no count."""

DEFINITIONS_COLUMNS = pl.Schema(
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
`InstrumentDefMsg`): `min_price_increment` and `unit_of_measure_qty` in 1e-9 units,
`expiration` and `activation` in nanoseconds."""

STATISTICS_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "ts_ref": pl.Int64,
        "instrument_id": pl.UInt32,
        "stat_type": pl.UInt16,
        "price": pl.Int64,
        "quantity": pl.Int64,
        "update_action": pl.UInt8,
        "sequence": pl.UInt32,
    }
)
"""A venue statistic (Databento's `StatMsg`): `stat_type` 3 is the settlement price, 6 the
cleared volume, and 9 the open interest. `ts_ref` is the vendor's reference time (the
settlement's trade date), and `ts_recv` is when the value became available, the first
moment a backtest may use it."""

FUNDING_COLUMNS = pl.Schema(
    {
        "ts_recv": pl.Int64,
        "ts_event": pl.Int64,
        "instrument_id": pl.UInt32,
        "funding_rate": pl.Int64,
    }
)
"""A perpetual's funding event, its rate in 1e-9 units (0.0001 is 100_000); an archive with
one time column stores it in both clocks."""

COLUMNS_BY_KIND = {
    SchemaKind.TRADES: TRADES_COLUMNS,
    SchemaKind.TBBO: TBBO_COLUMNS,
    SchemaKind.OHLCV: BARS_COLUMNS,
    SchemaKind.DEFINITIONS: DEFINITIONS_COLUMNS,
    SchemaKind.STATISTICS: STATISTICS_COLUMNS,
    SchemaKind.FUNDING: FUNDING_COLUMNS,
}


def polars_schema(schema_name: SchemaName) -> pl.Schema:
    """The columns, in order and with their types, that every partition of the schema holds."""
    return pl.Schema(COLUMNS_BY_KIND[schema_name.kind])


class Partitioning(StrEnum):
    """How a schema's files are split under each contract: by the key folder named, or not."""

    TRADE_DATE = "date"
    MONTH = "month"
    CONTRACT = "contract"


def partitioning(schema_name: SchemaName) -> Partitioning:
    """Ticks and bars finer than a minute go per trade date, one-minute bars per month, and
    the rest per contract (`02-engine-and-data.md` §1.1)."""
    if isinstance(schema_name, RecordSchemaName):
        ticks = schema_name.kind in (SchemaKind.TRADES, SchemaKind.TBBO)
        return Partitioning.TRADE_DATE if ticks else Partitioning.CONTRACT
    seconds = schema_name.timeframe.nominal_seconds()
    if seconds < SECONDS_PER_MINUTE:
        return Partitioning.TRADE_DATE
    if seconds == SECONDS_PER_MINUTE:
        return Partitioning.MONTH
    return Partitioning.CONTRACT


YEAR_MONTH = re.compile(r"([0-9]{4})-([0-9]{2})")


class YearMonth(FrozenModel):
    """A calendar month, the key of one-minute bar partitions, written `2026-03`."""

    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)

    @classmethod
    def parse(cls, text: str) -> Self:
        found = YEAR_MONTH.fullmatch(text)
        if found is None:
            raise ValueError(f"Expected a month written YYYY-MM, got {text!r}.")
        return cls(year=int(found[1]), month=int(found[2]))

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def overlaps(self, start: date, end: date) -> bool:
        """Whether any day of the month lies in `[start, end]`."""
        return (start.year, start.month) <= (self.year, self.month) <= (end.year, end.month)


class Dataset(FrozenModel):
    """One provider's records of one schema for one root, in `<provider>/<schema>/root=<root>`."""

    provider: ProviderName
    schema_name: SchemaName
    root: FolderName

    def relative_folder(self) -> PurePosixPath:
        """The dataset's folder, relative to the store folder."""
        return PurePosixPath(self.provider, str(self.schema_name), f"root={self.root}")


def _partitioning_of(key: date | YearMonth | None) -> Partitioning:
    if key is None:
        return Partitioning.CONTRACT
    if isinstance(key, YearMonth):
        return Partitioning.MONTH
    return Partitioning.TRADE_DATE


class Partition(FrozenModel):
    """One Parquet file of a dataset: one contract's records, for one key where the schema
    has keys (a trade date or a month)."""

    dataset: Dataset
    contract: FolderName
    key: date | YearMonth | None

    @model_validator(mode="after")
    def _key_fits_the_partitioning(self) -> Self:
        expected = partitioning(self.dataset.schema_name)
        if _partitioning_of(self.key) is not expected:
            raise ValueError(
                f"Expected a {expected} key for {self.dataset.schema_name} partitions, "
                f"got {self.key!r}."
            )
        return self

    @classmethod
    def from_relative_path(cls, path: PurePosixPath) -> Self:
        """Read a partition from its path relative to the store folder; any other path is refused."""
        try:
            partition = cls._from_folders(path.parts)
        except ValueError as error:
            raise ValueError(
                f"Expected a partition path {PARTITION_LAYOUT}, got {path}: {error}"
            ) from error
        if partition.relative_path() != path:
            raise ValueError(
                f"Expected a partition path {PARTITION_LAYOUT}, got {path}, which is written "
                f"{partition.relative_path()}."
            )
        return partition

    @classmethod
    def _from_folders(cls, folders: tuple[str, ...]) -> Self:
        if len(folders) not in (5, 6) or folders[-1] != PARTITION_FILE_NAME:
            raise ValueError(f"expected five or six parts ending in {PARTITION_FILE_NAME}")
        dataset = Dataset(
            provider=folders[0],
            schema_name=parse_schema_name(folders[1]),
            root=_folder_value(folders[2], "root"),
        )
        key = _parsed_key(folders[4]) if len(folders) == 6 else None
        return cls(dataset=dataset, contract=_folder_value(folders[3], "contract"), key=key)

    def relative_path(self) -> PurePosixPath:
        """The file's path, relative to the store folder."""
        folder = self.dataset.relative_folder() / f"contract={self.contract}"
        if self.key is None:
            return folder / PARTITION_FILE_NAME
        return folder / f"{_partitioning_of(self.key)}={self.key}" / PARTITION_FILE_NAME


def _folder_value(folder: str, name: str) -> str:
    prefix = f"{name}="
    if not folder.startswith(prefix):
        raise ValueError(f"expected the folder {prefix}<value>, got {folder!r}")
    return folder.removeprefix(prefix)


def _parsed_key(folder: str) -> date | YearMonth:
    name, _, value = folder.partition("=")
    if name == Partitioning.TRADE_DATE:
        return date.fromisoformat(value)
    if name == Partitioning.MONTH:
        return YearMonth.parse(value)
    raise ValueError(f"expected a date= or month= folder, got {folder!r}")


class SizeUnit(FrozenModel):
    """What one unit of a `size` or `volume` column is: `lot` of `asset`, such as 1 contract
    or 0.001 BTC."""

    lot: Decimal = Field(gt=0)
    asset: str = Field(min_length=1)


class DatasetMetadata(FrozenModel):
    """What every partition of a dataset shares, kept in the dataset's `dataset.json`."""

    size_unit: SizeUnit
