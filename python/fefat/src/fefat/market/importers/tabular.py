"""A trader's export read as a table of text (step 1.10): delimited text (CSV, TSV, `.txt`) or
Parquet, each plain, gzipped (`.gz`), or zipped (`.zip`, one file inside), as the import
profile's layout describes it (`fefat.market.importers.profiles`).

Every value is read as text, stripped of the spaces around it, so that the profile parses it
(`fefat.market.importers.profile_records`): Parquet's typed columns are written as text too,
instants as ISO 8601, and an empty value as empty text, as a delimited file gives it. A header
row's names are stripped as well, of a byte-order mark too; without a header the columns are
`column_0`, `column_1`, ... by position. Empty lines are left out, and a file without a line
is refused.

`sniffed_layout` guesses a delimited file's layout from its first lines, for the import wizard,
which shows a file's rows before a profile reads it (step 5.12).
"""

import csv
import gzip
import io
import zipfile
from pathlib import Path

import polars as pl

from fefat.market.importers.profiles import FileLayout

_PARQUET_SUFFIX = ".parquet"
_SNIFFED_DELIMITERS = ",;\t|"
_SNIFFED_BYTES = 64 * 1024
GUESSED_LAYOUT = FileLayout(delimiter=",", header=True)
"""The layout shown for Parquet, whose columns are its own, and for a file whose first lines
give no delimiter: a comma and a header, which the trader changes where they are wrong."""


def sniffed_layout(path: Path, content: bytes) -> FileLayout:
    """The layout of the delimited file `path`, whose bytes are `content`, or of the one its
    `.gz` or `.zip` holds, as Python's `csv.Sniffer` reads its first lines: its delimiter among
    comma, semicolon, tab, and bar, and whether its first row names its columns."""
    name, unpacked = _unpacked(path, content)
    if name.lower().endswith(_PARQUET_SUFFIX):
        return GUESSED_LAYOUT
    text = unpacked[:_SNIFFED_BYTES].decode("utf-8", errors="replace").lstrip("﻿")
    sample = text if len(unpacked) <= _SNIFFED_BYTES else text[: text.rfind("\n") + 1]
    sniffer = csv.Sniffer()
    try:
        delimiter = sniffer.sniff(sample, delimiters=_SNIFFED_DELIMITERS).delimiter
        return FileLayout(delimiter=delimiter, header=sniffer.has_header(sample))
    except csv.Error:
        return GUESSED_LAYOUT


def read_table(path: Path, content: bytes, layout: FileLayout) -> tuple[str, pl.DataFrame]:
    """The name of the file the records are in, `path`'s own or the one a `.gz` or `.zip`
    holds, which the profile's contract pattern reads, and its rows as text columns, laid out
    as `layout` says, or as Parquet; `content` is the bytes of `path`, read once."""
    name, unpacked = _unpacked(path, content)
    table = _raw_table(name, unpacked, layout)
    named = table.rename({column: column.lstrip("﻿").strip() for column in table.columns})
    stripped = named.with_columns(pl.all().fill_null("").str.strip_chars())
    return name, stripped.filter(pl.any_horizontal(pl.all() != ""))


def _raw_table(name: str, content: bytes, layout: FileLayout) -> pl.DataFrame:
    if name.lower().endswith(_PARQUET_SUFFIX):
        return _as_text(pl.read_parquet(io.BytesIO(content)))
    try:
        return pl.read_csv(
            io.BytesIO(content),
            separator=layout.delimiter,
            has_header=layout.header,
            infer_schema=False,
        )
    except pl.exceptions.NoDataError as error:
        raise ValueError(f"Expected rows in {name}, got an empty file.") from error


def _unpacked(path: Path, content: bytes) -> tuple[str, bytes]:
    lowered = path.name.lower()
    if lowered.endswith(".gz"):
        return path.name[: -len(".gz")], gzip.decompress(content)
    if lowered.endswith(".zip"):
        return _single_member(path, content)
    return path.name, content


def _single_member(path: Path, content: bytes) -> tuple[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) != 1:
            names = ", ".join(member.filename for member in members) or "none"
            raise ValueError(
                f"Expected one file inside {path}, got {len(members)}: {names}. Import them one "
                "by one."
            )
        return Path(members[0].filename).name, archive.read(members[0])


def _as_text(table: pl.DataFrame) -> pl.DataFrame:
    """A Parquet file's columns as text: instants in UTC as ISO 8601 with nanoseconds and `Z`,
    naive ones without it, and everything else as Polars writes it."""
    columns = []
    for name, dtype in table.schema.items():
        column = pl.col(name)
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            column = column.dt.convert_time_zone("UTC").dt.strftime("%Y-%m-%dT%H:%M:%S%.9fZ")
        elif isinstance(dtype, pl.Datetime):
            column = column.dt.strftime("%Y-%m-%dT%H:%M:%S%.9f")
        columns.append(column.cast(pl.String).alias(name))
    return table.select(columns)
