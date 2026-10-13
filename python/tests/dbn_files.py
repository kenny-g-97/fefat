"""DBN files for the importer tests, written with Databento's own encoder (D-42) into a test's
temporary folder: the store's rules keep market-data files out of the repository except the
synthetic fixtures."""

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from databento_dbn import (
    Compression,
    DBNRecord,
    Encoding,
    Metadata,
    Schema,
    SType,
    Transcoder,
)
from databento_dbn.metadata import MappingInterval

NANOSECONDS_PER_MINUTE = 60_000_000_000
INSTRUMENT_ID = SType("instrument_id")


@dataclass
class Interval:
    """A mapping interval as the decoder's metadata takes it: the symbol is the instrument_id."""

    start_date: date
    end_date: date
    symbol: str


@dataclass
class SymbolMapping:
    raw_symbol: str
    intervals: Sequence[MappingInterval]


def utc(*fields: int) -> int:
    """The instant of a UTC date and time, in nanoseconds since the Unix epoch."""
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def mapping(raw_symbol: str, instrument_id: int, start: date, end: date) -> SymbolMapping:
    """`raw_symbol` named `instrument_id` from `start` until the day before `end`."""
    return SymbolMapping(raw_symbol, [Interval(start, end, str(instrument_id))])


def dbn_content(
    schema: Schema,
    mappings: Sequence[SymbolMapping],
    records: Sequence[DBNRecord],
    stype_out: SType = INSTRUMENT_ID,
    version: int = 3,
) -> bytes:
    """A DBN file's bytes: the metadata of a parent-symbol query on CME Globex, then the records."""
    metadata = Metadata(
        dataset="GLBX.MDP3",
        start=utc(2010, 1, 1),
        stype_in=SType("parent"),
        stype_out=stype_out,
        schema=schema,
        symbols=["ES.FUT"],
        partial=[],
        not_found=[],
        mappings=list(mappings),
        end=utc(2030, 1, 1),
        version=version,
    )
    return metadata.encode() + b"".join(bytes(record) for record in records)


def write_dbn(path: Path, content: bytes) -> Path:
    """Write `content` to `path`, compressed with zstd by the vendor's encoder when the name
    ends in `.zst`."""
    if path.name.endswith(".zst"):
        compressed = io.BytesIO()
        transcoder = Transcoder(compressed, Encoding("dbn"), Compression("zstd"))
        transcoder.write(content)
        transcoder.finish()
        content = compressed.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
