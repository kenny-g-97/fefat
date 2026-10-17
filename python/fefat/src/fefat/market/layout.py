"""Where the canonical store keeps its files, and which files a request selects (ADR-0019).

A store folder holds a folder per provider, a folder per schema in each, and below:

    <provider>/<schema>/root=<root>/dataset.json
    <provider>/<schema>/root=<root>/contract=<contract>/date=<YYYY-MM-DD>/part.parquet
    <provider>/<schema>/root=<root>/contract=<contract>/month=<YYYY-MM>/part.parquet
    <provider>/<schema>/root=<root>/contract=<contract>/part.parquet

Trades, TBBO, and bars finer than a minute are split per trade date, one-minute bars per
month of their trade dates, and coarser bars, definitions, statistics, and funding are one
file per contract (`partitioning`). `dataset.json` holds what every partition of the dataset
shares: the unit of its sizes, its origin, and the licence scope its source gives the trader
(step 1.9). The folder `raw` beside the providers keeps the vendors' original files
(`fefat.market.raw_manifest`), and the folder `reports` the quality reports
(`fefat.market.quality`). What the files hold is `fefat.market.schema`.
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from fefat.config import REPORTS_FOLDER_NAME
from fefat.market.schema import (
    FrozenModel,
    RecordSchemaName,
    SchemaKind,
    SchemaName,
    Timeframe,
    TimeUnit,
    parse_schema_name,
)

RAW_FOLDER_NAME = "raw"
RESERVED_FOLDERS = {
    RAW_FOLDER_NAME: "the vendors' raw files",
    REPORTS_FOLDER_NAME: "the quality reports",
}
"""The folders beside the providers that are no provider, with what each holds."""
PARTITION_FILE_NAME = "part.parquet"
DATASET_METADATA_FILE_NAME = "dataset.json"
PARTITION_LAYOUT = (
    "<provider>/<schema>/root=<root>/contract=<contract>[/date=<YYYY-MM-DD>|/month=<YYYY-MM>]"
    f"/{PARTITION_FILE_NAME}"
)


def _not_a_reserved_folder(name: str) -> str:
    held = RESERVED_FOLDERS.get(name.lower())
    if held is not None:
        raise ValueError(f"Expected a provider, got {name!r}, the folder of {held}.")
    return name


FolderName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
]
"""A provider, root, or contract as a folder name: letters and digits, with dots, dashes,
and underscores inside (Windows drops a trailing dot, and the layout uses `/` and `=`)."""

ProviderName = Annotated[FolderName, AfterValidator(_not_a_reserved_folder)]
"""A provider's folder name; `raw` and `reports`, in any case, are the folders of the vendors'
files and of the quality reports."""


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
    one_minute = Timeframe(count=1, unit=TimeUnit.MINUTE).nominal_seconds()
    if seconds < one_minute:
        return Partitioning.TRADE_DATE
    if seconds == one_minute:
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

    def metadata_path(self) -> PurePosixPath:
        """The dataset's `dataset.json`, relative to the store folder."""
        return self.relative_folder() / DATASET_METADATA_FILE_NAME


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


class PartitionRequest(FrozenModel):
    """The partitions of one dataset whose keys touch a range of trade dates, both ends included:
    a trade-date key inside the range, a month key with any day in it, and a partition without a
    key (one file per contract) always. Selecting a file is not cutting its rows:
    `Store.scan` and `Store.read` keep the bars of the range, and records without a trade date
    come whole, for the reader to cut at `ts_recv`."""

    dataset: Dataset
    start: date
    end: date

    @model_validator(mode="after")
    def _starts_on_or_before_its_end(self) -> Self:
        if self.end < self.start:
            raise ValueError(
                f"Expected the start {self.start} on or before the end, got the end {self.end}."
            )
        return self

    def selects(self, partition: Partition) -> bool:
        """Whether the partition belongs to the dataset and its key touches the dates."""
        if partition.dataset != self.dataset:
            return False
        if isinstance(partition.key, YearMonth):
            return partition.key.overlaps(self.start, self.end)
        if isinstance(partition.key, date):
            return self.start <= partition.key <= self.end
        return True


class SizeUnit(FrozenModel):
    """What one unit of a `size` or `volume` column is: `lot` of `asset`, such as 1 contract
    or 0.001 BTC."""

    lot: Decimal = Field(gt=0)
    asset: str = Field(min_length=1)

    def __str__(self) -> str:
        return f"{self.lot} {self.asset}"


class DatasetOrigin(StrEnum):
    """How a dataset came into the store (D-37): imported from the trader's files, or synced
    through a connector to a source the trader connects, which waits for a later phase (D-38)."""

    IMPORT = "import"
    SYNC = "sync"


class DatasetMetadata(FrozenModel):
    """What every partition of a dataset shares, kept in the dataset's `dataset.json`: the unit
    of its sizes, its origin, and the licence scope the terms of its source give the trader
    (`fefat.market.sources`). Its provider is the folder it lies in."""

    size_unit: SizeUnit
    origin: DatasetOrigin
    licence_scope: str = Field(min_length=1)
