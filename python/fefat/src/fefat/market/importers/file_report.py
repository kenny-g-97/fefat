"""What an import of a trader's own file tells the trader (`fefat.market.importers.file_import`):
what the file holds once read with its profile, the preview of an import, the report of one that
wrote, and a file found imported before. Counts, dates, and problems; only a preview's first
records hold prices, which stay on the trader's screen (D-21).
"""

from datetime import date

from fefat.market.calendar_check import CalendarReport
from fefat.market.importers.report import DatasetMerge
from fefat.market.layout import Dataset
from fefat.market.schema import FrozenModel


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


class FilePreview(FrozenModel):
    """A file read with its profile, nothing written, and its first records as stored."""

    reading: FileReading
    first_rows: tuple[str, ...]

    def summary(self) -> str:
        reading = self.reading
        heading = (
            f"Preview of {reading.source} with the profile {reading.profile}; nothing was written."
        )
        verdict = (
            "It would import as it is."
            if not reading.refusals()
            else "It would be refused: fix the profile, or the file, and preview it again."
        )
        return "\n".join(
            [heading, *reading.lines(), "  First records as stored:", *self.first_rows, verdict]
        )


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


class AlreadyImported(FrozenModel):
    """A file `import_file` found imported before, kept under `raw` as `raw_path`."""

    source: str
    raw_path: str

    def summary(self) -> str:
        return (
            f"Nothing to import from {self.source}: it is imported already, as raw/{self.raw_path}."
        )
