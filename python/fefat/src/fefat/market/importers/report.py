"""What an import tells the trader: per file, what was written and what was set aside, per
dataset, what the file adds to what the store holds of it (`DatasetMerge`, step 5.14), and per
batch download, the vendor's own word on its days. Counts and ranges only, never prices, so a
summary can go into a pull request (D-21).

`DatabentoImport.summary` is what `fefat data import databento` prints, and
`DatabentoPreview.summary` what it prints with `--preview`.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from enum import StrEnum
from itertools import groupby

from pydantic import Field

from fefat.market.calendar import counted, utc_text
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.schema import FrozenModel, SchemaKind, SchemaName

_LISTED_AT_MOST = 10
"""How many symbols or days a summary line names before it says how many more there are."""
DIFFERING_ADVICE = (
    "Where the file is an export, check its profile's time zone and bar stamping; where it holds "
    "a vendor's correction, or a bar the store took before it was complete, import it with "
    "--differing take-file, and its records stand."
)
"""What to do about records that differ from the store's, as their refusal and a preview say."""
DIFFERING_VERDICT = (
    f"It would be refused: its records differ from the ones the store holds. {DIFFERING_ADVICE}"
)
"""A preview's last line for a file whose import the differing records would refuse."""


class VendorCondition(StrEnum):
    """How complete the vendor says a day's data is (Databento's `condition.json`)."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    PENDING = "pending"
    MISSING = "missing"


class ConditionDay(FrozenModel):
    """A day the vendor marks other than available."""

    day: date
    condition: VendorCondition


class BatchReport(FrozenModel):
    """A batch download's job, the newest revision date of its days (none when the vendor
    gives no day one), and the days its vendor marks other than available."""

    job_id: str = Field(min_length=1)
    revised: date | None
    unavailable_days: tuple[ConditionDay, ...]

    def lines(self) -> list[str]:
        heading = f"Databento batch {self.job_id}, data revised up to {self.revised}."
        if self.revised is None:
            heading = f"Databento batch {self.job_id}, no revision date in its conditions."
        ordered = sorted(self.unavailable_days, key=lambda day: (day.condition, day.day))
        listed: list[str] = []
        for condition, days in groupby(ordered, key=lambda day: day.condition):
            named = [str(day.day) for day in days]
            listed.append(f"Days the vendor marks {condition} ({len(named)}): {', '.join(named)}")
        return [heading, *(listed or ["Days the vendor marks degraded: none"])]


class ContractRecords(FrozenModel):
    """The records written for one contract, with the first and last instant of their clock."""

    root: str
    contract: str
    expiry: str
    records: int = Field(ge=1)
    first_instant: int
    last_instant: int


class SymbolRecords(FrozenModel):
    """How many records of a spread or strategy symbol were set aside."""

    raw_symbol: str
    records: int = Field(ge=1)


class EarlySymbol(FrozenModel):
    """An outright's records dated before its product's first trade date, set aside."""

    raw_symbol: str
    records: int = Field(ge=1)
    first_trade_date: date
    last_trade_date: date


class DayRecords(FrozenModel):
    """How many records of a trade date a count found."""

    trade_date: date
    records: int = Field(ge=1)


class ClockDecrease(FrozenModel):
    """A record whose clock is earlier than the record before it: its place in the file,
    counted from 0, and both instants."""

    record: int = Field(ge=1)
    instant: int
    before: int


class DatasetMerge(FrozenModel):
    """What a file adds to one dataset, read against what the store holds of it (ADR-0021),
    under `on_differing`: the records it adds, those the store already holds, and those at the
    instants the two dispute, with the stored records at those instants; the trade dates that
    gain records, the new ones, which no partition the file touches held, apart from those the
    store holds; the differing records per trade date; and the partitions the import changes
    and leaves as they are."""

    dataset: str
    on_differing: DifferingRecords
    records_added: int = Field(ge=0)
    records_held: int = Field(ge=0)
    records_differing: int = Field(ge=0)
    stored_records_disputed: int = Field(ge=0)
    new_sessions: tuple[DayRecords, ...]
    extended_sessions: tuple[DayRecords, ...]
    differing_sessions: tuple[DayRecords, ...]
    partitions_changed: int = Field(ge=0)
    partitions_unchanged: int = Field(ge=0)

    def refuses(self) -> bool:
        """Whether the file's records differ from the store's and no import lets them stand."""
        return self.records_differing > 0 and self.on_differing is DifferingRecords.REFUSE

    def replaces(self) -> bool:
        """Whether the import takes the file's records in place of stored ones."""
        taken = self.on_differing is DifferingRecords.TAKE_THE_FILE
        return self.records_differing > 0 and taken

    def disagreement(self) -> str:
        """The records that differ, counted, with the first trade date that holds one."""
        dated = ""
        if self.differing_sessions:
            dated = f", the first on trade date {self.differing_sessions[0].trade_date}"
        return f"{self.records_differing:,} with other values in {self.dataset}{dated}"

    def lines(self) -> list[str]:
        differing = f"{self.records_differing:,} that differ"
        if self.replaces():
            stored = counted(self.stored_records_disputed, "stored record")
            differing = f"{differing}, the file's taken in place of {stored}"
        disputed = [f"    Records that differ: {_days(self.differing_sessions)}"]
        return [
            f"  {self.dataset}:",
            f"    New sessions: {_days(self.new_sessions)}",
            f"    Sessions the store holds that gain records: {_days(self.extended_sessions)}",
            f"    Records: {self.records_added:,} new, {self.records_held:,} already held, "
            f"{differing}",
            *(disputed if self.differing_sessions else []),
            f"    Partitions: {self.partitions_changed} that change, "
            f"{self.partitions_unchanged} unchanged",
        ]


class FileImport(FrozenModel):
    """One data file imported: its raw path, schema, DBN version, records and their range,
    contracts, what it adds to each dataset, and what was set aside or counted on the way."""

    path: str
    schema_name: SchemaName
    dbn_version: int
    records: int = Field(ge=0)
    first_instant: int | None
    last_instant: int | None
    contracts: tuple[ContractRecords, ...]
    merges: tuple[DatasetMerge, ...]
    spreads: tuple[SymbolRecords, ...]
    before_first_trade_date: tuple[EarlySymbol, ...]
    outside_sessions: tuple[DayRecords, ...]
    unreliable_ts_recv: tuple[DayRecords, ...]
    clock_decreases: int = Field(ge=0)
    first_clock_decrease: ClockDecrease | None

    def lines(self) -> list[str]:
        roots = groupby(self.contracts, key=lambda contract: contract.root)
        return [
            f"{self.path}: {self.schema_name}, DBN version {self.dbn_version}, "
            f"{counted(self.records, 'record')}{_range(self.first_instant, self.last_instant)}",
            *(f"  {_root_line(root, list(contracts))}" for root, contracts in roots),
            f"  Spreads and strategies set aside: {_spreads(self.spreads)}",
            f"  Before their product's first trade date: {_early(self.before_first_trade_date)}",
            f"  Outside every session: {_days(self.outside_sessions)}",
            *self._unreliable_line(),
            f"  Clock: {self._clock()}",
            *(line for merge in self.merges for line in merge.lines()),
        ]

    def _unreliable_line(self) -> list[str]:
        if self.schema_name.kind not in (SchemaKind.TRADES, SchemaKind.TBBO):
            return []
        return [f"  Unreliable ts_recv: {_days(self.unreliable_ts_recv)}"]

    def _clock(self) -> str:
        first = self.first_clock_decrease
        if first is None:
            return "never decreases"
        return (
            f"decreases {counted(self.clock_decreases, 'time')}, the first at record "
            f"{first.record}: {utc_text(first.instant)} after {utc_text(first.before)}"
        )


class DatabentoFiles(FrozenModel):
    """What a Databento folder or file holds for the store: the data files read against it,
    those the raw manifest already held, the vendor's daily bars, which are skipped, and the
    batch they came in."""

    source: str
    batch: BatchReport | None
    files: tuple[FileImport, ...]
    already_imported: tuple[str, ...]
    daily_bars_skipped: tuple[str, ...]

    def lines(self) -> list[str]:
        """A few lines per file, with every day the vendor marks degraded."""
        lines: list[str] = []
        if self.batch is not None:
            lines.extend(self.batch.lines())
        for file in self.files:
            lines.extend(file.lines())
        if self.already_imported:
            lines.append(f"Already imported: {', '.join(self.already_imported)}")
        if self.daily_bars_skipped:
            lines.append(
                "Skipped, the vendor's daily bars are cut on UTC days rather than sessions: "
                + ", ".join(self.daily_bars_skipped)
            )
        return lines


class DatabentoImport(DatabentoFiles):
    """What `import_databento` did with a folder or file."""

    def summary(self) -> str:
        return "\n".join([self._heading(), *self.lines()])

    def _heading(self) -> str:
        if self.files:
            return f"Imported {counted(len(self.files), 'file')} from {self.source}."
        if self.already_imported:
            return f"Nothing to import from {self.source}: every file is already imported."
        return f"Nothing to import from {self.source}."


class DatabentoPreview(DatabentoFiles):
    """What `preview_databento` found that `import_databento` would do with a folder or file,
    nothing written."""

    def refuses(self) -> bool:
        """Whether the import would be refused for records that differ from the store's."""
        return any(merge.refuses() for file in self.files for merge in file.merges)

    def summary(self) -> str:
        heading = f"Preview of {self.source}; nothing was written."
        return "\n".join([heading, *self.lines(), self._verdict()])

    def _verdict(self) -> str:
        if self.refuses():
            return DIFFERING_VERDICT
        return "It would import as it is." if self.files else "It would import nothing."


def _range(first: int | None, last: int | None) -> str:
    if first is None or last is None:
        return ""
    return f" from {utc_text(first)} to {utc_text(last)}"


def _root_line(root: str, contracts: Sequence[ContractRecords]) -> str:
    by_expiry = sorted(contracts, key=lambda contract: contract.expiry)
    names = by_expiry[0].contract
    if len(by_expiry) > 1:
        names = f"{names} to {by_expiry[-1].contract}"
    records = sum(contract.records for contract in contracts)
    first = min(contract.first_instant for contract in contracts)
    last = max(contract.last_instant for contract in contracts)
    return (
        f"{root}: {counted(len(contracts), 'contract')}, {names}, "
        f"{counted(records, 'record')}{_range(first, last)}"
    )


def _spreads(spreads: Sequence[SymbolRecords]) -> str:
    if not spreads:
        return "none"
    records = sum(spread.records for spread in spreads)
    return f"{counted(len(spreads), 'symbol')}, {counted(records, 'record')}"


def _early(symbols: Sequence[EarlySymbol]) -> str:
    if not symbols:
        return "none"
    named = _listed(
        f"{symbol.raw_symbol} {counted(symbol.records, 'record')} on "
        f"{symbol.first_trade_date} to {symbol.last_trade_date}"
        for symbol in symbols
    )
    return f"{counted(len(symbols), 'symbol')}: {named}"


def _days(days: Sequence[DayRecords]) -> str:
    if not days:
        return "none"
    records = sum(day.records for day in days)
    named = _listed(f"{day.trade_date} ({day.records:,})" for day in days)
    return f"{counted(records, 'record')} on {counted(len(days), 'trade date')}: {named}"


def _listed(texts: Iterable[str]) -> str:
    listed = list(texts)
    shown = ", ".join(listed[:_LISTED_AT_MOST])
    if len(listed) <= _LISTED_AT_MOST:
        return shown
    return f"{shown}, and {len(listed) - _LISTED_AT_MOST:,} more"
