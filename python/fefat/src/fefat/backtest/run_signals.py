"""A run's signal frame (steps 2.10, 3.2, and 3.3): the strategy's signal bars as `load` gives them,
each trade date's from the finest level that holds it, read from as many sessions before the
window as its features' warm-up needs (`FeatureGraph.lead_in`, D-71), its features' values read
from the feature cache, as `ff.features.compute` keeps them (`fefat.features.cache`), its signals
evaluated over them and cut to the window, and the warnings of the load and of the datasets its
features read, which the run's record keeps. From step 5.3 a run tells its stages as it reaches
them (`RunStage`)."""

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from fefat.features.cache import cached_slots
from fefat.market.api import load
from fefat.market.calendar import SessionTable
from fefat.market.contracts import parse_contract_name
from fefat.strategy.signal_strategy import SignalStrategy


class RunStage(StrEnum):
    """A stage `ff.backtest.run` tells its `progress` callable as it reaches it (step 5.3): its
    bars loaded; its features and signals computed; its engine running, which spans the engine
    cache's build, the engine, the fidelity check's reruns, the rerun at one more tick of
    slippage, and the second look at the store; and its artifacts written. A run found saved
    tells only the stages it went through."""

    DATA_LOADED = "data_loaded"
    FEATURES_COMPUTED = "features_computed"
    ENGINE_RUNNING = "engine_running"
    ARTIFACTS_WRITTEN = "artifacts_written"


type RunProgress = Callable[[RunStage], None]
"""What a run tells each stage it reaches."""


def tell_no_one(stage: RunStage) -> None:
    """The progress of a run that no one follows."""


@dataclass(frozen=True)
class SignalFrame:
    """A run's signal frame on its window, the warnings its load raised, and `first_read`, the
    first trade date of the data it read, its window's first or the first its features' warm-up
    reached, so that the snapshots pin what it read whatever start it was given before its first
    bar."""

    signals: pl.DataFrame
    warnings: tuple[str, ...]
    first_read: date


def signal_frame(
    strategy: SignalStrategy,
    sessions: SessionTable,
    provider: str,
    dates: tuple[date, date],
    contract: str | None,
    progress: RunProgress = tell_no_one,
) -> SignalFrame:
    """The signal frame of `strategy` on the trade dates from `dates`' start to its end, from
    `provider`'s data, of the root's fronts or of the one `contract` (module docstring), telling
    `progress` its data loaded and its features computed; a window without bars is refused, as
    `load` refuses one."""
    start, end = dates
    graph = strategy.feature_graph()
    first = graph.lead_in(sessions, start)
    symbol = strategy.instrument if contract is None else contract_of(strategy.instrument, contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bars = load(symbol, strategy.timeframe, first, end, provider=provider).collect()
    progress(RunStage.DATA_LOADED)
    slots = cached_slots(
        graph, (first, end), provider, contract=None if contract is None else symbol
    )
    signals = strategy.signals_with(bars, slots.values, start=start).collect()
    progress(RunStage.FEATURES_COMPUTED)
    first_read = bars.get_column("trade_date").min()
    if signals.is_empty() or not isinstance(first_read, date):
        raise ValueError(f"Expected bars of {symbol} from {start} to {end} in the store, got none.")
    warned = [str(warning.message) for warning in caught]
    loaded = tuple(dict.fromkeys([*warned, *slots.warnings]))
    read = [first_read] if slots.first_read is None else [first_read, slots.first_read]
    return SignalFrame(signals=signals, warnings=loaded, first_read=min(read))


def contract_of(root: str, contract: str) -> str:
    """`contract`, refused unless it is a contract of `root`, the strategy's."""
    contract_root, _ = parse_contract_name(contract)
    if contract_root != root:
        raise ValueError(f"Expected a contract of {root}, the strategy's root, got {contract}.")
    return contract
