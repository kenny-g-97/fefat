"""The checks of the quality report that read every record (step 1.8, `fefat.market.quality`):
per dataset, contract, and trade date, the records, the repeated ones, those outside their
session, those received in the break after its close or inside its halts, the decreases of
the clock, and the prices of zero or below; and the sessions of a dataset without a record.

A record's instant is its `ts_recv` (trades and TBBO) or its `ts_open` (bars), and its
session is that of its partition's trade date (ticks) or of its own `trade_date` (bars). It
is outside its session before the open or from the next session's open on, and in the break
from the close until that open, where a print keeps its trade date (D-43).
"""

from collections.abc import Mapping
from datetime import date

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.coverage import DatasetCoverage
from fefat.market.layout import Dataset, Partition
from fefat.market.quality_report import FINDING_COLUMNS, QualityFinding
from fefat.market.schema import SchemaKind
from fefat.market.store import Store

NEGATIVE_PRICES_ALLOWED: Mapping[str, tuple[date, ...]] = {
    "CL": (date(2020, 4, 20), date(2020, 4, 21)),
}
"""The trade dates on which a root's prices may be zero or below: WTI crude's May 2020
contract traded below zero on 2020-04-20, settling at -37.63, and expired on 04-21 (CFTC,
"Interim Staff Report: Trading in NYMEX WTI Crude Oil Futures Contract Leading up to, on, and
around April 20, 2020", November 2020)."""
RECORD_FINDINGS = {
    "duplicates": QualityFinding.DUPLICATES,
    "out_of_session": QualityFinding.OUT_OF_SESSION,
    "clock_decreases": QualityFinding.CLOCK_DECREASES,
    "non_positive_prices": QualityFinding.NON_POSITIVE_PRICES,
}
"""The counts of `checked_records` that are findings, with the finding each counts."""


def session_bounds(sessions: SessionTable, first: date, last: date) -> pl.DataFrame:
    """The sessions of the trade dates from `first` to `last`, each with the open of the next,
    which ends the break in which a print still takes its trade date (D-43)."""
    after_last = sessions.following(last).open
    return sessions.between(first, last).with_columns(
        next_open=pl.col("open").shift(-1).fill_null(after_last)
    )


def checked_records(
    store: Store, datasets: Mapping[Dataset, DatasetCoverage], bounds: pl.DataFrame, root: str
) -> pl.DataFrame:
    """Per schema, contract, and trade date of the `datasets`' records: their instruments
    (`instrument_ids`), how many there are (`records`), and how many are duplicates,
    out of session, received in the break or inside a halt, after a decrease of the clock,
    or priced at zero or below. `bounds` are the sessions of `session_bounds`. Each partition
    marks its own records, in their stored order; one query then counts them all."""
    marked = pl.concat(
        [
            _marked(store, file.partition)
            for dataset in datasets
            for file in store.list_partitions(dataset)
        ]
    ).join(
        bounds.select("trade_date", "open", "close", "next_open").lazy(),
        on="trade_date",
        how="left",
    )
    keys = ("schema", "contract", "trade_date")
    instant = pl.col("instant")
    halts = (
        bounds.select("trade_date", "halts").explode("halts").drop_nulls("halts").unnest("halts")
    )
    in_halts = (
        marked.select(*keys, "instant")
        .join(halts.lazy(), on="trade_date")
        .filter((instant >= pl.col("start")) & (instant < pl.col("end")))
        .group_by(keys)
        .agg(halt_prints=pl.len().cast(pl.Int64))
    )
    allowed = pl.Series(NEGATIVE_PRICES_ALLOWED.get(root, ()), dtype=pl.Date).implode()
    outside = (
        pl.col("open").is_null() | (instant < pl.col("open")) | (instant >= pl.col("next_open"))
    )
    counted = marked.group_by(keys).agg(
        instrument_ids=pl.col("instrument_id").unique(),
        records=pl.len().cast(pl.Int64),
        duplicates=_count(pl.col("repeated")),
        out_of_session=_count(outside),
        break_prints=_count((instant >= pl.col("close")) & (instant < pl.col("next_open"))),
        clock_decreases=_count(pl.col("decreased")),
        non_positive_prices=_count(pl.col("non_positive") & ~pl.col("trade_date").is_in(allowed)),
    )
    return (
        counted.join(in_halts, on=keys, how="left")
        .with_columns(pl.col("halt_prints").fill_null(0))
        .collect()
    )


def gaps(
    records: pl.DataFrame, datasets: Mapping[Dataset, DatasetCoverage], bounds: pl.DataFrame
) -> pl.DataFrame:
    """A gap, with the columns of `FINDING_COLUMNS`, for each session between a dataset's first
    and last trade date without a record of any of its contracts among `records`."""
    found = [
        bounds.filter(
            pl.col("trade_date").is_between(coverage.first_trade_date, coverage.last_trade_date)
        )
        .select("trade_date")
        .join(
            records.filter(pl.col("schema") == str(dataset.schema_name), pl.col("records") > 0),
            on="trade_date",
            how="anti",
        )
        .with_columns(
            kind=pl.lit(str(QualityFinding.GAP)),
            schema=pl.lit(str(dataset.schema_name)),
            contract=pl.lit(None, dtype=pl.String),
            count=pl.lit(1, dtype=pl.Int64),
        )
        .select(FINDING_COLUMNS.names())
        for dataset, coverage in datasets.items()
    ]
    return pl.concat(found)


def _marked(store: Store, partition: Partition) -> pl.LazyFrame:
    """A partition's records in their stored order, with its schema and contract: the trade
    date of their session, their instant and instrument, and whether each repeats one before
    it, follows a decrease of the clock, or has a price of zero or below."""
    trade_date, instant, lowest_price, identity = _record_columns(partition)
    return store.scan_partition(partition).select(
        schema=pl.lit(str(partition.dataset.schema_name)),
        contract=pl.lit(partition.contract),
        trade_date=trade_date,
        instant=instant,
        instrument_id="instrument_id",
        repeated=~identity.is_first_distinct(),
        decreased=(instant.diff() < 0).fill_null(False),
        non_positive=lowest_price <= 0,
    )


def _record_columns(partition: Partition) -> tuple[pl.Expr, pl.Expr, pl.Expr, pl.Expr]:
    """A record's trade date, instant, lowest price, and identity: a bar's own trade date,
    `ts_open`, lowest of four prices, and instrument and open; a tick's partition key,
    `ts_recv`, price, and every column."""
    if partition.dataset.schema_name.kind is SchemaKind.OHLCV:
        lowest = pl.min_horizontal("open", "high", "low", "close")
        return (
            pl.col("trade_date"),
            pl.col("ts_open"),
            lowest,
            pl.struct("instrument_id", "ts_open"),
        )
    return (
        pl.lit(partition.key, dtype=pl.Date),
        pl.col("ts_recv"),
        pl.col("price"),
        pl.struct(pl.all()),
    )


def _count(condition: pl.Expr) -> pl.Expr:
    return condition.sum().cast(pl.Int64)
