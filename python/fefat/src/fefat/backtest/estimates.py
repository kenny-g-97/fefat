"""What a run of a window would read, told before anything runs (step 5.6), for the app's Run
backtest dialog and a notebook: the settings the run would apply, what it can choose among, the
trade dates its series holds, the window asked for cut to them, and how many sessions, bars, and
ticks the engine would replay, each session on the level it fills on, the finest it holds at or
coarser than the run's fidelity (D-58), of the contract the run reads that day. It reads the
store's listing, the `trade_date` column of the bars a file keeps by month, and the footers of
the files kept by trade date: it builds no strategy and loads no bar.

    ff.backtest.estimated("ES", Timeframe.parse("5m"), None, None, RunConfig(), paths)

Three limits, none of which changes a run: the first estimate of a spliced root in a process
builds its roll calendar from the whole 1-minute dataset, as the chart's first open does; the
estimate reads the store where the engine reads its cache, which can leave a level out of a date;
and a run replays its window a second time at one more tick (`02` §7), which the counts leave
out.
"""

from datetime import date

import polars as pl
from pydantic import Field

from fefat.backtest.record import Window
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.backtest.run_signals import contract_of
from fefat.backtest.snapshots import level_rank
from fefat.config import FefatPaths
from fefat.market.contracts import parse_contract_name
from fefat.market.coverage import session_datasets
from fefat.market.dataset_choice import (
    UnbuildableSeriesError,
    building_datasets,
    default_provider,
    held_providers,
    held_records,
)
from fefat.market.engine_cache import level_of
from fefat.market.fees import FeeChoice, fee_in_force, tables_pricing
from fefat.market.fidelity import TickFidelity
from fefat.market.instruments import Currency, InstrumentKind
from fefat.market.layout import Dataset, Partition, SeriesKind
from fefat.market.schema import FrozenModel, Timeframe
from fefat.market.series_source import SeriesSource, series_source_in
from fefat.market.store import Store


class WindowEstimate(FrozenModel):
    """What a run of a window would read (module docstring): its `settings`, every default
    applied; the `providers` that hold its root, the provider's `contracts` in time order, none
    for a series of one contract, its `levels`, finest first, and the `fee_tables` that price the
    root, each with the fee it would pay on the window's last day, or on the last day asked where
    the window meets no data, the newest schedule's where none was asked (D-117); the `currency`
    its money counts in; `held`, the trade dates its series holds, none while it holds none;
    `window`, the dates asked for cut to them, none where they do not meet; and the `sessions`,
    `bars`, and `ticks` the engine would replay on it."""

    settings: AppliedRunConfig
    providers: tuple[str, ...]
    contracts: tuple[str, ...]
    levels: tuple[str, ...]
    fee_tables: tuple[FeeChoice, ...]
    currency: Currency
    held: Window | None
    window: Window | None
    sessions: int = Field(ge=0)
    bars: int = Field(ge=0)
    ticks: int = Field(ge=0)


def estimated(
    root: str,
    timeframe: Timeframe,
    start: date | None,
    end: date | None,
    config: RunConfig,
    paths: FefatPaths,
) -> WindowEstimate | None:
    """What a run of `root`, or of the instrument `config` names in its place (D-114), in
    `timeframe` bars under `config` would read from `start` to `end`, each left out meaning where
    the data starts or ends; None where the store holds none of that instrument, and zero counts
    for a window that holds no session, or a series the provider's data cannot make, which holds
    no dates and still names what can be chosen instead. Where several providers hold the root
    and `config` names none, the catalog's recommended one, or else the first by name. Refused as
    the run would be for a provider or a contract it cannot read, and for a session whose levels
    are all finer than the fidelity."""
    root = root if config.instrument is None else config.instrument
    store = Store(paths.data_dir)
    providers = held_providers(store, root)
    if not providers:
        return None
    provider = default_provider(root, providers) if config.provider is None else config.provider
    symbol = root if config.contract is None else contract_of(root, config.contract)
    source, dates = _source_and_dates(store, paths, symbol, provider, timeframe)
    ranked = sorted(source.datasets.values(), key=lambda dataset: level_rank(level_of(dataset)))
    settings = config.applied(level_of(ranked[0]), source.instrument, source.provider)
    held = None if dates is None else Window(start=dates[0], end=dates[1])
    window = None if held is None else _within(held, start, end)
    sessions, bars, ticks = (
        (0, 0, 0) if window is None else _read(source, ranked, timeframe, window, settings.fidelity)
    )
    last_day = end if window is None else window.end
    return WindowEstimate(
        settings=settings,
        providers=providers,
        contracts=_contracts(source),
        levels=tuple(str(level_of(dataset)) for dataset in ranked),
        fee_tables=tuple(
            FeeChoice(name=name, fee=fee_in_force(name, root, last_day))
            for name in tables_pricing(root)
        ),
        currency=source.instrument.currency,
        held=held,
        window=window,
        sessions=sessions,
        bars=bars,
        ticks=ticks,
    )


def held_instruments(paths: FefatPaths) -> tuple[str, ...]:
    """The roots whose trades, TBBO, or bars the store holds, by name: what a run can trade
    (D-114)."""
    return tuple(sorted({dataset.root for dataset in session_datasets(Store(paths.data_dir))}))


def _source_and_dates(
    store: Store, paths: FefatPaths, symbol: str, provider: str, timeframe: Timeframe
) -> tuple[SeriesSource, tuple[date, date] | None]:
    """The series a run reads and the trade dates it holds; where the provider's data cannot make
    it, for want of bars to splice its contracts or of any that build `timeframe`, the series
    unspliced and no dates. A provider or a contract the store does not hold is refused by that
    second read too."""
    try:
        source = series_source_in(store, paths.cache_dir, symbol, provider=provider)
        return source, source.decided_dates(timeframe)
    except UnbuildableSeriesError:
        unspliced = series_source_in(
            store, paths.cache_dir, symbol, continuous=False, provider=provider
        )
        return unspliced, None


def _within(held: Window, start: date | None, end: date | None) -> Window | None:
    """The dates from `start` to `end`, each left out being `held`'s, cut to `held`."""
    first = held.start if start is None else max(start, held.start)
    last = held.end if end is None else min(end, held.end)
    return None if last < first else Window(start=first, end=last)


def _contracts(source: SeriesSource) -> tuple[str, ...]:
    """The contracts of a futures series the source's datasets hold, in time order; none for a
    product that does not expire or a continuous series, which have no contract to choose."""
    if source.instrument.kind is not InstrumentKind.FUTURES or (
        source.series is not SeriesKind.CONTRACT
    ):
        return ()
    held = {
        file.partition.contract
        for dataset in source.datasets.values()
        for file in source.store.list_partitions(dataset)
    }
    return tuple(sorted(held, key=_expiry_of))


def _expiry_of(contract: str) -> tuple[int, int]:
    month = parse_contract_name(contract)[1]
    return month.year, month.month


def _read(
    source: SeriesSource,
    ranked: list[Dataset],
    timeframe: Timeframe,
    window: Window,
    fidelity: TickFidelity | Timeframe,
) -> tuple[int, int, int]:
    """The sessions, bars, and ticks a run reads of `window`: the dates from the first to the last
    on which a level builds its signal bars, since a run's window is theirs, each on the level it
    fills on."""
    held = _held_of_the_run(source, ranked, (window.start, window.end))
    building = building_datasets(source.datasets, timeframe)
    builds = [rank for rank, dataset in enumerate(ranked) if dataset in building]
    signal_dates = held.filter(pl.col("rank").is_in(builds)).get_column("trade_date")
    if signal_dates.is_empty():
        return 0, 0, 0
    inside = held.filter(pl.col("trade_date").is_between(signal_dates.min(), signal_dates.max()))
    filled = _filled(inside, ranked, fidelity)
    counts = [
        (level_of(ranked[rank]), _records_of(source.store, ranked[rank], rows))
        for (rank,), rows in filled.partition_by("rank", as_dict=True).items()
    ]
    bars = sum(records for level, records in counts if isinstance(level, Timeframe))
    ticks = sum(records for level, records in counts if isinstance(level, TickFidelity))
    return filled.get_column("trade_date").n_unique(), bars, ticks


def _held_of_the_run(
    source: SeriesSource, ranked: list[Dataset], dates: tuple[date, date]
) -> pl.DataFrame:
    """What each of the `ranked` datasets holds on `dates` of the contract the run reads each
    day, with its `rank` among them, finest first."""
    held = pl.concat(
        held_records(source.store, dataset, dates).with_columns(rank=pl.lit(rank, pl.Int64))
        for rank, dataset in enumerate(ranked)
    )
    fronts = source.counted(dates)
    if fronts is None:
        return held
    read = fronts.select("trade_date", "contract")
    return held.join(read, on=["trade_date", "contract"], how="semi")


def _filled(
    held: pl.DataFrame, ranked: list[Dataset], fidelity: TickFidelity | Timeframe
) -> pl.DataFrame:
    """The rows of `held` the engine replays: each session's finest level at or coarser than
    `fidelity`; a session with none is refused in the engine's words (`RunError`)."""
    cap = level_rank(fidelity)
    coarse = [rank for rank, dataset in enumerate(ranked) if level_rank(level_of(dataset)) >= cap]
    candidates = held.filter(pl.col("rank").is_in(coarse))
    filled = candidates.filter(
        pl.col("rank") == pl.col("rank").min().over("trade_date", "contract")
    )
    refused = held.join(filled, on=["trade_date", "contract"], how="anti")
    if refused.is_empty():
        return filled
    day = refused.get_column("trade_date").min()
    present = refused.filter(pl.col("trade_date") == day).get_column("rank").sort().to_list()
    levels = ", ".join(str(level_of(ranked[rank])) for rank in present)
    raise ValueError(
        f"Expected a level at or coarser than {fidelity} on {day}, which holds {levels}."
    )


def _records_of(store: Store, dataset: Dataset, rows: pl.DataFrame) -> int:
    """The records of `dataset` on `rows`: those a file kept by month counted, and the footers of
    the files kept by trade date."""
    counted = int(rows.get_column("records").fill_null(0).sum())
    unread = rows.filter(pl.col("records").is_null()).select("trade_date", "contract")
    partitions = (
        Partition(dataset=dataset, contract=contract, key=trade_date)
        for trade_date, contract in unread.iter_rows()
    )
    return counted + store.record_count(partitions)
