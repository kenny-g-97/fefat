"""What an import of a trader's own file tells the trader (`fefat.market.importers.file_import`):
what the file holds once read with its profile, the preview of an import, the report of one that
wrote, and a file found imported before. Counts, dates, and problems: the account of what a file
adds to the store holds no price, while a preview's first records, and the first row a problem
quotes, show the file's own values, which stay on the trader's screen (D-21).
"""

from datetime import date

from fefat.market.calendar import utc_text
from fefat.market.calendar_check import CalendarReport
from fefat.market.engine_units import price_text
from fefat.market.importers.report import DIFFERING_VERDICT, DatasetMerge
from fefat.market.layout import Dataset
from fefat.market.schema import FrozenModel


class StoredBar(FrozenModel):
    """A bar of a file as the store would hold it (step 5.12): when it opens and closes, in
    nanoseconds since the Unix epoch, UTC, its trade date and contract, its prices in 1e-9 units,
    and its volume in lots."""

    ts_open: int
    ts_close: int
    trade_date: date
    contract: str
    open: int
    high: int
    low: int
    close: int
    volume: int

    def line(self) -> str:
        """The bar as a preview prints it, instants in UTC and prices as decimals."""
        return (
            f"    {utc_text(self.ts_open)} to {utc_text(self.ts_close)}, {self.trade_date}, "
            f"{self.contract}: open {price_text(self.open)}, high {price_text(self.high)}, "
            f"low {price_text(self.low)}, close {price_text(self.close)}, volume {self.volume}"
        )


class StoredPrint(FrozenModel):
    """A print of a file as the store would hold it (step 5.12): when it was received, in
    nanoseconds since the Unix epoch, UTC, its trade date and contract, its price in 1e-9 units,
    its size in lots, and its aggressor's side."""

    ts_recv: int
    trade_date: date
    contract: str
    price: int
    size: int
    side: str

    def line(self) -> str:
        """The print as a preview prints it, its instant in UTC and its price as a decimal."""
        return (
            f"    {utc_text(self.ts_recv)}, {self.trade_date}, {self.contract}: price "
            f"{price_text(self.price)}, size {self.size}, side {self.side}"
        )


class FileReading(FrozenModel):
    """What a file holds once read with its profile: the dataset its records go to, how many
    rows and records there are, their contracts and trade dates, what was left out, the
    problems, the calendar check, and the warnings: what every load of them repeats, and a
    calendar check that could not test their timing."""

    source: str
    profile: str
    dataset: Dataset
    rows_read: int
    records: int
    contracts: tuple[str, ...]
    first_trade_date: date | None
    last_trade_date: date | None
    bars_without_volume: int
    spread_rows: int
    problems: tuple[str, ...]
    calendar: CalendarReport
    warnings: tuple[str, ...]

    def refusals(self) -> list[str]:
        """The problems and offsets that stop an import."""
        return [*self.problems, *(offset.describe() for offset in self.calendar.offsets)]

    def lines(self) -> list[str]:
        dates = (
            "no trade date"
            if self.first_trade_date is None
            else (f"trade dates {self.first_trade_date} to {self.last_trade_date}")
        )
        contracts = ", ".join(self.contracts) if self.contracts else "none"
        left_out = [
            f"{self.bars_without_volume:,} bars without volume" if self.bars_without_volume else "",
            f"{self.spread_rows:,} rows of spread symbols" if self.spread_rows else "",
        ]
        shown = [part for part in left_out if part]
        return [
            f"  {self.rows_read:,} rows read; {self.records:,} records for {self.dataset.relative_folder()}, "
            f"contracts {contracts}, {dates}",
            *([f"  Left out: {' and '.join(shown)}"] if shown else []),
            *(f"  Warning: {warning}" for warning in self.warnings),
            *(["  Problems: none"] if not self.problems else ["  Problems:"]),
            *(f"    {problem}" for problem in self.problems),
            *(f"  Calendar check: {line}" for line in self.calendar.summary().splitlines()),
        ]


class AlreadyImported(FrozenModel):
    """A file `import_file` found imported before, kept under `raw` as `raw_path`."""

    source: str
    raw_path: str

    def summary(self) -> str:
        return (
            f"Nothing to import from {self.source}: it is imported already, as raw/{self.raw_path}."
        )


class FilePreview(FrozenModel):
    """A file read with its profile and against the store, nothing written: what it holds, its
    first records as stored, and what its import would find in the store, what the file adds
    to its dataset (`DatasetMerge`) or the file imported before; none where its reading refuses
    the file, before the store is read."""

    reading: FileReading
    first_records: tuple[StoredBar, ...] | tuple[StoredPrint, ...]
    against_the_store: DatasetMerge | AlreadyImported | None

    @property
    def first_rows(self) -> tuple[str, ...]:
        """The first records as the store holds them, a line each, as the preview prints them."""
        return tuple(record.line() for record in self.first_records)

    def refusals(self) -> list[str]:
        """What would stop the import: the reading's problems and offsets, and records that
        differ from the store's while the import does not let the file's stand; nothing for a
        file imported before, whose import changes nothing."""
        found = self.against_the_store
        if isinstance(found, AlreadyImported):
            return []
        if found is None or not found.refuses():
            return self.reading.refusals()
        differing = f"records that differ from the ones the store holds: {found.disagreement()}"
        return [*self.reading.refusals(), differing]

    def summary(self) -> str:
        reading, found = self.reading, self.against_the_store
        heading = (
            f"Preview of {reading.source} with the profile {reading.profile}; nothing was written."
        )
        return "\n".join(
            [
                heading,
                *reading.lines(),
                "  First records as stored:",
                *self.first_rows,
                *(found.lines() if isinstance(found, DatasetMerge) else []),
                self._verdict(),
            ]
        )

    def _verdict(self) -> str:
        found = self.against_the_store
        if isinstance(found, AlreadyImported):
            return (
                f"It is imported already, as raw/{found.raw_path}: importing it again changes "
                "nothing."
            )
        if self.reading.refusals():
            return "It would be refused: fix the profile, or the file, and preview it again."
        if found is not None and found.refuses():
            return DIFFERING_VERDICT
        return "It would import as it is."


class FileImportReport(FrozenModel):
    """What `import_file` wrote: the file kept under `raw`, what was read, what the file added
    to its dataset and what the store already held of it (`DatasetMerge`), and whether the new
    instrument was saved."""

    source: str
    raw_path: str
    reading: FileReading
    merge: DatasetMerge
    instrument_saved: bool

    def summary(self) -> str:
        saved = (
            ["  New instrument saved for later imports and loads."] if self.instrument_saved else []
        )
        return "\n".join(
            [
                f"Imported {self.source} with the profile {self.reading.profile}.",
                *self.reading.lines(),
                *saved,
                *self.merge.lines(),
                f"  Original kept as raw/{self.raw_path}",
            ]
        )
