"""The leak detector (step 3.4, `02-engine-and-data.md` §6, ADR-0010, D-12, D-71): a feature is
prefix-invariant when its values before a cut never change once the data past the cut is removed,
and `validate` checks it on the data, beside the lint's reading of its source
(`fefat.features.source_lint`); its report is `fefat.features.validation_report`.

    report = ff.features.validate(next_close(), "ES", "5m", "2026-02-11", "2026-02-19")
    report.passed  # False
    report.first_failure()  # the first cut that changed a value, with the row and the values
    print(report.summary())

`validate` loads the bars of every grid the feature reads once, from the warm-up before the
window's first trade date to one session past its last, as `compute` reads them, and evaluates the
feature on them whole. It then cuts every input at each instant `fefat.features.cuts` gives, but
one past the end of every input, which removes nothing, a bar kept while its `ts_close` is at or
before the cut, so that a bar in progress at the cut, of the signal bars or of a higher timeframe
the feature reads, is held back as `load` holds back a bar closing after the end of its data
(D-43), and evaluates the feature on what is left. The trades input is cut alike, a bucket's prints
by side kept while its `ts_close` is at or before the cut (step 3.6): cutting the prints at their
`ts_recv` and building the buckets again holds a bucket in progress back, as the bar's, so both
keep the same buckets, and the five instants around a stop differ only by prints received in the
break, which lie in no bucket of the grid (`fefat.market.aggressor`). The values of the window's rows before each cut
must be the whole range's: integers and Booleans exactly, floats within 1e-9 of the output's
largest finite magnitude among the rows compared, nulls alike
(`fefat.features.cache_evaluation.compare_values`). The start check evaluates the feature again
from the warm-up before the window's middle trade date, and before the trade date after it, each
input read from its instrument's first bar after that start, and requires the values from that
date on to be the whole range's, so that a feature that remembers more than its warm-up, such as
a running total, fails it, even one whose memory the middle date's week resets; the roll
calendar keeps its anchor, the dataset's first whole session, whatever the start (D-45). A start
the data does not let move, as at the store's first session, checks nothing and fails, as an
output whose values no cut compares does, so that a warm-up longer than the data passes nothing.
The lint reads the feature and the features it reads; its findings warn, but one: data a feature
reads itself, or holds from outside it, which the cuts never cut, fails. The random cuts come from `seed`, drawn when it is None, and the report records it with
the numbers of stops and random cuts and the features read, so that a validation repeats (D-11).
The report is kept beside the feature's versions, the latest of each content hash
(`fefat.features.versions.validation_file`), for the database of Phase 4.

What it misses: wrong availability timestamps, since it cuts each record at the instant the data
says it became available, and bars a later record of their trade date would build from another
level (`BACKLOG.md`); revised data, since it reads one vintage; parameters chosen on the full
sample, which change no value it compares, though the lint warns of a default not written as a
literal; a leak in rows or branches its cuts never reach, or in a helper the feature calls, whose
code the lint does not read; a statistic over the whole frame or a session that the window's data
settle before every cut, such as a maximum reached early, of which the lint warns; and a memory longer than the declared warm-up but inside the whole
sessions every computation reads before a window, which the start check reads too (`BACKLOG.md`).
A feature that passes is prefix-invariant on these data at these cuts, not proven so."""

import random
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

import polars as pl

from fefat.features.cache_evaluation import compare_values, slot_outputs
from fefat.features.cuts import Cut, cuts_of
from fefat.features.evaluation import FeatureSpec
from fefat.features.grids import InputBars, PrintsGrid, grid_frames, input_sources
from fefat.features.runtime import FeatureGraph
from fefat.features.source_lint import LintFinding, lint
from fefat.features.validation_report import CutResult, FeatureRead, StartCheck, ValidationReport
from fefat.features.versions import validation_file
from fefat.market.api import SeriesSource, parse_trade_date, series_source
from fefat.market.schema import Timeframe
from fefat.market.store_files import json_writer, write_atomically

_SLOT = "validated"


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
    from `seed`. The report is kept beside the feature's versions and names each feature the
    graph read with its parameters, those `reads` gave and those the feature binds or reads with
    their defaults (step 3.7)."""
    first, last = _window_dates(start, end, stops, random_cuts)
    graph = _graph_of(spec, reads, instrument, Timeframe.parse(timeframe))
    sources = _sources_of(graph, provider)
    signal = sources[graph.root]
    lead = graph.lead_in(signal.sessions, first)
    following = signal.sessions.following(last).trade_date
    inputs = grid_frames(graph, sources, (lead, following), graph.grids())
    window = _window(graph, inputs, (first, last))
    drawn = random.randrange(2**32) if seed is None else seed
    higher = _higher_timeframes(graph, inputs)
    chooser = random.Random(drawn)
    cuts = cuts_of(window, signal.sessions, _roll_days(signal), higher, chooser, stops, random_cuts)
    outputs = tuple(spec.definition.outputs)
    report = ValidationReport(
        feature=spec.definition.name,
        hash=spec.definition.hash,
        parameters=spec.parameters.model_dump(mode="json"),
        reads=_reads_of(graph),
        instrument=instrument,
        timeframe=str(graph.timeframe),
        provider=signal.provider,
        start=first,
        end=last,
        seed=drawn,
        stops=stops,
        random_cuts=random_cuts,
        cuts=_compared_cuts(graph, inputs, window, cuts, outputs),
        start_check=_start_check(graph, inputs, sources, window, outputs),
        lint=_graph_lint(graph),
        created_at=datetime.now(UTC),
    )
    write_atomically(validation_file(report.feature, report.hash), json_writer(report))
    return report


def _window_dates(
    start: str | date, end: str | date, stops: int, random_cuts: int
) -> tuple[date, date]:
    """The window's first and last trade dates, refused out of order, as are negative numbers of
    stops or random cuts."""
    first, last = parse_trade_date(start, "start"), parse_trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    if min(stops, random_cuts) < 0:
        raise ValueError(
            f"Expected numbers of stops and random cuts of at least 0, got stops={stops} and "
            f"random_cuts={random_cuts}."
        )
    return first, last


def _reads_of(graph: FeatureGraph) -> tuple[FeatureRead, ...]:
    """Each feature the validated one reads with its parameters, once, whatever grids it is
    read on, in the order the graph evaluates them."""
    found: dict[str, FeatureRead] = {}
    for node in graph.order:
        if node != graph.slots[_SLOT]:
            read = _read(node.spec)
            found.setdefault(read.model_dump_json(), read)
    return tuple(found.values())


def _read(spec: FeatureSpec) -> FeatureRead:
    definition = spec.definition
    parameters = spec.parameters.model_dump(mode="json")
    return FeatureRead(name=definition.name, hash=definition.hash, parameters=parameters)


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


def _graph_lint(graph: FeatureGraph) -> tuple[LintFinding, ...]:
    """The lint's findings in the validated feature's source, then in those of the features it
    reads, which the cuts evaluate with it: data one of them reads itself is never cut either."""
    definitions = {
        node.spec.definition.hash: node.spec.definition for node in reversed(graph.order)
    }
    return tuple(finding for definition in definitions.values() for finding in lint(definition))


def _graph_of(
    spec: FeatureSpec, reads: Sequence[FeatureSpec], root: str, timeframe: Timeframe
) -> FeatureGraph:
    """The graph of `spec` alone on the signal grid, the features it reads found among `reads`."""
    slots = {_SLOT: spec, **{f"read_{number}": read for number, read in enumerate(reads)}}
    return FeatureGraph.of(slots, root, timeframe).of_slot(_SLOT)


def _sources_of(graph: FeatureGraph, provider: str | None) -> dict[str, SeriesSource]:
    """What `load` reads each instrument of the graph from: its root from `provider`, another
    instrument from the same provider where it holds it, as `compute` reads them."""
    signal = series_source(graph.root, provider=provider)
    return {graph.root: signal, **input_sources(graph, signal)}


def _higher_timeframes(graph: FeatureGraph, inputs: InputBars) -> list[pl.DataFrame]:
    """The `trade_date` and `ts_close` of the bars of each timeframe of the graph's instrument
    coarser than its signal bars."""
    seconds = graph.timeframe.nominal_seconds()
    return [
        frame.select("trade_date", "ts_close")
        for grid, frame in inputs.items()
        if grid.root == graph.root
        and not isinstance(grid, PrintsGrid)
        and grid.timeframe.nominal_seconds() > seconds
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
    """The start check from the window's middle trade date and from the one after it where the
    window holds it: the first that fails, else the middle's, since a memory the middle date's
    week or month resets agrees from that date alone (module docstring)."""
    days = window.get_column("trade_date").unique().sort().to_list()
    middle = len(days) // 2
    checks = [
        _start_check_from(graph, inputs, sources, window, outputs, day)
        for day in days[middle : middle + 2]
    ]
    return next((check for check in checks if not check.passed), checks[0])


def _start_check_from(
    graph: FeatureGraph,
    inputs: InputBars,
    sources: Mapping[str, SeriesSource],
    window: pl.DataFrame,
    outputs: Sequence[str],
    compared_from: date,
) -> StartCheck:
    """The feature evaluated from the warm-up before `compared_from`, each input read from its
    instrument's first bar after that start, and compared with the whole range from that date
    on."""
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
