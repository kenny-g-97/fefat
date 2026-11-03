"""The leak detector (step 3.4, `02-engine-and-data.md` §6, ADR-0010, D-12, D-71): a feature is
prefix-invariant when its values before a cut never change once the data past the cut is removed,
and `validate` checks it on the data, beside the lint's reading of its source
(`fefat.features.source_lint`).

    report = ff.features.validate(next_close(), "ES", "5m", "2026-02-11", "2026-02-19")
    report.passed  # False
    report.first_failure()  # the first cut that changed a value, with the row and the values
    print(report.summary())

`validate` loads the bars of every grid the feature reads once, from the warm-up before the
window's first trade date to one session past its last, as `compute` reads them, and evaluates the
feature on them whole. It then cuts every input at each instant `fefat.features.cuts` gives, but
one past the end of every input, which removes nothing, a bar kept while its `ts_close` is at or
before the cut, so that a bar in progress at the cut, of the
signal bars or of a higher timeframe the feature reads, is held back as `load` holds back a bar
closing after the end of its data (D-43), and evaluates the feature on what is left. The values
of the window's rows before each cut must be the whole range's: integers and Booleans exactly,
floats within 1e-9 of the output's largest finite magnitude among the rows compared, nulls alike
(`fefat.features.cache_evaluation.compare_values`); and each output must have a value compared at
each cut, or a warm-up longer than the data would compare nothing and pass. The start check
evaluates the feature again from the warm-up before the window's middle trade date, each input
read from its instrument's first bar after that start, and requires the values from that date on
to be the whole range's, so that a feature that remembers more than its warm-up, such as a running
total, fails it; the roll calendar keeps its anchor, the dataset's first whole session, whatever
the start (D-45). The random cuts come from `seed`, drawn when it is None and recorded, so that a
validation repeats (D-11). The report is kept beside the feature's versions, the latest of each
content hash (`fefat.features.versions.validation_file`), for the database of Phase 4.

What it misses: wrong availability timestamps, since it cuts each record at the instant the data
says it became available; revised data, since it reads one vintage; parameters chosen on the full
sample, which change no value it compares, though the lint warns of a default not written as a
literal; a leak in rows or branches its cuts never reach; and a memory longer than the declared
warm-up but inside the whole sessions every computation reads before a window, which the start
check reads too (`BACKLOG.md`). A feature that passes is prefix-invariant on these data at these
cuts, not proven so."""

import random
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from fefat.features.cache_evaluation import Difference, compare_values, slot_outputs
from fefat.features.cuts import Cut, CutKind, cuts_of
from fefat.features.evaluation import FeatureSpec
from fefat.features.runtime import FeatureGraph, Grid, InputBars
from fefat.features.source_lint import LintFinding, lint
from fefat.features.versions import validation_file
from fefat.market.api import SeriesSource, parse_trade_date, series_source
from fefat.market.calendar import utc_text
from fefat.market.schema import FrozenModel, Timeframe
from fefat.market.store_files import json_writer, write_atomically

MINIMUM_COMPARED = 1
"""The values of each output, non-null on both sides, that each cut and the start check must
compare: below it they fail, so that a warm-up longer than the data passes nothing (D-71)."""
_SLOT = "validated"


class CutResult(FrozenModel):
    """A cut compared: its instant and kinds, the values of each output it compared, and where
    the values before it first differ from the whole range's, None where they agree."""

    instant: int
    kinds: tuple[CutKind, ...]
    compared: dict[str, int]
    difference: Difference | None

    @property
    def passed(self) -> bool:
        return self.difference is None and not _missing(self.compared)

    def __str__(self) -> str:
        at = f"at {utc_text(self.instant)} ({', '.join(self.kinds)})"
        found = self.difference
        if found is not None:
            return (
                f"{at}: {found.output} at {utc_text(found.ts_close)} is {found.value} with the "
                f"data after the cut and {found.against} without it"
            )
        return f"{at}: {_agreement(self.compared)}"


class StartCheck(FrozenModel):
    """The start check (module docstring): the first trade date of the whole range's bars and of
    the later start's, the trade date from which their values were compared, the values of each
    output compared, and where they first differ, None where they agree."""

    whole_from: date
    later_from: date
    compared_from: date
    compared: dict[str, int]
    difference: Difference | None

    @property
    def passed(self) -> bool:
        return self.difference is None and not _missing(self.compared)

    def __str__(self) -> str:
        read = f"from {self.compared_from}, read from {self.whole_from} and from {self.later_from}"
        found = self.difference
        if found is not None:
            return (
                f"{read}: {found.output} at {utc_text(found.ts_close)} is {found.value} against "
                f"{found.against}, so the feature remembers more than its warm-up"
            )
        return f"{read}: {_agreement(self.compared)}"


class ValidationReport(FrozenModel):
    """A validation of a feature with its parameters on an instrument's signal bars of a
    timeframe over a window of trade dates (module docstring): each cut compared, the start
    check, and the lint's findings. It passes when every cut and the start check agree with
    values compared, and the lint finds no way of reading ahead; a warning of the lint, of what
    the hash leaves out, never fails it."""

    feature: str
    hash: str
    parameters: dict[str, Any]
    instrument: str
    timeframe: str
    provider: str
    start: date
    end: date
    seed: int
    cuts: tuple[CutResult, ...]
    start_check: StartCheck
    lint: tuple[LintFinding, ...]
    created_at: datetime

    @property
    def passed(self) -> bool:
        reads_ahead = any(finding.rule.looks_ahead for finding in self.lint)
        return not self.failing_cuts() and self.start_check.passed and not reads_ahead

    def failing_cuts(self) -> tuple[CutResult, ...]:
        """The cuts that changed a value before them or compared none, in order of instant."""
        return tuple(cut for cut in self.cuts if not cut.passed)

    def first_failure(self) -> CutResult | None:
        """The first failing cut, with the first row whose value it changed; None when none
        fails."""
        failing = self.failing_cuts()
        return failing[0] if failing else None

    def summary(self) -> str:
        """The report in words: the verdict, the first failing cut, the start check, and the
        lint's findings, each on a line of its own."""
        named = ", ".join(f"{name}={value!r}" for name, value in self.parameters.items())
        verdict = "PASSED" if self.passed else "FAILED"
        failing = self.failing_cuts()
        cuts = (
            f"cuts: {len(failing)} of {len(self.cuts)} fail, the first {failing[0]}"
            if failing
            else f"cuts: none of {len(self.cuts)} fails"
        )
        found = [f"lint: {finding}" for finding in self.lint] or ["lint: no finding"]
        return "\n".join(
            [
                f"{self.feature}({named}) on {self.instrument} {self.timeframe} from {self.start} "
                f"to {self.end}, seed {self.seed}: {verdict}",
                cuts,
                f"start check {self.start_check}",
                *found,
            ]
        )


def validate(
    spec: FeatureSpec,
    instrument: str,
    timeframe: str,
    start: str | date,
    end: str | date,
    *,
    reads: Sequence[FeatureSpec] = (),
    provider: str | None = None,
    seed: int | None = None,
    stops: int = 24,
    random_cuts: int = 16,
) -> ValidationReport:
    """Validate `spec` on the signal bars of the root `instrument` of `timeframe` on the trade
    dates from `start` to `end` from `provider`, as `load` names it (module docstring): `reads`
    are the features it reads, each with its parameters, as `compute` takes them in slots; the
    stops of trading cut at are at most `stops`, but never fewer than the first and the last, a
    weekend, and a holiday halt where the window holds them, and `random_cuts` closes are drawn
    from `seed`. The report is kept beside the feature's versions."""
    first, last = parse_trade_date(start, "start"), parse_trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    if min(stops, random_cuts) < 0:
        raise ValueError(
            f"Expected numbers of stops and random cuts of at least 0, got stops={stops} and "
            f"random_cuts={random_cuts}."
        )
    graph = _graph_of(spec, reads, instrument, Timeframe.parse(timeframe))
    sources = _sources_of(graph, provider)
    signal = sources[graph.root]
    lead = graph.lead_in(signal.sessions, first)
    inputs = _loaded(graph, sources, (lead, signal.sessions.following(last).trade_date))
    window = _window(graph, inputs, (first, last))
    drawn = random.randrange(2**32) if seed is None else seed
    chooser = random.Random(drawn)
    higher = _higher_timeframes(graph, inputs)
    rolls = _roll_days(signal)
    cuts = cuts_of(window, signal.sessions, rolls, higher, chooser, stops, random_cuts)
    outputs = tuple(spec.definition.outputs)
    report = ValidationReport(
        feature=spec.definition.name,
        hash=spec.definition.hash,
        parameters=spec.parameters.model_dump(mode="json"),
        instrument=instrument,
        timeframe=str(graph.timeframe),
        provider=signal.provider,
        start=first,
        end=last,
        seed=drawn,
        cuts=_compared_cuts(graph, inputs, window, cuts, outputs),
        start_check=_start_check(graph, inputs, sources, window, outputs),
        lint=lint(spec.definition),
        created_at=datetime.now(UTC),
    )
    write_atomically(validation_file(report.feature, report.hash), json_writer(report))
    return report


def _window(graph: FeatureGraph, inputs: InputBars, dates: tuple[date, date]) -> pl.DataFrame:
    """`trade_date`, `ts_close`, and the feature's outputs evaluated on the whole of `inputs`, on
    the window's trade dates, `dates`, which must hold two at least, for the start check."""
    first, last = dates
    window = slot_outputs(graph, inputs).filter(pl.col("trade_date").is_between(first, last))
    days = window.get_column("trade_date").n_unique()
    if days < 2:
        raise ValueError(
            f"Expected bars of {graph.root} on two trade dates from {first} to {last} at least, "
            f"so that the start check can move the window's start, got {days}."
        )
    return window


def _graph_of(
    spec: FeatureSpec, reads: Sequence[FeatureSpec], root: str, timeframe: Timeframe
) -> FeatureGraph:
    """The graph of `spec` alone on the signal grid, the features it reads found among `reads`."""
    slots = {_SLOT: spec, **{f"read_{number}": read for number, read in enumerate(reads)}}
    return FeatureGraph.of(slots, root, timeframe).of_slot(_SLOT)


def _sources_of(graph: FeatureGraph, provider: str | None) -> dict[str, SeriesSource]:
    """What `load` reads each instrument of the graph from: its root from `provider`, another
    instrument from its own default, as `compute` reads them."""
    others = sorted({grid.root for grid in graph.grids()} - {graph.root})
    signal = series_source(graph.root, provider=provider)
    return {graph.root: signal, **{root: series_source(root) for root in others}}


def _loaded(
    graph: FeatureGraph, sources: Mapping[str, SeriesSource], dates: tuple[date, date]
) -> dict[Grid, pl.DataFrame]:
    """The bars of every grid the graph reads for the window `dates`, each read once; a grid
    without bars there is refused, as `load` refuses one."""
    loaded = {}
    for grid in graph.grids():
        source = sources[grid.root]
        read = graph.grid_dates(grid, dates, source.sessions)
        bars = source.signal_bars(grid.timeframe, read)
        if bars.is_empty():
            raise ValueError(
                f"Expected bars of {grid} from {read[0]} to {read[1]} in the store, got none."
            )
        loaded[grid] = bars
    return loaded


def _higher_timeframes(graph: FeatureGraph, inputs: InputBars) -> list[pl.DataFrame]:
    """The `trade_date` and `ts_close` of the bars of each timeframe of the graph's instrument
    coarser than its signal bars."""
    seconds = graph.timeframe.nominal_seconds()
    return [
        frame.select("trade_date", "ts_close")
        for grid, frame in inputs.items()
        if grid.root == graph.root and grid.timeframe.nominal_seconds() > seconds
    ]


def _roll_days(source: SeriesSource) -> list[date]:
    """The trade dates a spliced series rolls at the open of; none for a series not spliced."""
    if source.calendar is None:
        return []
    return source.calendar.rolls().get_column("trade_date").to_list()


def _compared_cuts(
    graph: FeatureGraph,
    inputs: InputBars,
    window: pl.DataFrame,
    cuts: Sequence[Cut],
    outputs: Sequence[str],
) -> tuple[CutResult, ...]:
    """Each cut compared: every input cut at it, the feature evaluated on what is left, once for
    cuts that leave the same bars, and its values on the window's rows before the cut compared
    with the whole range's; a cut after every input's last bar, where the store ends, removes
    nothing and is left out."""
    closes = [frame.get_column("ts_close") for frame in inputs.values()]
    whole = tuple(each.len() for each in closes)
    kept: tuple[int, ...] = ()
    values = window
    compared = []
    for cut in cuts:
        rows = tuple(int(each.search_sorted(cut.instant, side="right")) for each in closes)
        if rows == whole:
            continue
        if rows != kept:
            kept = rows
            heads = zip(inputs.items(), rows, strict=True)
            left = {grid: frame.head(count) for (grid, frame), count in heads}
            values = slot_outputs(graph, left)
        before = window.filter(pl.col("ts_close") <= cut.instant).drop("trade_date")
        comparison = compare_values(before, values.drop("trade_date"), outputs)
        compared.append(
            CutResult(
                instant=cut.instant,
                kinds=cut.kinds,
                compared=comparison.compared,
                difference=comparison.difference,
            )
        )
    return tuple(compared)


def _start_check(
    graph: FeatureGraph,
    inputs: InputBars,
    sources: Mapping[str, SeriesSource],
    window: pl.DataFrame,
    outputs: Sequence[str],
) -> StartCheck:
    """The feature evaluated from the warm-up before the window's middle trade date, each input
    read from its instrument's first bar after that start, and compared with the whole range from
    that date on (module docstring)."""
    days = window.get_column("trade_date").unique().sort().to_list()
    compared_from = days[len(days) // 2]
    later = graph.lead_in(sources[graph.root].sessions, compared_from)
    shortened = {
        grid: frame.filter(
            pl.col("trade_date")
            >= graph.grid_dates(grid, (later, compared_from), sources[grid.root].sessions)[0]
        )
        for grid, frame in inputs.items()
    }
    held = window.filter(pl.col("trade_date") >= compared_from).drop("trade_date")
    comparison = compare_values(held, slot_outputs(graph, shortened).drop("trade_date"), outputs)
    signal = graph.signal_grid
    return StartCheck(
        whole_from=inputs[signal].item(0, "trade_date"),
        later_from=shortened[signal].item(0, "trade_date"),
        compared_from=compared_from,
        compared=comparison.compared,
        difference=comparison.difference,
    )


def _missing(compared: Mapping[str, int]) -> list[str]:
    """The outputs with fewer values compared than `MINIMUM_COMPARED`."""
    return [output for output, count in compared.items() if count < MINIMUM_COMPARED]


def _agreement(compared: Mapping[str, int]) -> str:
    missing = _missing(compared)
    if missing:
        return (
            f"no value of {', '.join(missing)} to compare, as a warm-up longer than the data "
            "before it leaves; validate a window with more data before it"
        )
    return f"{sum(compared.values()):,} values agree"
