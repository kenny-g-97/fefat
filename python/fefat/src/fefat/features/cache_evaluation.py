"""Evaluating the partitions of the feature cache that a computation lacks (`fefat.features.cache`,
step 3.3): each feature from its own warm-up, its slot's graph alone (`FeatureGraph.of_slot`), over
the bars each instrument's source gives (`SeriesSource.signal_bars`); and the check that a feature
read from two starts gives the same values (`check_warmups`, `compare_values`), which refuses a
feature that remembers more than its warm-up, with the comparison the leak detector reads too
(step 3.4)."""

import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import product
from pathlib import Path

import polars as pl

from fefat.features.cache_folders import FeatureFolder
from fefat.features.cache_keys import CachePartition
from fefat.features.runtime import FeatureGraph, Grid, InputBars, slot_columns
from fefat.market.api import SeriesSource
from fefat.market.calendar import SessionTable, utc_text
from fefat.market.schema import FrozenModel

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
            values = slot_outputs(folder.graph, own)
            frames[folder.path] = bars.select("ts_close").join(
                values.drop("trade_date"), on="ts_close", how="left", maintain_order="left"
            )
            read = values if own is inputs else slot_outputs(folder.graph, inputs)
            past_its_first = pl.col("trade_date") >= partition.first
            beyond[folder.path] = read.filter(past_its_first, ~partition.holds())
    return Evaluation(frames, beyond, starts)


def _inputs(
    graphs: Sequence[FeatureGraph], sources: Mapping[str, SeriesSource], dates: tuple[date, date]
) -> dict[Grid, pl.DataFrame]:
    """The frame of every grid the graphs read, each from its instrument's source, for the
    window `dates` (`FeatureGraph.grid_dates`): its bars, or its prints by side."""
    grids = dict.fromkeys(grid for graph in graphs for grid in graph.grids())
    with warnings.catch_warnings(action="ignore"):  # `compute` gives `load`'s once
        return {
            grid: grid.frame_from(
                sources[grid.root], graphs[0].grid_dates(grid, dates, sources[grid.root].sessions)
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


def slot_outputs(graph: FeatureGraph, inputs: InputBars) -> pl.DataFrame:
    """`trade_date`, `ts_close`, and the outputs of the one slot of `graph` on its signal grid,
    named by output."""
    ((slot, node),) = graph.slots.items()
    named = {column: output for output, column in slot_columns(slot, node.spec).items()}
    values = graph.evaluate(inputs).rename(named)
    return pl.concat([inputs[graph.signal_grid].select("trade_date"), values], how="horizontal")


def check_warmups(
    evaluations: Mapping[str, Evaluation],
    partitions: Sequence[CachePartition],
    folders: Sequence[FeatureFolder],
    frames: Mapping[tuple[Path, str], pl.DataFrame],
    sessions: SessionTable,
) -> None:
    """Refuse a feature whose values one evaluation read past its partition differ from those
    the partition holding them gives from its own warm-up (`fefat.features.cache`, module
    docstring): each evaluation is compared with the evaluated partitions holding the trade
    dates it read past its own alone, the next session's and a month's left-out dates."""
    for name, done in evaluations.items():
        days = {day for each in done.beyond.values() for day in each.get_column("trade_date")}
        others = [
            other
            for other in partitions
            if other.name != name
            and other.name in evaluations
            and any(other.holds_day(day) for day in days)
        ]
        for other, folder in product(others, folders):
            _require_agreement(folder, done, other, frames, sessions)


def _require_agreement(
    folder: FeatureFolder,
    done: Evaluation,
    other: CachePartition,
    frames: Mapping[tuple[Path, str], pl.DataFrame],
    sessions: SessionTable,
) -> None:
    """Refuse the folder's feature where its values one evaluation read on the trade dates of
    `other` differ from those `other` holds, read from its own warm-up."""
    beyond = done.beyond.get(folder.path)
    read = None if beyond is None else beyond.filter(other.holds())
    if read is None or read.is_empty():
        return
    held = frames[(folder.path, other.name)]
    difference = compare_values(read.drop("trade_date"), held, folder.outputs()).difference
    if difference is not None:
        starts = (done.starts[folder.path], folder.graph.lead_in(sessions, other.first))
        raise ValueError(_disagreement(folder, starts, difference))


class Difference(FrozenModel):
    """Where two computations of a feature's output on the same rows first differ: the output, the
    row's close, and the value each gives, the first `value` and the second `against`."""

    output: str
    ts_close: int
    value: bool | int | float | None
    against: bool | int | float | None

    def __str__(self) -> str:
        return f"{self.output} at {utc_text(self.ts_close)}: {self.value} against {self.against}"


@dataclass(frozen=True)
class Comparison:
    """Two computations of a feature's outputs on the same rows compared: the earliest row where
    they differ, None where they agree, and the values compared, non-null in both, by output."""

    difference: Difference | None
    compared: dict[str, int]


def compare_values(read: pl.DataFrame, held: pl.DataFrame, outputs: Iterable[str]) -> Comparison:
    """Two computations of a feature's `outputs` on the same rows, each a frame of `ts_close` and
    the outputs, compared: integers and Booleans exactly, floats within `TOLERANCE` of the
    output's largest finite magnitude among the rows, and a null on one side only differing."""
    joined = read.join(held, on="ts_close", suffix="_held").sort("ts_close")
    names = tuple(outputs)
    found = [each for each in (_first_apart(joined, output) for output in names) if each]
    compared = {
        output: joined.select(
            (pl.col(output).is_not_null() & pl.col(f"{output}_held").is_not_null()).sum()
        ).item()
        for output in names
    }
    return Comparison(min(found, key=lambda each: each.ts_close, default=None), compared)


def _first_apart(joined: pl.DataFrame, output: str) -> Difference | None:
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
    if differing.is_empty():
        return None
    row = differing.row(0, named=True)
    return Difference(
        output=output, ts_close=row["ts_close"], value=row[output], against=row[f"{output}_held"]
    )


def _disagreement(folder: FeatureFolder, starts: tuple[date, date], difference: Difference) -> str:
    node = folder.graph.slots[folder.slot]
    ours, theirs = starts
    return (
        f"Expected feature {node.name} to give the same values read from {ours} as from "
        f"{theirs}, where its warm-up starts, got {difference}: it remembers more than its "
        f"warm-up of {folder.graph.warmup_text(node)}, so a partition of the cache would differ "
        "from a computation of the whole range; declare a longer warm-up."
    )
