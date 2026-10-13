"""Reading DBN files, Databento's binary encoding, with the vendor's own decoder (`databento-dbn`,
D-42).

A DBN file is a metadata header (the dataset, the schema, and the symbology that maps each raw
symbol to an `instrument_id` by UTC date) followed by fixed-width records. `read_dbn` feeds the
file to the decoder a chunk at a time, so a file of any size streams, and yields its
`DbnMetadata`, read at once, and an iterator of frames, one per chunk, with the record columns
the canonical store keeps (`fefat.market.schema`), in the file's order. The vendor's undefined values (its largest
integers, an empty text) become null. Flags are not kept: trades and TBBO frames carry
`bad_ts_recv`, whether a record's flags mark its `ts_recv` unreliable, for the importer to count
per day (ADR-0019). Files of older DBN versions are upgraded to version 3 as they are read, and
a file whose name ends in `.zst` is inflated by the decoder.

    metadata, frames = read_dbn(Path("glbx-mdp3-20100606-20260923.ohlcv-1m.dbn"))
    for bars in frames:
        ...  # ts_event, instrument_id, open, high, low, close, volume
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path
from typing import Any

import polars as pl
from databento_dbn import (
    F_BAD_TS_RECV,
    UNDEF_ORDER_SIZE,
    UNDEF_PRICE,
    UNDEF_STAT_QUANTITY,
    UNDEF_TIMESTAMP,
    Compression,
    DBNDecoder,
    DBNError,
    InstrumentDefMsg,
    MBP1Msg,
    Metadata,
    OHLCVMsg,
    RType,
    StatMsg,
    SType,
    TradeMsg,
    VersionUpgradePolicy,
)

from fefat.market.contracts import SYMBOLOGY_COLUMNS
from fefat.market.schema import SchemaName, parse_schema_name

CHUNK_BYTES = 8_000_000
"""How much of a file the decoder takes at a time: about 143,000 one-minute bars."""
_HEADER_CHUNK_BYTES = 65_536
"""How much the decoder takes at a time while it reads only the header."""

_UNDEFINED_YEAR = 65_535
_UNDEFINED_MONTH = 255
_AS_WRITTEN = VersionUpgradePolicy.from_int(1)
_UPGRADE_TO_VERSION_3 = VersionUpgradePolicy.from_int(3)


@dataclass(frozen=True)
class DbnMetadata:
    """A DBN file's header: its dataset, the canonical schema of its records, the DBN version
    it is written in (before the decoder upgrades it), and its symbology, with the columns of
    `SYMBOLOGY_COLUMNS`."""

    dataset: str
    schema_name: SchemaName
    version: int
    symbology: pl.DataFrame


@dataclass(frozen=True)
class RecordField:
    """One column read from every record: its name, how to read it, its type, and the vendor's
    undefined value, which becomes null. A timestamp whose undefined value is 2**64 - 1 is read
    as UInt64 and becomes Int64 once that value is null."""

    name: str
    read: Callable[[Any], object]
    dtype: type[pl.DataType]
    undefined: int | str | None = None
    read_dtype: type[pl.DataType] | None = None

    def series(self, records: list[Any]) -> pl.Series:
        dtype = self.dtype if self.read_dtype is None else self.read_dtype
        return pl.Series(self.name, [self.read(record) for record in records], dtype=dtype)

    def column(self) -> pl.Expr:
        read = pl.col(self.name)
        if self.undefined is None:
            return read
        return pl.when(read != self.undefined).then(read).cast(self.dtype).alias(self.name)


def _plain(name: str, dtype: type[pl.DataType]) -> RecordField:
    return RecordField(name, attrgetter(name), dtype)


def _price(name: str, read: Callable[[Any], object] | None = None) -> RecordField:
    return RecordField(name, attrgetter(name) if read is None else read, pl.Int64, UNDEF_PRICE)


def _timestamp(name: str) -> RecordField:
    return RecordField(name, attrgetter(name), pl.Int64, UNDEF_TIMESTAMP, pl.UInt64)


def _text(name: str) -> RecordField:
    return RecordField(name, lambda record: str(getattr(record, name)), pl.String, "")


def _unreliable_ts_recv(record: Any) -> bool:
    return record.flags & F_BAD_TS_RECV != 0


_BAR_FIELDS = (
    _plain("ts_event", pl.Int64),
    _plain("instrument_id", pl.UInt32),
    _price("open"),
    _price("high"),
    _price("low"),
    _price("close"),
    _plain("volume", pl.UInt64),
)
_TRADE_FIELDS = (
    _plain("ts_recv", pl.Int64),
    _plain("ts_event", pl.Int64),
    _plain("instrument_id", pl.UInt32),
    _price("price"),
    RecordField("size", attrgetter("size"), pl.UInt32, UNDEF_ORDER_SIZE),
    RecordField("side", lambda record: str(record.side), pl.String),
    _plain("sequence", pl.UInt32),
)
_BAD_TS_RECV = RecordField("bad_ts_recv", _unreliable_ts_recv, pl.Boolean)
_TBBO_FIELDS = (
    *_TRADE_FIELDS,
    _price("bid_px_00", lambda record: record.levels[0].bid_px),
    _price("ask_px_00", lambda record: record.levels[0].ask_px),
    RecordField("bid_sz_00", lambda record: record.levels[0].bid_sz, pl.UInt32),
    RecordField("ask_sz_00", lambda record: record.levels[0].ask_sz, pl.UInt32),
)
_DEFINITION_FIELDS = (
    _plain("ts_recv", pl.Int64),
    _plain("ts_event", pl.Int64),
    _plain("instrument_id", pl.UInt32),
    _text("raw_symbol"),
    _text("asset"),
    _text("exchange"),
    _text("currency"),
    _text("instrument_class"),
    _text("security_type"),
    _price("min_price_increment"),
    _plain("display_factor", pl.Int64),
    _text("unit_of_measure"),
    _price("unit_of_measure_qty"),
    _timestamp("expiration"),
    _timestamp("activation"),
    RecordField("maturity_year", attrgetter("maturity_year"), pl.UInt16, _UNDEFINED_YEAR),
    RecordField("maturity_month", attrgetter("maturity_month"), pl.UInt8, _UNDEFINED_MONTH),
)
_STATISTIC_FIELDS = (
    _plain("ts_recv", pl.Int64),
    _plain("ts_event", pl.Int64),
    _timestamp("ts_ref"),
    _plain("instrument_id", pl.UInt32),
    RecordField("stat_type", lambda record: int(record.stat_type), pl.UInt16),
    _price("price"),
    RecordField("quantity", attrgetter("quantity"), pl.Int64, UNDEF_STAT_QUANTITY),
    RecordField("update_action", lambda record: int(record.update_action), pl.UInt8),
    _plain("stat_flags", pl.UInt8),
    _plain("sequence", pl.UInt32),
)


@dataclass(frozen=True)
class _RecordLayout:
    """The records of one schema: its name, their class, their record type where the class
    serves several (bars of each timeframe), and the columns read from them."""

    name: str
    record_class: type
    rtype: RType | None
    fields: tuple[RecordField, ...]

    def frame(self, records: list[Any], path: Path) -> pl.DataFrame:
        stray = next((record for record in records if not self._holds(record)), None)
        if stray is not None:
            raise ValueError(
                f"Expected {self.record_class.__name__} records of {self.name} in {path}, got a "
                f"{type(stray).__name__} of {stray.rtype}."
            )
        read = pl.DataFrame([field.series(records) for field in self.fields])
        return read.select(field.column() for field in self.fields)

    def _holds(self, record: Any) -> bool:
        return type(record) is self.record_class and (
            self.rtype is None or record.rtype == self.rtype
        )


def _bars(name: str) -> _RecordLayout:
    return _RecordLayout(name, OHLCVMsg, RType.from_str(name), _BAR_FIELDS)


_LAYOUTS = {
    layout.name: layout
    for layout in (
        _RecordLayout("trades", TradeMsg, None, (*_TRADE_FIELDS, _BAD_TS_RECV)),
        _RecordLayout("tbbo", MBP1Msg, None, (*_TBBO_FIELDS, _BAD_TS_RECV)),
        _bars("ohlcv-1s"),
        _bars("ohlcv-1m"),
        _bars("ohlcv-1d"),
        _RecordLayout("definitions", InstrumentDefMsg, None, _DEFINITION_FIELDS),
        _RecordLayout("statistics", StatMsg, None, _STATISTIC_FIELDS),
    )
}
_CANONICAL_NAMES = {"definition": "definitions"}


def read_dbn(
    path: Path, chunk_bytes: int = CHUNK_BYTES
) -> tuple[DbnMetadata, Iterator[pl.DataFrame]]:
    """The file's `DbnMetadata`, read now, and its records as a frame per chunk, read as the
    iterator is consumed, in file order. A file that is not DBN, holds records of another
    schema than its header names, or ends in the middle of a record is refused."""
    version = _written_version(path, min(chunk_bytes, _HEADER_CHUNK_BYTES))
    decoded = _decoded(path, chunk_bytes, _UPGRADE_TO_VERSION_3)
    first = next(decoded, None)
    if first is None:
        raise ValueError(f"Expected a DBN file with its metadata, got an empty file: {path}.")
    metadata = _metadata_of(first[0], path, version)
    layout = _LAYOUTS[str(metadata.schema_name)]
    return metadata, _frames(layout, first[1:], decoded, path)


def _frames(
    layout: _RecordLayout, first: list[Any], decoded: Iterator[list[Any]], path: Path
) -> Iterator[pl.DataFrame]:
    if first:
        yield layout.frame(first, path)
    for records in decoded:
        yield layout.frame(records, path)


def _written_version(path: Path, chunk_bytes: int) -> int:
    """The DBN version the file states in its header, read before any upgrade."""
    for decoded in _decoded(path, chunk_bytes, _AS_WRITTEN):
        return _header(decoded[0], path).version
    raise ValueError(f"Expected a DBN file with its metadata, got an empty file: {path}.")


def _decoded(
    path: Path, chunk_bytes: int, upgrade_policy: VersionUpgradePolicy
) -> Iterator[list[Any]]:
    """What the decoder makes of each chunk, skipping chunks that complete nothing."""
    compression = Compression("zstd" if path.name.endswith(".zst") else "none")
    decoder = DBNDecoder(upgrade_policy=upgrade_policy, compression=compression)
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(chunk_bytes), b""):
                decoder.write(chunk)
                decoded = decoder.decode()
                if decoded:
                    yield decoded
    except DBNError as error:
        raise ValueError(f"Expected a DBN file, got {path}: {error}") from error
    left = len(decoder.buffer())
    if left:
        raise ValueError(
            f"Expected whole records in {path}, got {left} bytes after the last one: the file "
            "is cut short; download it again."
        )


def _header(decoded: object, path: Path) -> Metadata:
    if not isinstance(decoded, Metadata):
        raise ValueError(
            f"Expected the DBN metadata first in {path}, got {type(decoded).__name__}."
        )
    return decoded


def _metadata_of(decoded: object, path: Path, version: int) -> DbnMetadata:
    header = _header(decoded, path)
    if header.stype_out != SType("instrument_id") or not header.mappings:
        raise ValueError(
            f"Expected raw symbols mapped to instrument_id in the metadata of {path}, got the "
            f"output symbology {header.stype_out} with {len(header.mappings)} mappings: a file "
            "without them names its contracts only through definition records, which the "
            "importer does not read yet."
        )
    return DbnMetadata(
        dataset=header.dataset,
        schema_name=_schema_name(header, path),
        version=version,
        symbology=_symbology(header, path),
    )


def _schema_name(header: Metadata, path: Path) -> SchemaName:
    vendor_name = str(header.schema)
    canonical_name = _CANONICAL_NAMES.get(vendor_name, vendor_name)
    if canonical_name not in _LAYOUTS:
        raise ValueError(
            f"Expected a DBN file of {', '.join(sorted(_LAYOUTS))}, got the schema {vendor_name} "
            f"in {path}."
        )
    return parse_schema_name(canonical_name)


def _symbology(header: Metadata, path: Path) -> pl.DataFrame:
    """The metadata's mappings as rows of `SYMBOLOGY_COLUMNS`; an interval without a symbol,
    when the raw symbol named nothing, is left out."""
    rows = [
        (
            raw_symbol,
            _instrument_id(interval["symbol"], raw_symbol, path),
            interval["start_date"],
            interval["end_date"],
        )
        for raw_symbol, intervals in header.mappings.items()
        for interval in intervals
        if interval["symbol"]
    ]
    return pl.DataFrame(rows, schema=SYMBOLOGY_COLUMNS, orient="row")


def _instrument_id(symbol: str, raw_symbol: str, path: Path) -> int:
    if not symbol.isdigit():
        raise ValueError(
            f"Expected an instrument_id as the symbol {raw_symbol} maps to in {path}, got "
            f"{symbol!r}."
        )
    return int(symbol)
