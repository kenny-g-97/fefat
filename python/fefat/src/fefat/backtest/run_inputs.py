"""What a backtest reads (step 2.10): its signal bars, as `load` gives them, each trade date's
from the finest level that holds it, whose eras the run records, read from as many sessions before
its window as its features' warm-up needs, with the bars of the other grids they read (step 3.2),
with the warnings the loads raise, and its signal frame on its window, checked as both engines read
it; a snapshot of each dataset of
its provider over its window (ADR-0019), whose hashes key the run; the engine cache of the months
it replays, built from the same files (D-56); the fronts it trades and the rolls between them, as
the roll calendar gives them (D-44, F-ROL-01); the hours its market trades in (F-SES-02); a
perpetual's funding rates from the store (F-FND-01); its fee table (F-FEE-01); and the config the
engine reads, every setting applied (D-51), with the config of its rerun at one more tick of
slippage and its exchange's time zone, which its metrics read (step 2.11)."""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl

from fefat.backtest.record import DatasetRecord, FeeTableRecord, RollRecord, Window
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.backtest.run_signals import signal_frame
from fefat.config import FefatPaths
from fefat.market.api import parse_trade_date, roll_calendar
from fefat.market.calendar import SessionTable, counted
from fefat.market.dataset_choice import provider_datasets, signal_bar_eras
from fefat.market.engine_cache import build_cache_months, level_of
from fefat.market.engine_cache_index import ENGINE_CACHE_FOLDER_NAME
from fefat.market.engine_units import (
    InstrumentParameters,
    instrument_parameters,
    micro_units,
    price_text,
)
from fefat.market.fees import TABLES, CryptoFee, FuturesFee
from fefat.market.fidelity import FidelityEra, TickFidelity
from fefat.market.instruments import Instrument, InstrumentKind
from fefat.market.layout import Dataset, PartitionRequest, YearMonth
from fefat.market.roll_decisions import RollReason
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import SchemaKind, Timeframe, parse_schema_name
from fefat.market.snapshot import Snapshot
from fefat.market.store import Store
from fefat.reference.costs import RunFees
from fefat.reference.hours import CalendarHours
from fefat.reference.rolls import RollRow
from fefat.reference.run_documents import (
    exit_features,
    run_document,
    settings_document,
    with_engine_columns,
)
from fefat.reference.tape import FundingRate, funding_rates_of
from fefat.strategy.signal_frame import require_named_columns
from fefat.strategy.signal_strategy import SignalStrategy
from fefat.strategy.spec import StrategySpec


@dataclass(frozen=True)
class RunInputs:
    """What the engine reads of a run, and what its record says it read; its fronts' engine
    caches are built only when it runs (`cache_paths`), since a saved run reads none of them."""

    spec: StrategySpec
    signals: pl.DataFrame
    store: Store
    fronts: tuple[str, ...]
    engine_config: dict[str, object]
    partition_hashes: tuple[str, ...]
    datasets: tuple[DatasetRecord, ...]
    config: AppliedRunConfig
    instrument: Instrument
    parameters: InstrumentParameters
    fee_table: FeeTableRecord
    rolls: tuple[RollRecord, ...]
    window: Window
    warnings: tuple[str, ...]
    time_zone: str
    signal_bar_eras: tuple[FidelityEra, ...]

    def spec_json(self) -> str:
        return json.dumps(self.spec.document())

    def config_json(self) -> str:
        return json.dumps(self.engine_config)

    def config_json_at_one_more_tick(self) -> str:
        """The config of the rerun at one more tick of slippage on market and stop orders, whose
        profit and loss the metrics report (`02` §7, F-SLP-01)."""
        settings = self.config.at_one_more_tick().run_settings()
        return json.dumps({**self.engine_config, "settings": settings_document(settings)})

    def cache_paths(self, paths: FefatPaths) -> tuple[Path, ...]:
        """The engine cache's folder of each front, its months of the window built from the store
        (`engine_cache_folder`)."""
        root, provider = self.instrument.root, self.config.provider
        folder = engine_cache_folder(self.store, paths, (root, provider), self.window, self.fronts)
        folders = tuple(folder / contract for contract in self.fronts)
        missing = [str(path) for path in folders if not path.is_dir()]
        if missing:
            raise ValueError(
                f"Expected the engine cache of each front, got none in {', '.join(missing)}."
            )
        return folders


def engine_cache_folder(
    store: Store,
    paths: FefatPaths,
    root_and_provider: tuple[str, str],
    window: Window,
    fronts: Sequence[str],
) -> Path:
    """The folder of the engine caches of a root's contracts from a provider, the months of the
    window of its `fronts`, the contracts a run trades, built from the store
    (`build_cache_months`); a month of a front the cache refuses refuses the run."""
    root, provider = root_and_provider
    months = _months(window)
    built = build_cache_months(store, paths.cache_dir, root, months, provider, fronts)
    if built.refused:
        raise ValueError(
            f"Expected the engine cache of {root} from {window.start} to {window.end}, got: "
            f"{'; '.join(built.refused)}"
        )
    return paths.cache_dir / ENGINE_CACHE_FOLDER_NAME / provider / root


@dataclass(frozen=True)
class _Market:
    """The store, the instrument, its session table, and the provider's datasets of it."""

    store: Store
    instrument: Instrument
    sessions: SessionTable
    datasets: tuple[Dataset, ...]

    @property
    def provider(self) -> str:
        return self.datasets[0].provider


def run_inputs(
    strategy: SignalStrategy,
    start: str | date,
    end: str | date,
    config: RunConfig,
    paths: FefatPaths,
) -> RunInputs:
    """Everything a run of `strategy` on the trade dates from `start` to `end` reads."""
    market = _market(strategy.instrument, config.provider, paths)
    applied = config.applied(_finest(market.datasets), market.instrument.kind, market.provider)
    dates = (parse_trade_date(start, "start"), parse_trade_date(end, "end"))
    read = signal_frame(strategy, market.sessions, market.provider, dates, applied.contract)
    signals = read.signals
    spec = strategy.to_spec()
    require_named_columns(spec.execution, signals.columns)
    window = _window(signals)
    snapshots = _snapshots(market, read.warmup_from, window)
    fronts, rolls = _fronts_and_rolls(signals, market, window)
    parameters = instrument_parameters(market.instrument)
    engine_config = _engine_config(market, applied, signals, snapshots, window, rolls)
    return RunInputs(
        spec=spec,
        signals=with_engine_columns(spec, signals, market.sessions),
        store=market.store,
        fronts=fronts,
        engine_config=engine_config,
        partition_hashes=tuple(sorted(snapshot.sha256 for snapshot in snapshots)),
        datasets=tuple(_dataset_record(market.store, snapshot) for snapshot in snapshots),
        config=applied,
        instrument=market.instrument,
        parameters=parameters,
        fee_table=_fee_table_record(applied.fee_table, market.instrument.root),
        rolls=tuple(_roll_record(roll) for roll in rolls),
        window=window,
        warnings=(*read.warnings, *_features_below_a_tick(spec, signals, parameters.tick)),
        time_zone=market.sessions.time_zone(),
        signal_bar_eras=_signal_bar_eras(market, strategy, window, applied.contract),
    )


def _engine_config(
    market: _Market,
    applied: AppliedRunConfig,
    signals: pl.DataFrame,
    snapshots: tuple[Snapshot, ...],
    window: Window,
    rolls: tuple[RollRow, ...],
) -> dict[str, object]:
    """The config the engine reads: the applied settings, the instrument in the engines'
    integers, the sessions around the signal bars, the capital, the fee table, a perpetual's
    funding, and the rolls (`fefat.reference.run_documents.run_document`)."""
    first, last = signals.select(
        pl.col("ts_close").min().alias("first"), pl.col("ts_close").max().alias("last")
    ).row(0)
    root = market.instrument.root
    return run_document(
        fidelity=applied.fidelity,
        instrument=instrument_parameters(market.instrument),
        settings=applied.run_settings(),
        hours=CalendarHours.around(market.sessions, first, last),
        capital=micro_units(applied.capital),
        position=None,
        fees=RunFees.of_table(TABLES[applied.fee_table], root),
        funding=_funding(market, snapshots, window),
        rolls=rolls,
    )


def _market(root: str, provider: str | None, paths: FefatPaths) -> _Market:
    store = Store(paths.data_dir)
    table = instrument_table(paths.data_dir)
    datasets = provider_datasets(store, root, provider, origin=None)
    return _Market(
        store=store,
        instrument=table.get(root),
        sessions=table.sessions_of(root, paths.cache_dir),
        datasets=tuple(datasets.values()),
    )


def _finest(datasets: Iterable[Dataset]) -> TickFidelity | Timeframe:
    """The finest level the datasets hold: TBBO, then trades, then the shortest bars."""

    def rank(level: TickFidelity | Timeframe) -> tuple[int, int]:
        if isinstance(level, Timeframe):
            return (2, level.nominal_nanoseconds())
        return (0 if level is TickFidelity.TBBO else 1, 0)

    return min((level_of(dataset) for dataset in datasets), key=rank)


def _signal_bar_eras(
    market: _Market, strategy: SignalStrategy, window: Window, contract: str | None
) -> tuple[FidelityEra, ...]:
    """The levels the window's signal bars were built from, each trade date's as `load` chose it
    (`signal_bar_eras`), in eras."""
    held = {str(dataset.schema_name): dataset for dataset in market.datasets}
    timeframe = Timeframe.parse(strategy.timeframe)
    return signal_bar_eras(market.store, held, timeframe, (window.start, window.end), contract)


def _window(signals: pl.DataFrame) -> Window:
    first, last = signals.select(
        pl.col("trade_date").min().alias("first"), pl.col("trade_date").max().alias("last")
    ).row(0)
    return Window(start=first, end=last)


def _snapshots(market: _Market, first: date, window: Window) -> tuple[Snapshot, ...]:
    """A snapshot of each dataset of the provider to the window's end from the session before
    `first`, the window's start or where its features' warm-up reaches back to, which `load`
    reads from, and of a perpetual's funding; a dataset without a partition in that range is not
    read."""
    lead_in = market.sessions.preceding(first).trade_date
    datasets = list(market.datasets)
    if market.instrument.kind is InstrumentKind.PERPETUAL:
        datasets.append(_funding_dataset(market))
    snapshots = []
    for dataset in datasets:
        request = PartitionRequest(dataset=dataset, start=lead_in, end=window.end)
        listed = market.store.list_partitions(dataset)
        if any(request.selects(file.partition) for file in listed):
            snapshots.append(market.store.snapshot(request))
    return tuple(snapshots)


def _funding_dataset(market: _Market) -> Dataset:
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


def _funding(
    market: _Market, snapshots: tuple[Snapshot, ...], window: Window
) -> tuple[FundingRate, ...]:
    """A perpetual's funding rates received from its first session's open until the open of the
    session after its last, where `load`'s range ends (`02` §1.1); a window the store's funding
    rates leave out is refused, as a perpetual without them is (`_funding_dataset`)."""
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


def _fronts_and_rolls(
    signals: pl.DataFrame, market: _Market, window: Window
) -> tuple[tuple[str, ...], tuple[RollRow, ...]]:
    """The contracts the run trades, in order, and the rolls between them that the roll calendar
    gives, those whose session opens after the window's first trade date and by its last."""
    contracts = tuple(signals.get_column("contract").unique(maintain_order=True).to_list())
    if len(contracts) == 1:
        return contracts, ()
    calendar = roll_calendar(market.instrument.root, provider=market.provider)
    crossed = calendar.rolls().filter(
        pl.col("trade_date") > window.start, pl.col("trade_date") <= window.end
    )
    rolls = tuple(
        RollRow.model_construct(**{**row, "reason": RollReason(row["reason"])})
        for row in crossed.iter_rows(named=True)
    )
    fronts = (contracts[0], *(roll.contract for roll in rolls))
    if fronts != contracts:
        raise ValueError(
            f"Expected the signal bars of {market.instrument.root} on the fronts its roll calendar "
            f"gives, {', '.join(fronts)}, got {', '.join(contracts)}."
        )
    return fronts, rolls


def _months(window: Window) -> list[YearMonth]:
    months = []
    year, month = window.start.year, window.start.month
    while (year, month) <= (window.end.year, window.end.month):
        months.append(YearMonth(year=year, month=month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _dataset_record(store: Store, snapshot: Snapshot) -> DatasetRecord:
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


def _fee_table_record(name: str, root: str) -> FeeTableRecord:
    table = TABLES[name]
    return FeeTableRecord(
        name=name,
        schedules=tuple(
            (schedule.effective_from, _fee_text(schedule.fees[root]))
            for schedule in table.schedules
        ),
    )


def _fee_text(fee: FuturesFee | CryptoFee) -> str:
    if isinstance(fee, FuturesFee):
        return f"{fee.per_contract_side} per contract per side"
    return f"maker {fee.maker_bps} bps, taker {fee.taker_bps} bps"


def _roll_record(roll: RollRow) -> RollRecord:
    return RollRecord(
        trade_date=roll.trade_date,
        rolled_from=roll.rolled_from,
        contract=roll.contract,
        gap=Decimal(price_text(roll.gap)),
        reason=roll.reason,
    )


def _features_below_a_tick(spec: StrategySpec, signals: pl.DataFrame, tick: int) -> tuple[str, ...]:
    """A warning for each feature an exit rule reads that lies above zero but below one tick on
    an entry row: an exit rule reads a feature as a distance in 1e-9 units of price (F-RND-01),
    so an ATR written in points gives a stop of one tick without an error (BACKLOG.md)."""
    entries = signals.filter(pl.col("long_entry") | pl.col("short_entry"))
    found = []
    for column, feature in sorted(exit_features(spec).items()):
        if feature not in entries.columns:
            continue
        below = entries.filter((pl.col(feature) > 0) & (pl.col(feature) < tick)).height
        if below:
            found.append(
                f"the feature {feature}, which {column} reads, lies below one tick "
                f"({price_text(tick)}) on {counted(below, 'entry row')}: an exit rule reads a "
                "feature as a distance in 1e-9 units of price (F-RND-01)"
            )
    return tuple(found)
