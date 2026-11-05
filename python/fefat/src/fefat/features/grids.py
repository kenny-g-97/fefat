"""What a feature graph reads (`fefat.features.runtime`, steps 3.2 and 3.6): the grid of each
input, an instrument's signal bars of one timeframe or its prints by aggressor side in each bucket
of that grid, the frame each gives, and the frames a notebook loads to evaluate a graph or a
strategy's signals (`load_inputs`), which `compute` and a run read through the feature cache
instead."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import TYPE_CHECKING

import polars as pl

from fefat.config import resolve_paths
from fefat.market.api import SeriesSource, load, series_source
from fefat.market.coverage import session_datasets
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.market.store import Store

if TYPE_CHECKING:
    from fefat.features.runtime import FeatureGraph


@dataclass(frozen=True)
class Grid:
    """An instrument's signal bars of one timeframe: the rows a feature is evaluated on, or the
    bars of another instrument it reads."""

    root: str
    timeframe: Timeframe

    def __str__(self) -> str:
        return f"{self.root} {self.timeframe}"

    @property
    def described(self) -> str:
        """What the grid's frame holds, in words."""
        return f"bars of {self}"

    def frame_from(self, source: SeriesSource, dates: tuple[date, date]) -> pl.DataFrame:
        """The grid's frame from `source`, its instrument's, on the trade dates `dates` spans."""
        return source.signal_bars(self.timeframe, dates)


@dataclass(frozen=True)
class PrintsGrid(Grid):
    """An instrument's prints by aggressor side in each bucket of one timeframe's grid
    (`fefat.market.aggressor`), which a feature declaring `TradesInput` reads; never equal to the
    `Grid` of its bars."""

    @property
    def described(self) -> str:
        return f"prints by side of {self}"

    def frame_from(self, source: SeriesSource, dates: tuple[date, date]) -> pl.DataFrame:
        return source.side_volumes(self.timeframe, dates)


InputBars = Mapping[Grid, pl.DataFrame]
"""The frame of each grid a graph reads: its bars as `load` gives them, or its prints by side."""

NO_INPUTS: InputBars = MappingProxyType({})
"""No bars beside a strategy's signal bars."""


def grid_frame(inputs: InputBars, grid: Grid, reader: str) -> pl.DataFrame:
    """The frame of `grid` in `inputs`, which the feature or strategy `reader` reads, refused
    where it is not given."""
    frame = inputs.get(grid)
    if frame is None:
        held = ", ".join(each.described for each in inputs) or "none"
        raise ValueError(
            f"Expected the {grid.described} that {reader} reads, got {held}: "
            "ff.features.compute and ff.backtest.run load them."
        )
    return frame


def input_provider(store: Store, root: str, provider: str) -> str | None:
    """The provider of another instrument's bars that a feature reads, `root`'s, where the
    signal bars come from `provider`: that provider where it holds the root, else None, the
    root's default as `load` chooses it (step 3.7, `BACKLOG.md`), so that a root several
    providers hold is read from the signal instrument's."""
    held = {dataset.provider for dataset in session_datasets(store) if dataset.root == root}
    return provider if provider in held else None


def input_sources(graph: "FeatureGraph", signal: SeriesSource) -> dict[str, SeriesSource]:
    """What `load` reads each other instrument the graph reads from, by root, where its signal
    bars come from `signal` (`input_provider`)."""
    others = sorted({grid.root for grid in graph.grids()} - {graph.root})
    return {
        root: series_source(root, provider=input_provider(signal.store, root, signal.provider))
        for root in others
    }


def load_inputs(
    graph: "FeatureGraph",
    dates: tuple[date, date],
    provider: str | None = None,
    *,
    contract: str | None = None,
) -> dict[Grid, pl.DataFrame]:
    """The frame of each grid the graph reads but its signal grid, for the trade dates `dates`
    span (`FeatureGraph.grid_dates`): its instrument's bars at other timeframes, as `load` gives
    them, and its prints by side, from `provider`, where it is named, of one `contract` where a
    run reads one, and another instrument's bars from the same provider where it holds them
    (`input_provider`), for the graph's `evaluate` or a strategy's `signals` over bars a
    notebook loads."""
    others = [grid for grid in graph.grids() if grid != graph.signal_grid]
    if not others:
        return {}
    paths = resolve_paths(os.environ)
    signal = series_source(graph.root if contract is None else contract, provider=provider)
    loaded = {}
    for grid in others:
        timeframe = str(grid.timeframe)
        if isinstance(grid, PrintsGrid):
            loaded[grid] = grid.frame_from(signal, dates)
            continue
        if grid.root == graph.root:
            loaded[grid] = load(signal.symbol, timeframe, *dates, provider=provider).collect()
            continue
        sessions = instrument_table(paths.data_dir).sessions_of(grid.root, paths.cache_dir)
        read = graph.grid_dates(grid, dates, sessions)
        chosen = input_provider(signal.store, grid.root, signal.provider)
        loaded[grid] = load(grid.root, timeframe, *read, provider=chosen).collect()
    return loaded
