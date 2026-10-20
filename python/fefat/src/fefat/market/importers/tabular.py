"""A trader's export read as a table of text (step 1.10): delimited text (CSV, TSV, `.txt`) or
Parquet, each plain, gzipped (`.gz`), or zipped (`.zip`, one file inside), as the import
profile's layout describes it (`fefat.market.importers.profiles`).

Every value is read as text, stripped of the spaces around it, so that the profile parses it
(`fefat.market.importers.profile_records`): Parquet's typed columns are written as text too,
instants as ISO 8601. A header row's names are stripped as well, of a byte-order mark too;
without a header the columns are `column_0`, `column_1`, ... by position. Empty lines are
left out.
"""

import gzip
import io
import zipfile
from pathlib import Path

import polars as pl

from fefat.market.importers.profiles import FileLayout

_PARQUET_SUFFIX = ".parquet"


def read_table(path: Path, layout: FileLayout) -> pl.DataFrame:
    """The file at `path` as text columns, laid out as `layout` says, or as Parquet."""
    name, content = _decompressed(path)
    if name.lower().endswith(_PARQUET_SUFFIX):
        return _as_text(pl.read_parquet(io.BytesIO(content)))
    table = pl.read_csv(
        io.BytesIO(content),
        separator=layout.delimiter,
        has_header=layout.header,
        infer_schema=False,
    )
    named = table.rename({column: column.lstrip("﻿").strip() for column in table.columns})
    stripped = named.with_columns(pl.all().fill_null("").str.strip_chars())
    return stripped.filter(pl.any_horizontal(pl.all() != ""))


def inner_file_name(path: Path) -> str:
    """The name of the file the records are in: the path's own, or the one a `.gz` or `.zip`
    holds, which the profile's contract pattern reads."""
    return _decompressed(path)[0]


def _decompressed(path: Path) -> tuple[str, bytes]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected a file to import, got no such file: {path}.")
    lowered = path.name.lower()
    if lowered.endswith(".gz"):
        return path.name[: -len(".gz")], gzip.decompress(path.read_bytes())
    if lowered.endswith(".zip"):
        return _single_member(path)
    return path.name, path.read_bytes()


def _single_member(path: Path) -> tuple[str, bytes]:
    with zipfile.ZipFile(path) as archive:
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
