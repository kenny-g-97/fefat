"""What a dataset of trades, TBBO, or bars holds: its contracts, its first and last trade date,
and the instant by which every record was received, read from its partitions at either end
(step 1.8). The quality report
(`fefat.market.quality`), the load API (`fefat.market.api`), and the status of datasets and
products (`fefat.market.status`) start from it.

    es_trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
    dataset_coverage(Store(Path("fixtures")), es_trades)
"""

from datetime import date

import polars as pl

from fefat.market.layout import Dataset, Partition
from fefat.market.schema import FrozenModel, SchemaKind
from fefat.market.store import Store

SESSION_KINDS = frozenset({SchemaKind.TRADES, SchemaKind.TBBO, SchemaKind.OHLCV})
"""The schemas whose records fall in sessions: trades, TBBO, and bars."""


class DatasetCoverage(FrozenModel):
    """What a dataset of trades, TBBO, or bars holds: its contracts, its first and last trade
    date, `received_from`, the instant of its first record (a bar's `ts_open`, a tick's
    `ts_recv`), before which no record is in hand, and `received_until`, the instant by which
    every record was received (a bar's `ts_close`, a tick's `ts_recv` and a nanosecond)."""

    contracts: tuple[str, ...]
    first_trade_date: date
    last_trade_date: date
    received_from: int
    received_until: int


def session_datasets(store: Store) -> tuple[Dataset, ...]:
    """The store's datasets of trades, TBBO, and bars, sorted by folder."""
    return tuple(
        dataset for dataset in store.list_datasets() if dataset.schema_name.kind in SESSION_KINDS
    )


def dataset_coverage(
    store: Store, dataset: Dataset, contract: str | None = None
) -> DatasetCoverage | None:
    """The coverage of a dataset of trades, TBBO, or bars, or of `contract`'s partitions of it
    where one is named, read from its partitions at either end (all of them where its schema has
    no keys); None while it has no partition."""
    if dataset.schema_name.kind not in SESSION_KINDS:
        raise ValueError(
            f"Expected a dataset of trades, TBBO, or bars, got {dataset.relative_folder()}."
        )
    partitions = [
        file.partition
        for file in store.list_partitions(dataset)
        if contract is None or file.partition.contract == contract
    ]
    if not partitions:
        return None
    keys = sorted({str(partition.key) for partition in partitions if partition.key is not None})
    end_keys = {keys[0], keys[-1]} if keys else set[str]()
    ends = [partition for partition in partitions if not keys or str(partition.key) in end_keys]
    first, last, received_from, received_until = (
        pl.concat([_partition_span(store, partition) for partition in ends])
        .select(
            pl.col("first").min(), pl.col("last").max(), pl.col("start").min(), pl.col("end").max()
        )
        .collect()
        .row(0)
    )
    return DatasetCoverage(
        contracts=tuple(sorted({partition.contract for partition in partitions})),
        first_trade_date=first,
        last_trade_date=last,
        received_from=received_from,
        received_until=received_until,
    )


def _partition_span(store: Store, partition: Partition) -> pl.LazyFrame:
    """A partition's first and last trade date, the instant of its first record, and the
    instant its last record was received."""
    rows = store.scan_partition(partition)
    if partition.dataset.schema_name.kind is SchemaKind.OHLCV:
        dates = pl.col("trade_date")
        return rows.select(
            first=dates.min(),
            last=dates.max(),
            start=pl.col("ts_open").min(),
            end=pl.col("ts_close").max(),
        )
    key = pl.lit(partition.key, dtype=pl.Date)
    received = pl.col("ts_recv")
    return rows.select(first=key, last=key, start=received.min(), end=received.max() + 1)
