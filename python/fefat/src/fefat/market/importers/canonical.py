"""From a vendor's records to the canonical store's partitions (ADR-0019, `02-engine-and-data.md`
§1.1 to 1.3).

`RecordPlacement` places one DBN file's frames, as `fefat.market.importers.dbn.read_dbn` yields
them, ready for the store:

- Each record gets its contract from one join with the file's symbology (`symbology_contracts`):
  the interval covering its `instrument_id` on the UTC date of its clock, each interval cut to
  the days its instrument has records (`active_days`, a first pass over the file), since the
  vendor's interval can run on years after its contract expired. A record no interval covers,
  or two cover, is refused. Spread and strategy symbols are set aside with a count.
- Bars and ticks get the trade date of their session
  (`SessionTable.assign_trade_dates_or_previous`). A record outside every session takes the
  session before it and is counted per trade date, since the holiday rules of the years before
  2024 are unchecked (step 1.3). Records dated before their product's first trade date are set
  aside per symbol: the vendor maps a contract from its listing, weeks before a new product
  trades. Definitions and statistics carry no trade date and are kept whole per contract.

`fefat.market.importers.file_writer` drives it with the file's clock check and the partition
buffers.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.contracts import ACTIVE_DAYS_COLUMNS, symbology_contracts
from fefat.market.importers.dbn import DbnMetadata
from fefat.market.instruments import InstrumentTable
from fefat.market.layout import (
    Dataset,
    Partition,
    Partitioning,
    YearMonth,
    partitioning,
)
from fefat.market.schema import BarSchemaName, SchemaKind, SchemaName, polars_schema

SPREAD_COUNTS = pl.Schema({"raw_symbol": pl.String, "records": pl.UInt32})
EARLY_COUNTS = pl.Schema(
    {
        "raw_symbol": pl.String,
        "records": pl.UInt32,
        "first_trade_date": pl.Date,
        "last_trade_date": pl.Date,
    }
)
DAY_COUNTS = pl.Schema({"trade_date": pl.Date, "records": pl.UInt32})
CONTRACT_COUNTS = pl.Schema(
    {
        "root": pl.String,
        "contract": pl.String,
        "expiry": pl.String,
        "records": pl.UInt32,
        "first_instant": pl.Int64,
        "last_instant": pl.Int64,
    }
)
_NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class PlacedRecords:
    """One frame of records placed: the canonical rows by partition, and what was counted or
    set aside, as small frames the file's report adds up."""

    partitions: Mapping[Partition, pl.DataFrame]
    contracts: pl.DataFrame
    spreads: pl.DataFrame
    early: pl.DataFrame
    outside_sessions: pl.DataFrame
    unreliable_ts_recv: pl.DataFrame


class RecordPlacement:
    """Places one file's records: each in its contract, from the file's symbology, and bars and
    ticks in the session of their trade date, from their root's session calendar (built once
    per root and kept in `cache_folder`)."""

    def __init__(
        self,
        source: Path,
        metadata: DbnMetadata,
        days: pl.DataFrame,
        provider: str,
        instruments: InstrumentTable,
        cache_folder: Path,
    ) -> None:
        self.schema_name: SchemaName = metadata.schema_name
        self._source = source
        self.metadata = metadata
        self._contracts = symbology_contracts(metadata.symbology, days).rename(
            {"raw_symbol": "mapped_symbol"}
        )
        _require_covered(days, self._contracts, source)
        self._provider = provider
        self._instruments = instruments
        self._cache_folder = cache_folder
        self._sessions: dict[str, SessionTable] = {}

    def clock_column(self) -> str:
        """The column a file of this schema is ordered by: bars have no `ts_recv`."""
        return clock_column(self.schema_name)

    def order_column(self) -> str:
        """The column a stored partition of this schema is sorted by."""
        return "ts_open" if self.schema_name.kind is SchemaKind.OHLCV else "ts_recv"

    def placed(self, records: pl.DataFrame) -> PlacedRecords:
        located = self._with_contracts(records)
        outright = pl.col("contract").is_not_null()
        spreads = _symbol_counts(located.filter(outright.not_()))
        outrights = located.filter(outright)
        if outrights.is_empty():
            return _spreads_only(spreads)
        kept, early = self._dated(outrights)
        return PlacedRecords(
            partitions=self._partitions(kept),
            contracts=self._contract_counts(kept),
            spreads=spreads,
            early=early,
            outside_sessions=_day_counts(kept, "in_session", outside=True),
            unreliable_ts_recv=_day_counts(kept, "bad_ts_recv", outside=False),
        )

    def _with_contracts(self, records: pl.DataFrame) -> pl.DataFrame:
        """The records with the raw symbol, root, contract, and expiry of the one interval that
        covers each; a record no interval covers, or two cover, is refused."""
        numbered = records.with_row_index("record").with_columns(_utc_day(self.clock_column()))
        covering = pl.col("day").is_between(pl.col("start_date"), pl.col("end_date"), closed="left")
        located = numbered.join(self._contracts, on="instrument_id").filter(covering)
        if located.height != numbered.height or located.get_column("record").is_duplicated().any():
            self._refuse_uncovered(numbered, located)
        return located.sort("record").drop("record", "day", "start_date", "end_date")

    def _refuse_uncovered(self, numbered: pl.DataFrame, located: pl.DataFrame) -> None:
        missing = numbered.join(located.select("record"), on="record", how="anti").sort("record")
        if not missing.is_empty():
            instrument_id, day = missing.select("instrument_id", "day").row(0)
            raise ValueError(
                f"Expected the symbology of {self._source} to cover every record, got none for "
                f"instrument_id {instrument_id} on {day} ({missing.height} records uncovered)."
            )
        doubled = located.filter(pl.col("record").is_duplicated()).sort("record", "mapped_symbol")
        record, instrument_id, day = doubled.select("record", "instrument_id", "day").row(0)
        covering = doubled.filter(pl.col("record") == record).get_column("mapped_symbol")
        symbols = ", ".join(covering.to_list())
        raise ValueError(
            f"Expected one symbology interval covering instrument_id {instrument_id} on {day} in "
            f"{self._source}, got the intervals of {symbols}."
        )

    def _dated(self, outrights: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Bars and ticks with their trade date and `in_session`, and those dated before their
        product's first trade date counted apart; other records pass undated."""
        if self.schema_name.kind not in (SchemaKind.OHLCV, SchemaKind.TRADES, SchemaKind.TBBO):
            return outrights, pl.DataFrame(schema=EARLY_COUNTS)
        roots = outrights.partition_by("root", as_dict=True, maintain_order=True)
        dated = pl.concat([self._dated_root(str(root), rows) for (root,), rows in roots.items()])
        before = pl.col("trade_date") < pl.col("first_trade_date")
        early = (
            dated.filter(before)
            .group_by("mapped_symbol")
            .agg(
                records=pl.len(),
                first_trade_date=pl.col("trade_date").min(),
                last_trade_date=pl.col("trade_date").max(),
            )
            .rename({"mapped_symbol": "raw_symbol"})
        )
        return dated.filter(before.not_()), early

    def _dated_root(self, root: str, rows: pl.DataFrame) -> pl.DataFrame:
        first_trade_date = self._instruments.first_trade_date(root)
        dated = self._sessions_of(root).assign_trade_dates_or_previous(rows, self.clock_column())
        return dated.with_columns(first_trade_date=pl.lit(first_trade_date))

    def _sessions_of(self, root: str) -> SessionTable:
        if root not in self._sessions:
            # shortcut: the calendar of the root's newest instrument version, as the calendar
            # check takes it; date by version when a root's calendar changes over time.
            calendar = BUILT_IN[self._instruments.get(root).calendar_id]
            self._sessions[root] = sessions_of(calendar, self._cache_folder)
        return self._sessions[root]

    def _contract_counts(self, kept: pl.DataFrame) -> pl.DataFrame:
        clock = pl.col(self.clock_column())
        return kept.group_by("root", "contract", "expiry").agg(
            records=pl.len(), first_instant=clock.min(), last_instant=clock.max()
        )

    def _partitions(self, kept: pl.DataFrame) -> dict[Partition, pl.DataFrame]:
        columns = list(polars_schema(self.schema_name))
        canonical = _canonical(kept, self.schema_name).with_columns(
            partition_key=_partition_key(self.schema_name)
        )
        groups = canonical.partition_by(
            "root", "contract", "partition_key", as_dict=True, maintain_order=True
        )
        return {
            self._partition(str(root), str(contract), key): rows.select(columns)
            for (root, contract, key), rows in groups.items()
        }

    def _partition(self, root: str, contract: str, key: object) -> Partition:
        dataset = Dataset(provider=self._provider, schema_name=self.schema_name, root=root)
        if partitioning(self.schema_name) is Partitioning.MONTH and isinstance(key, date):
            return Partition(
                dataset=dataset, contract=contract, key=YearMonth(year=key.year, month=key.month)
            )
        if isinstance(key, date):
            return Partition(dataset=dataset, contract=contract, key=key)
        return Partition(dataset=dataset, contract=contract, key=None)


def _require_covered(days: pl.DataFrame, contracts: pl.DataFrame, source: Path) -> None:
    """Refuse, before the second pass writes anything, a file with records on a day that no
    symbology interval of their instrument covers, or that two cover."""
    covering = pl.col("day").is_between(pl.col("start_date"), pl.col("end_date"), closed="left")
    covered = days.join(contracts, on="instrument_id").filter(covering)
    missing = days.join(covered, on=["instrument_id", "day"], how="anti").sort(
        "day", "instrument_id"
    )
    if not missing.is_empty():
        instrument_id, day = missing.select("instrument_id", "day").row(0)
        raise ValueError(
            f"Expected the symbology of {source} to cover every record, got none for "
            f"instrument_id {instrument_id} on {day} ({missing.height} instrument days uncovered)."
        )
    doubled = covered.filter(pl.struct("instrument_id", "day").is_duplicated()).sort("day")
    if not doubled.is_empty():
        instrument_id, day = doubled.select("instrument_id", "day").row(0)
        raise ValueError(
            f"Expected one symbology interval covering instrument_id {instrument_id} on {day} in "
            f"{source}, got {doubled.height} intervals over its days."
        )


def clock_column(schema_name: SchemaName) -> str:
    """The column a DBN file of the schema is ordered by: `ts_recv`, or `ts_event` for bars,
    which have no `ts_recv`."""
    return "ts_event" if schema_name.kind is SchemaKind.OHLCV else "ts_recv"


def active_days(records: Iterable[pl.DataFrame], schema_name: SchemaName) -> pl.DataFrame:
    """The UTC dates on which each instrument_id has records in a file's frames, with the
    columns of `ACTIVE_DAYS_COLUMNS`, from a first pass over the file."""
    day = _utc_day(clock_column(schema_name))
    seen = [frame.select("instrument_id", day).unique() for frame in records]
    return pl.concat([pl.DataFrame(schema=ACTIVE_DAYS_COLUMNS), *seen]).unique()


def _utc_day(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Datetime("ns")).dt.date().alias("day")


def _canonical(kept: pl.DataFrame, schema_name: SchemaName) -> pl.DataFrame:
    """The rows with the store's columns of the schema, and the root and contract beside them:
    a vendor's bar opens at its `ts_event` and carries no trade count."""
    if not isinstance(schema_name, BarSchemaName):
        return kept
    width = schema_name.timeframe.nominal_seconds() * _NANOSECONDS_PER_SECOND
    return kept.with_columns(
        ts_open=pl.col("ts_event"),
        ts_close=pl.col("ts_event") + width,
        trade_count=pl.lit(None, dtype=pl.UInt32),
    )


def _partition_key(schema_name: SchemaName) -> pl.Expr:
    split = partitioning(schema_name)
    if split is Partitioning.TRADE_DATE:
        return pl.col("trade_date")
    if split is Partitioning.MONTH:
        return pl.col("trade_date").dt.truncate("1mo")
    return pl.lit(None, dtype=pl.Date)


def _spreads_only(spreads: pl.DataFrame) -> PlacedRecords:
    """A frame of records without one outright: nothing to write, the spreads counted."""
    no_days = pl.DataFrame(schema=DAY_COUNTS)
    return PlacedRecords(
        partitions={},
        contracts=pl.DataFrame(schema=CONTRACT_COUNTS),
        spreads=spreads,
        early=pl.DataFrame(schema=EARLY_COUNTS),
        outside_sessions=no_days,
        unreliable_ts_recv=no_days,
    )


def _symbol_counts(spreads: pl.DataFrame) -> pl.DataFrame:
    return (
        spreads.group_by("mapped_symbol")
        .agg(records=pl.len())
        .rename({"mapped_symbol": "raw_symbol"})
    )


def _day_counts(kept: pl.DataFrame, column: str, *, outside: bool) -> pl.DataFrame:
    """Per trade date, the records whose `column` is false (`outside`) or true; none where the
    records carry no such column."""
    if column not in kept.columns:
        return pl.DataFrame(schema=DAY_COUNTS)
    counted = pl.col(column).not_() if outside else pl.col(column)
    return kept.filter(counted).group_by("trade_date").agg(records=pl.len())
