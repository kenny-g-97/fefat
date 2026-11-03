"""A run's signal frame (steps 2.10 and 3.2): the strategy's signal bars as `load` gives them,
each trade date's from the finest level that holds it, read from as many sessions before the
window as its features' warm-up needs (`FeatureGraph.lead_in`, D-71), with the bars of the other
grids its features read, its signals evaluated over them and cut to the window, and the warnings
the loads raised, which the run's record keeps."""

import warnings
from dataclasses import dataclass
from datetime import date

import polars as pl

from fefat.features.runtime import FeatureGraph, InputBars, load_inputs
from fefat.market.api import load
from fefat.market.calendar import SessionTable
from fefat.market.contracts import parse_contract_name
from fefat.strategy.signal_strategy import SignalStrategy


@dataclass(frozen=True)
class SignalFrame:
    """A run's signal frame on its window, the warnings its loads raised, and `first_read`, the
    first trade date of the bars it read, its window's first or the first its features' warm-up
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
) -> SignalFrame:
    """The signal frame of `strategy` on the trade dates from `dates`' start to its end, from
    `provider`'s data, of the root's fronts or of the one `contract` (module docstring); a window
    without bars is refused, as `load` refuses one."""
    start, end = dates
    graph = strategy.feature_graph()
    first = graph.lead_in(sessions, start)
    bars, inputs, loaded = _bars(strategy, graph, (first, end), provider, contract)
    signals = strategy.signals(bars, inputs, start=start).collect()
    first_read = bars.get_column("trade_date").min()
    if signals.is_empty() or not isinstance(first_read, date):
        named = strategy.instrument if contract is None else contract
        raise ValueError(f"Expected bars of {named} from {start} to {end} in the store, got none.")
    return SignalFrame(signals=signals, warnings=loaded, first_read=first_read)


def _bars(
    strategy: SignalStrategy,
    graph: FeatureGraph,
    dates: tuple[date, date],
    provider: str,
    contract: str | None,
) -> tuple[pl.DataFrame, InputBars, tuple[str, ...]]:
    """The strategy's signal bars from `dates`' start to its end, as `load` gives them, of the
    root's fronts or of the one `contract`, the bars of the other grids its features read
    (`load_inputs`), and the warnings the loads raised."""
    root, timeframe = strategy.instrument, strategy.timeframe
    symbol = root if contract is None else _contract_of(root, contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = load(symbol, timeframe, *dates, provider=provider).collect()
        inputs = load_inputs(graph, dates, provider, contract=None if contract is None else symbol)
    return frame, inputs, tuple(str(warning.message) for warning in caught)


def _contract_of(root: str, contract: str) -> str:
    contract_root, _ = parse_contract_name(contract)
    if contract_root != root:
        raise ValueError(f"Expected a contract of {root}, the strategy's root, got {contract}.")
    return contract
