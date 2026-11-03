"""Evaluating the partitions of the feature cache that a computation lacks (`fefat.features.cache`,
step 3.3): each feature from its own warm-up, its slot's graph alone (`FeatureGraph.of_slot`), over
the bars each instrument's source gives (`SeriesSource.signal_bars`); and the check that a feature
read from two starts gives the same values (`first_difference`), which refuses a feature that
remembers more than its warm-up."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from fefat.features.cache_folders import FeatureFolder
from fefat.features.cache_keys import CachePartition
from fefat.features.runtime import FeatureGraph, Grid, InputBars, slot_columns
from fefat.market.api import SeriesSource
from fefat.market.calendar import counted, utc_text

TOLERANCE = 1e-9
"""How far apart two float values of a feature read from two starts may lie, relative to the
largest magnitude of the output among them (step 3.4's tolerance)."""


@dataclass(frozen=True)
class Evaluation:
    """A partition evaluated: the frame of each folder that lacked one, and each feature's values
    on the trade dates past the partition's first that other partitions hold, with the trade date
    each feature was read from."""

    frames: dict[Path, pl.DataFrame]
    beyond: dict[Path, pl.DataFrame]
    starts: dict[Path, date]


def evaluated_features(
    folders: Sequence[FeatureFolder],
    sources: Mapping[str, SeriesSource],
    partition: CachePartition,
    bars: pl.DataFrame,
    end: date,
) -> Evaluation:
    """Each folder's feature evaluated from its own warm-up: its values on the partition's
    `bars`, from what the partition's own dates give, and on the trade dates past its first
    that it does not hold, read to `end`, past its last day where the warm-up check compares
    them with the next partition's, so that what a partition holds never depends on whether
    the check ran, even for a feature that reads ahead."""
    starts = {
        folder.path: folder.graph.lead_in(sources[folder.graph.root].sessions, partition.first)
        for folder in folders
    }
    frames: dict[Path, pl.DataFrame] = {}
    beyond: dict[Path, pl.DataFrame] = {}
    for start in sorted(set(starts.values())):
        group = [folder for folder in folders if starts[folder.path] == start]
        graphs = [folder.graph for folder in group]
        inputs = _inputs(graphs, sources, (start, end))
        own = inputs
        if end > partition.last:
            own = _cut(graphs[0], inputs, sources, (start, partition.last))
        for folder in group:
            values = _outputs(folder.graph, own)
            frames[folder.path] = bars.select("ts_close").join(
                values.drop("trade_date"), on="ts_close", how="left", maintain_order="left"
            )
            read = values if own is inputs else _outputs(folder.graph, inputs)
            past_its_first = pl.col("trade_date") >= partition.first
            beyond[folder.path] = read.filter(past_its_first, ~partition.holds())
    return Evaluation(frames, beyond, starts)


def _inputs(
    graphs: Sequence[FeatureGraph], sources: Mapping[str, SeriesSource], dates: tuple[date, date]
) -> dict[Grid, pl.DataFrame]:
    """The bars of every grid the graphs read, each from its instrument's source, for the
    window `dates` (`FeatureGraph.grid_dates`)."""
    grids = dict.fromkeys(grid for graph in graphs for grid in graph.grids())
    return {
        grid: sources[grid.root].signal_bars(
            grid.timeframe, graphs[0].grid_dates(grid, dates, sources[grid.root].sessions)
        )
        for grid in grids
    }


def _cut(
    graph: FeatureGraph,
    inputs: Mapping[Grid, pl.DataFrame],
    sources: Mapping[str, SeriesSource],
    dates: tuple[date, date],
) -> dict[Grid, pl.DataFrame]:
    """`inputs` cut to what a read for the window `dates` gives: each grid's bars of the trade
    dates up to the last it is read for, which a longer read gives alike (step 3.2)."""
    return {
        grid: frame.filter(
            pl.col("trade_date") <= graph.grid_dates(grid, dates, sources[grid.root].sessions)[1]
        )
        for grid, frame in inputs.items()
    }


def _outputs(graph: FeatureGraph, inputs: InputBars) -> pl.DataFrame:
    """`trade_date`, `ts_close`, and the outputs of the one slot of `graph` on its signal grid."""
    ((slot, node),) = graph.slots.items()
    named = {column: output for output, column in slot_columns(slot, node.spec).items()}
    values = graph.evaluate(inputs).rename(named)
    return pl.concat([inputs[graph.signal_grid].select("trade_date"), values], how="horizontal")


def first_difference(read: pl.DataFrame, held: pl.DataFrame, outputs: Iterable[str]) -> str | None:
    """Where two computations of a feature's `outputs` on the same rows, each a frame of
    `ts_close` and the outputs, first differ, in words; None where they agree: integers and
    Booleans exactly, floats within `TOLERANCE` of the output's largest finite magnitude among
    the rows, and a null on one side only differing."""
    joined = read.join(held, on="ts_close", suffix="_held").sort("ts_close")
    for output in outputs:
        ours, theirs = pl.col(output), pl.col(f"{output}_held")
        apart = ours != theirs
        if joined.schema[output].is_float():
            scale = joined.select(
                pl.max_horizontal(
                    ours.filter(ours.is_finite()).abs().max(),
                    theirs.filter(theirs.is_finite()).abs().max(),
                )
            ).item()
            if scale is not None:
                apart = apart & ((ours - theirs).abs() > TOLERANCE * scale)
        differing = joined.filter((apart | (ours.is_null() != theirs.is_null())).fill_null(False))
        if not differing.is_empty():
            row = differing.row(0, named=True)
            at = utc_text(row["ts_close"])
            return f"{output} at {at}: {row[output]} against {row[f'{output}_held']}"
    return None


def disagreement(folder: FeatureFolder, starts: tuple[date, date], difference: str) -> str:
    node = folder.graph.slots[folder.slot]
    warmup = counted(folder.graph.warmups[node], "bar")
    ours, theirs = starts
    return (
        f"Expected feature {node.name} to give the same values read from {ours} as from "
        f"{theirs}, where its warm-up starts, got {difference}: it remembers more than its "
        f"warm-up of {warmup} of {node.timeframe}, so a partition of the cache would differ from "
        "a computation of the whole range; declare a longer warm-up."
    )
