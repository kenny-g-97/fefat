"""What a run's record pins of the data it read (steps 2.10 and 3.7, ADR-0019): the store, the
instrument, its session table, and its provider's datasets (`Market`); a snapshot of each of
those datasets over the trade dates the run read, and of a perpetual's funding, whose hashes key
the run (D-62) and which its record names with their terms (D-47); and, from step 3.7, a snapshot
of the datasets of each other instrument its features read, which key and name the run alike, so
that `explain` and the fidelity check find the data of every instrument as the run read it
(`BACKLOG.md`)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import polars as pl

from fefat.backtest.record import DatasetRecord, Window
from fefat.config import FefatPaths
from fefat.features.cache_keys import PartitionKeys
from fefat.features.grids import input_sources
from fefat.features.runtime import FeatureGraph
from fefat.market.api import series_source
from fefat.market.calendar import SessionTable
from fefat.market.dataset_choice import provider_datasets
from fefat.market.engine_cache import level_of
from fefat.market.fidelity import TickFidelity
from fefat.market.instruments import Instrument, InstrumentKind
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import SchemaKind, Timeframe, parse_schema_name
from fefat.market.snapshot import Snapshot
from fefat.market.store import Store
from fefat.reference.tape import FundingRate, funding_rates_of


@dataclass(frozen=True)
class Market:
    """The store, the instrument, its session table, and the provider's datasets of it."""

    store: Store
    instrument: Instrument
    sessions: SessionTable
    datasets: tuple[Dataset, ...]

    @property
    def provider(self) -> str:
        return self.datasets[0].provider


def market_of(root: str, provider: str | None, paths: FefatPaths) -> Market:
    """The store, the instrument `root`, its session table, and the datasets of it of
    `provider`, the root's default where it is None."""
    store = Store(paths.data_dir)
    table = instrument_table(paths.data_dir)
    datasets = provider_datasets(store, root, provider, origin=None)
    return Market(
        store=store,
        instrument=table.get(root),
        sessions=table.sessions_of(root, paths.cache_dir),
        datasets=tuple(datasets.values()),
    )


def finest_level(datasets: Iterable[Dataset]) -> TickFidelity | Timeframe:
    """The finest level the datasets hold: TBBO, then trades, then the shortest bars."""

    def rank(level: TickFidelity | Timeframe) -> tuple[int, int]:
        if isinstance(level, Timeframe):
            return (2, level.nominal_nanoseconds())
        return (0 if level is TickFidelity.TBBO else 1, 0)

    return min((level_of(dataset) for dataset in datasets), key=rank)


def snapshots_of(market: Market, first: date, window: Window) -> tuple[Snapshot, ...]:
    """A snapshot of each dataset of the provider to the window's end from the session before
    `first`, the first trade date of the bars the run read, which `load` reads from, and of a
    perpetual's funding; a dataset without a partition in that range is not read."""
    lead_in = market.sessions.preceding(first).trade_date
    datasets = list(market.datasets)
    if market.instrument.kind is InstrumentKind.PERPETUAL:
        datasets.append(funding_dataset(market))
    return _snapshots_within(market.store, datasets, (lead_in, window.end))


def input_snapshots(
    market: Market, graph: FeatureGraph, dates: tuple[date, date], contract: str | None
) -> tuple[Snapshot, ...]:
    """A snapshot of the datasets of each other instrument the graph's features read
    (`InstrumentInput`, step 3.7), over the trade dates the feature cache reads them for to
    evaluate the graph on the trade dates `dates` spans from its warm-up (`PartitionKeys.reads`),
    from the provider it reads them from (`input_sources`), for the one `contract` a run trades
    where it names one, as the cache reads the run's own bars."""
    if all(grid.root == graph.root for grid in graph.grids()):
        return ()
    signal = series_source(graph.root if contract is None else contract, provider=market.provider)
    others = input_sources(graph, signal)
    read = PartitionKeys({graph.root: signal, **others}).reads(graph, dates)
    return tuple(
        snapshot
        for root, source in others.items()
        for snapshot in _snapshots_within(market.store, source.datasets.values(), read[root])
    )


def _snapshots_within(
    store: Store, datasets: Iterable[Dataset], dates: tuple[date, date]
) -> tuple[Snapshot, ...]:
    """A snapshot of each of `datasets` over the trade dates `dates` spans; a dataset without a
    partition there is not read."""
    snapshots = []
    for dataset in datasets:
        request = PartitionRequest(dataset=dataset, start=dates[0], end=dates[1])
        if any(request.selects(file.partition) for file in store.list_partitions(dataset)):
            snapshots.append(store.snapshot(request))
    return tuple(snapshots)


def funding_dataset(market: Market) -> Dataset:
    dataset = Dataset(
        provider=market.provider,
        schema_name=parse_schema_name("funding"),
        root=market.instrument.root,
    )
    if not market.store.has_dataset_metadata(dataset):
        raise ValueError(
            f"Expected the funding rates of the perpetual {market.instrument.root} in the store "
            f"({dataset.relative_folder().as_posix()}), got none: a run without them would "
            "leave out what the position pays and receives (F-FND-01)."
        )
    return dataset


def funding_rates(
    market: Market, snapshots: tuple[Snapshot, ...], window: Window
) -> tuple[FundingRate, ...]:
    """A perpetual's funding rates received from its first session's open until the open of the
    session after its last, where `load`'s range ends (`02` §1.1); a window the store's funding
    rates leave out is refused, as a perpetual without them is (`funding_dataset`)."""
    if market.instrument.kind is not InstrumentKind.PERPETUAL:
        return ()
    received = [
        market.store.read(snapshot)
        for snapshot in snapshots
        if snapshot.request.dataset.schema_name.kind is SchemaKind.FUNDING
    ]
    opens = market.sessions.session(window.start).open
    until = market.sessions.following(window.end).open
    within = [
        rows.filter(pl.col("ts_recv") >= opens, pl.col("ts_recv") < until) for rows in received
    ]
    if not any(rows.height for rows in within):
        raise ValueError(
            f"Expected the funding rates of the perpetual {market.instrument.root} received from "
            f"{window.start} to {window.end} in the store, got none: a run without them would "
            "leave out what the position pays and receives (F-FND-01)."
        )
    return funding_rates_of(pl.concat(within))


def dataset_record(store: Store, snapshot: Snapshot) -> DatasetRecord:
    """A dataset as a run's record names it, with the terms its pinned `dataset.json` gives."""
    request, metadata = snapshot.request, store.pinned_metadata(snapshot)
    return DatasetRecord(
        provider=request.dataset.provider,
        schema_name=str(request.dataset.schema_name),
        root=request.dataset.root,
        origin=metadata.origin,
        licence_scope=metadata.licence_scope,
        first=request.start,
        last=request.end,
        snapshot=snapshot.sha256,
    )
