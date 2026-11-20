"""The check of a store's trade dates against its session calendars as they are now (step 5.16,
ADR-0024, `02-engine-and-data.md` §1.3). A record keeps the trade date its import's session table
gave it, so after a calendar changes, a holiday corrected, a former close, or a saved
instrument's hours edited, a stored record can lie outside the session of its trade date and the
break after it, which an import of the same records refuses
(`fefat.market.importers.stored_neighbours`, `partition_merge`). `verify_trade_dates` lists them
per dataset, contract, and stored trade date with the trade date the calendar gives them now,
and with them the daily bars that do not open at their session's open; `fefat data
verify-trade-dates [<root>]` prints the list. It reads the store and writes nothing: such
records are dated again by deleting the provider's data of the root and importing its files
again (step 5.18).

    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    print(verify_trade_dates(store, paths.cache_dir, instrument_table(store.folder)).summary())
"""

import itertools
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import Field

from fefat.market.calendar import SessionTable, counted, utc_text
from fefat.market.calendar_check import checked_datasets, dated_rows
from fefat.market.importers.partition_merge import deleted_and_imported_again
from fefat.market.instruments import InstrumentTable
from fefat.market.layout import Dataset, Partition
from fefat.market.quality_checks import OUT_OF_SESSION
from fefat.market.schema import FrozenModel, SchemaKind, holds_daily_bars
from fefat.market.store import Store

PARTITIONS_A_QUERY = 200
"""How many partitions one query reads: one over the 1,780 of a dataset of the builder's made
Polars warn that it ran out of threads."""


class DatedOtherwise(FrozenModel):
    """Records of a dataset's contract stored under a trade date whose session, with the break
    after it, does not hold them under the calendar as it is now, or daily bars that do not open
    at that session's open: how many, the first and last of their instants, in nanoseconds since
    the Unix epoch, UTC, and the trade date the calendar gives the first of them now, a daily
    bar's own where that date still has a session."""

    dataset: Dataset
    contract: str
    stored_trade_date: date
    records: int = Field(ge=1)
    first_instant: int
    last_instant: int
    trade_date_now: date

    def describe(self) -> str:
        """One line: where the records are stored, how many, when, and how the calendar dates
        them now."""
        first, last = utc_text(self.first_instant), utc_text(self.last_instant)
        held = (
            f"{self.dataset.relative_folder()} {self.contract} {self.stored_trade_date}: "
            f"{counted(self.records, 'record')} "
            + (f"at {first}" if first == last else f"from {first} to {last}")
        )
        if self.trade_date_now == self.stored_trade_date:
            return f"{held}, while the calendar opens that date otherwise now"
        return f"{held}, which the calendar dates {self.trade_date_now} now"


class TradeDateReport(FrozenModel):
    """What `verify_trade_dates` read, and the records it found dated otherwise, sorted by
    dataset, contract, and stored trade date."""

    records_checked: int = Field(ge=0)
    datasets_checked: int = Field(ge=0)
    dated_otherwise: tuple[DatedOtherwise, ...]

    def summary(self) -> str:
        """The records read, then a line for each stored trade date that holds records dated
        otherwise and how to date them again, or a line saying there are none."""
        heading = (
            f"Records checked: {self.records_checked:,} of "
            f"{counted(self.datasets_checked, 'dataset')}. Dated otherwise than the calendar "
            "dates them now:"
        )
        found = self.dated_otherwise
        if not found:
            return f"{heading} none."
        records = counted(sum(each.records for each in found), "record")
        dates = counted(len({each.stored_trade_date for each in found}), "stored trade date")
        datasets = {(each.dataset.provider, each.dataset.root): each.dataset for each in found}
        return "\n".join(
            [
                f"{heading} {records} on {dates}:",
                *(f"  {each.describe()}" for each in found),
                *(
                    f"To date them again, {deleted_and_imported_again(dataset)}."
                    for dataset in datasets.values()
                ),
            ]
        )


def verify_trade_dates(
    store: Store, cache_folder: Path, instruments: InstrumentTable, root: str | None = None
) -> TradeDateReport:
    """The store's trades, TBBO, and bars, of `root` alone where it is named, against their
    roots' session calendars in `instruments`, whose tables `cache_folder` keeps (module
    docstring); a root the store holds none of is refused."""
    checked = [
        (dataset, partitions)
        for dataset, partitions in checked_datasets(store)
        if root is None or dataset.root == root
    ]
    if not checked:
        named = "any product" if root is None else root
        raise ValueError(f"Expected trades or bars of {named} in the store, got none.")
    records, found = 0, list[DatedOtherwise]()
    for dataset, partitions in checked:
        sessions = instruments.sessions_of(dataset.root, cache_folder)
        for batch in itertools.batched(partitions, PARTITIONS_A_QUERY):
            read, otherwise = _dated_otherwise(store, dataset, batch, sessions)
            records += read
            found.extend(otherwise)
    return TradeDateReport(
        records_checked=records, datasets_checked=len(checked), dated_otherwise=tuple(found)
    )


def _dated_otherwise(
    store: Store, dataset: Dataset, partitions: Sequence[Partition], sessions: SessionTable
) -> tuple[int, list[DatedOtherwise]]:
    """How many records `partitions` hold, and those of them dated otherwise, per contract and
    stored trade date, with the trade date the calendar gives them now."""
    rows = _stored_dates(store, dataset, partitions)
    stored = pl.col("stored_trade_date")
    first, last, records = (
        rows.select(stored.min(), stored.max().alias("last"), pl.len()).collect().row(0)
    )
    if not records:
        return 0, []
    bounds = sessions.between_with_next_opens(first, last)
    outside = _outside_their_sessions(dataset, rows, bounds)
    if outside.is_empty():
        return records, []
    return records, _dated_now(dataset, outside, sessions)


def _stored_dates(store: Store, dataset: Dataset, partitions: Sequence[Partition]) -> pl.LazyFrame:
    """Each stored record's contract, its instant on the dataset's clock, and its stored trade
    date."""
    clock = "ts_open" if dataset.schema_name.kind is SchemaKind.OHLCV else "ts_recv"
    return pl.concat(
        [
            dated_rows(store, partition).select(
                contract=pl.lit(partition.contract),
                instant=pl.col(clock),
                stored_trade_date=pl.col("trade_date"),
            )
            for partition in partitions
        ]
    )


def _outside_their_sessions(
    dataset: Dataset, rows: pl.LazyFrame, bounds: pl.DataFrame
) -> pl.DataFrame:
    """Per contract and stored trade date, the records outside that date's session and the break
    after it, as the quality report's out-of-session finding reads them, or, of daily bars, at
    another open than the session's, with whether the date has a session now. `bounds` are the
    sessions of `SessionTable.between_with_next_opens`."""
    instant = pl.col("instant")
    outside = OUT_OF_SESSION
    if holds_daily_bars(dataset.schema_name):
        outside = pl.col("open").is_null() | (instant != pl.col("open"))
    sessions = bounds.select("open", "next_open", stored_trade_date="trade_date")
    return (
        rows.join(sessions.lazy(), on="stored_trade_date", how="left")
        .filter(outside)
        .group_by("contract", "stored_trade_date")
        .agg(
            records=pl.len(),
            first_instant=instant.min(),
            last_instant=instant.max(),
            has_session=pl.col("open").is_not_null().first(),
        )
        .collect()
    )


def _dated_now(
    dataset: Dataset, outside: pl.DataFrame, sessions: SessionTable
) -> list[DatedOtherwise]:
    """The records of `_outside_their_sessions` with the trade date the calendar gives the first
    of them now; a daily bar whose date still has a session keeps that date, since a daily bar
    is dated by the date it names, and only opens otherwise."""
    now = sessions.assign_trade_dates_or_previous(outside, "first_instant")
    if holds_daily_bars(dataset.schema_name):
        named = pl.when(pl.col("has_session")).then(pl.col("stored_trade_date"))
        now = now.with_columns(trade_date=named.otherwise(pl.col("trade_date")))
    return [
        DatedOtherwise(
            dataset=dataset,
            contract=row["contract"],
            stored_trade_date=row["stored_trade_date"],
            records=row["records"],
            first_instant=row["first_instant"],
            last_instant=row["last_instant"],
            trade_date_now=row["trade_date"],
        )
        for row in now.sort("contract", "stored_trade_date").iter_rows(named=True)
    ]
