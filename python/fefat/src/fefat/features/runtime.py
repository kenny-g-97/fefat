"""The feature runtime (step 3.2, `02-engine-and-data.md` §6, D-71): features evaluated in the
order their dependencies give, each over its grid's bars with the inputs it declares joined as
of each row's close, and their warm-up carried through the graph and read from before the
window.

    import fefat as ff

    frame = ff.features.compute(
        {"rsi": rsi(n=14), "rsi_15m": rsi_15m()}, "MES", "5m", "2026-09-21", "2026-09-23"
    ).collect()

A feature reads the bars of its grid, `load`'s signal bars of the instrument at the timeframe
asked for, or at the one its `TimeframeInput` names, such as `15m`, and beside them only what it
declares: the outputs of the features it reads (`FeatureInput`), each evaluated on its grid
unless it names a timeframe of its own, so that a feature of 15-minute bars reading `rsi` reads
an RSI of 15-minute bars; and another instrument's bars at its timeframe (`InstrumentInput`),
each column suffixed with the root, such as `close_MNQ`, with `staleness_MNQ`, the nanoseconds
from that bar's close to the row's. Each input is joined as of the row's `ts_close`, backward,
so a row sees a bar from its close on, never while it is in progress, and holds null before an
input's first bar (D-12). A feature's outputs are null on the rows of its warm-up: its own, after
the most that the features it reads need, counted on its grid. `compute` reads the bars from as
many sessions before `start` as the largest warm-up needs, counted back by the session table, so
the window's first row has every value where the data reaches back so far, and cuts its result
to the window. A feature read by another is one of the features given, found by its content
hash, so each one's parameters are named once; the features form a graph without cycles. A
feature of one output gives its slot's column, and one of several `<slot>_<output>` columns.
The trades input waits for step 3.6 and the dataset input for Phase 10.
"""

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from graphlib import CycleError, TopologicalSorter
from math import ceil, floor
from types import MappingProxyType

import polars as pl

from fefat.config import resolve_paths
from fefat.features.as_of import with_feature, with_instrument
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import (
    DatasetInput,
    FeatureInput,
    InstrumentInput,
    TimeframeInput,
    TradesInput,
)
from fefat.market.api import SIGNAL_BAR_COLUMNS, load, parse_trade_date
from fefat.market.calendar import Session, SessionTable
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe


@dataclass(frozen=True)
class Grid:
    """An instrument's signal bars of one timeframe: the rows a feature is evaluated on, or the
    bars of another instrument it reads."""

    root: str
    timeframe: Timeframe

    def __str__(self) -> str:
        return f"{self.root} {self.timeframe}"


InputBars = Mapping[Grid, pl.DataFrame]
"""The bars of each grid a graph reads, as `load` gives them."""

NO_INPUTS: InputBars = MappingProxyType({})
"""No bars beside a strategy's signal bars."""


@dataclass(frozen=True, eq=False)
class _Node:
    """A feature with its parameters, evaluated on its instrument's grid at `timeframe`; two
    nodes are one where their feature, parameters, and timeframe are."""

    spec: FeatureSpec
    timeframe: Timeframe

    @property
    def name(self) -> str:
        return self.spec.definition.name

    def _key(self) -> tuple[str, str, str]:
        parameters = self.spec.parameters.model_dump_json()
        return (self.spec.definition.hash, parameters, str(self.timeframe))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Node) and other._key() == self._key()

    def __hash__(self) -> int:
        return hash(self._key())


def slot_columns(slot: str, spec: FeatureSpec) -> dict[str, str]:
    """The column each output of `spec` takes in the slot `slot`: the slot's own name for a
    feature of one output, else `<slot>_<output>`."""
    outputs = list(spec.definition.outputs)
    if len(outputs) == 1:
        return {outputs[0]: slot}
    return {output: f"{slot}_{output}" for output in outputs}


@dataclass(frozen=True)
class FeatureGraph:
    """The features of `slots` on the grid of `root` at `timeframe`, the signal grid, with the
    features they read, the order to evaluate them in, and the warm-up of each on its grid
    (module docstring)."""

    root: str
    timeframe: Timeframe
    slots: Mapping[str, _Node]
    reads: Mapping[_Node, tuple[_Node, ...]]
    order: tuple[_Node, ...]
    warmups: Mapping[_Node, int]

    @classmethod
    def of(
        cls, slots: Mapping[str, FeatureSpec], root: str, timeframe: Timeframe
    ) -> "FeatureGraph":
        """The graph of the features in `slots` on the signal grid of `root` at `timeframe`;
        columns that two slots share, a feature read but not given, and a cycle are refused."""
        _require_columns_apart(slots)
        nodes = {slot: _Node(spec, _timeframe_of(spec, timeframe)) for slot, spec in slots.items()}
        reads = _reads(nodes.values(), _specs_by_hash(slots.values()))
        order = _evaluation_order(reads)
        warmups: dict[_Node, int] = {}
        for node in order:
            inherited = (
                _rows_before(warmups[input_node], input_node.timeframe, node.timeframe)
                for input_node in reads[node]
            )
            warmups[node] = node.spec.warmup + max(inherited, default=0)
        return cls(
            root=root,
            timeframe=timeframe,
            slots=MappingProxyType(nodes),
            reads=MappingProxyType(reads),
            order=order,
            warmups=MappingProxyType(warmups),
        )

    @property
    def signal_grid(self) -> Grid:
        return Grid(self.root, self.timeframe)

    def grids(self) -> tuple[Grid, ...]:
        """Every grid the graph reads, the signal grid first: its features' grids and the other
        instruments they read."""
        found = dict.fromkeys([self.signal_grid])
        for node in self.order:
            found[Grid(self.root, node.timeframe)] = None
            for declared in node.spec.definition.inputs:
                if isinstance(declared, InstrumentInput):
                    found[Grid(declared.root, node.timeframe)] = None
        return tuple(found)

    def lead_in_bars(self) -> int:
        """The most signal bars before its first value that a slot's warm-up needs."""
        needed = (
            _rows_before(self.warmups[node], node.timeframe, self.timeframe)
            for node in self.slots.values()
        )
        return max(needed, default=0)

    def lead_in(self, sessions: SessionTable, start: date) -> date:
        """The trade date to read the graph's bars from for a window from `start`: the sessions
        before it, counted back by the session table until they hold the bars `lead_in_bars`
        needs, at the fewest buckets each holds, so that every slot has its value on the first
        row of `start` where the data reaches back so far (D-71); `start` without a warm-up."""
        needed, day = self.lead_in_bars(), start
        while needed > 0:
            session = sessions.preceding(day)
            needed -= _fewest_buckets(session, self.timeframe)
            day = session.trade_date
        return day

    def evaluate(self, inputs: InputBars) -> pl.DataFrame:
        """The slots' columns on the signal grid, after its `ts_close`: each feature evaluated in
        order over the bars of its grid in `inputs` with the inputs it declares, its outputs null
        on the rows of its warm-up, and each slot's joined as of the signal grid's closes under
        its columns (`slot_columns`)."""
        values: dict[_Node, pl.DataFrame] = {}
        for node in self.order:
            values[node] = self._values_of(node, inputs, values)
        frame = _bars_of(inputs, self.signal_grid, "the strategy").select("ts_close")
        for slot, node in self.slots.items():
            renamed = values[node].rename(slot_columns(slot, node.spec))
            frame = frame.join_asof(renamed, on="ts_close", strategy="backward")
        return frame

    def _values_of(
        self, node: _Node, inputs: InputBars, values: Mapping[_Node, pl.DataFrame]
    ) -> pl.DataFrame:
        """`ts_close` and the node's outputs on its grid, null on the rows of its warm-up."""
        frame = _bars_of(inputs, Grid(self.root, node.timeframe), node.name)
        dependencies = iter(self.reads[node])
        for declared in node.spec.definition.inputs:
            if isinstance(declared, FeatureInput):
                frame = with_feature(frame, values[next(dependencies)], node.name)
            if isinstance(declared, InstrumentInput):
                other = _bars_of(inputs, Grid(declared.root, node.timeframe), node.name)
                frame = with_instrument(frame, other, declared.root, node.name)
        outputs = node.spec.outputs_over(frame).collect()
        warm = pl.int_range(pl.len()) >= self.warmups[node]
        return outputs.with_columns(
            pl.when(warm).then(pl.col(output)).alias(output)
            for output in node.spec.definition.outputs
        )


def load_inputs(
    graph: FeatureGraph,
    dates: tuple[date, date],
    provider: str | None = None,
    *,
    contract: str | None = None,
) -> dict[Grid, pl.DataFrame]:
    """The bars of each grid the graph reads but its signal grid, as `load` gives them for the
    trade dates `dates` span: its instrument's at other timeframes from `provider`, where it is
    named, of one `contract` where a run reads one, and another instrument's, from its own
    default provider, from the trade date before the first to the one after the last in that
    instrument's calendar, whose sessions may open before the first row's close and before the
    last row's, so that no row's value depends on the window's end."""
    paths = resolve_paths(os.environ)
    first, last = dates
    loaded = {}
    for grid in graph.grids():
        if grid == graph.signal_grid:
            continue
        timeframe = str(grid.timeframe)
        if grid.root == graph.root:
            symbol = grid.root if contract is None else contract
            loaded[grid] = load(symbol, timeframe, first, last, provider=provider).collect()
            continue
        sessions = instrument_table(paths.data_dir).sessions_of(grid.root, paths.cache_dir)
        earlier, later = sessions.preceding(first), sessions.following(last)
        dates_read = (earlier.trade_date, later.trade_date)
        loaded[grid] = load(grid.root, timeframe, *dates_read).collect()
    return loaded


def compute(
    specs: Mapping[str, FeatureSpec],
    instrument: str,
    timeframe: str,
    start: str | date,
    end: str | date,
    *,
    provider: str | None = None,
) -> pl.LazyFrame:
    """`load`'s signal bars of the root `instrument` of `timeframe` on the trade dates from
    `start` to `end` from `provider`, as `load` names it, each with the columns of the features
    of `specs` by slot (`slot_columns`), the graph they form evaluated over bars read from
    before `start` for their warm-up (module docstring)."""
    first, last = parse_trade_date(start, "start"), parse_trade_date(end, "end")
    graph = FeatureGraph.of(specs, instrument, Timeframe.parse(timeframe))
    paths = resolve_paths(os.environ)
    sessions = instrument_table(paths.data_dir).sessions_of(instrument, paths.cache_dir)
    lead_in = graph.lead_in(sessions, first)
    bars = load(instrument, timeframe, lead_in, last, provider=provider).collect()
    inputs = {graph.signal_grid: bars, **load_inputs(graph, (lead_in, last), provider)}
    values = graph.evaluate(inputs).drop("ts_close")
    whole = pl.concat([bars, values], how="horizontal")
    return whole.filter(pl.col("trade_date") >= first).lazy()


def _require_columns_apart(slots: Mapping[str, FeatureSpec]) -> None:
    """Refuse slots whose columns meet each other's or the bars'."""
    columns = [
        column for slot, spec in slots.items() for column in slot_columns(slot, spec).values()
    ]
    twice = {column for column in columns if columns.count(column) > 1}
    taken = sorted(twice | (set(columns) & set(SIGNAL_BAR_COLUMNS)))
    if taken:
        raise ValueError(
            "Expected the features' columns apart from each other's and from the bars' columns, "
            f"got {', '.join(taken)}."
        )


def _timeframe_of(spec: FeatureSpec, reader: Timeframe) -> Timeframe:
    """The timeframe of the grid `spec` is evaluated on: the one its `TimeframeInput` names, else
    `reader`'s, the grid of the feature or strategy that reads it."""
    named = [
        declared.timeframe
        for declared in spec.definition.inputs
        if isinstance(declared, TimeframeInput)
    ]
    if len(named) > 1:
        raise ValueError(
            f"Expected at most one timeframe input of feature {spec.definition.name}, got "
            f"{', '.join(named)}."
        )
    return Timeframe.parse(named[0]) if named else reader


def _specs_by_hash(specs: Iterable[FeatureSpec]) -> dict[str, list[FeatureSpec]]:
    """The specs given, apart, by their feature's content hash."""
    found: dict[str, dict[str, FeatureSpec]] = {}
    for spec in specs:
        found.setdefault(spec.definition.hash, {})[spec.parameters.model_dump_json()] = spec
    return {feature: list(apart.values()) for feature, apart in found.items()}


def _reads(
    nodes: Iterable[_Node], given: Mapping[str, Sequence[FeatureSpec]]
) -> dict[_Node, tuple[_Node, ...]]:
    """Each node reachable from `nodes` with the nodes it reads, in the order it declares them."""
    reads: dict[_Node, tuple[_Node, ...]] = {}
    pending = list(nodes)
    while pending:
        node = pending.pop()
        if node in reads:
            continue
        _require_inputs_the_runtime_evaluates(node.spec)
        inputs = tuple(
            _Node(spec, _timeframe_of(spec, node.timeframe))
            for spec in _read_specs(node.spec, given)
        )
        reads[node] = inputs
        pending.extend(inputs)
    return reads


def _read_specs(spec: FeatureSpec, given: Mapping[str, Sequence[FeatureSpec]]) -> list[FeatureSpec]:
    """The spec of each feature `spec` reads, the one given of its content hash."""
    found = []
    for declared in spec.definition.inputs:
        if not isinstance(declared, FeatureInput):
            continue
        specs = given.get(declared.hash, ())
        if len(specs) != 1:
            got = "none" if not specs else ", ".join(repr(each.parameters) for each in specs)
            raise ValueError(
                f"Expected the feature {declared.name} that {spec.definition.name} reads among "
                f"the features given, once with its parameters, got {got}: give it a slot, such "
                f"as {declared.name}(...)."
            )
        found.append(specs[0])
    return found


def _require_inputs_the_runtime_evaluates(spec: FeatureSpec) -> None:
    for declared in spec.definition.inputs:
        if isinstance(declared, TradesInput):
            raise ValueError(
                f"Expected inputs the runtime evaluates, got the trades input of feature "
                f"{spec.definition.name}, whose prints by bucket wait for step 3.6."
            )
        if isinstance(declared, DatasetInput):
            raise ValueError(
                f"Expected inputs the runtime evaluates, got the dataset input {declared.name} of "
                f"feature {spec.definition.name}, reserved for Phase 10."
            )


def _evaluation_order(reads: Mapping[_Node, tuple[_Node, ...]]) -> tuple[_Node, ...]:
    """The nodes, each after the nodes it reads; a cycle is refused with its features."""
    try:
        return tuple(TopologicalSorter(reads).static_order())
    except CycleError as error:
        cycle = " -> ".join(node.name for node in error.args[1])
        raise ValueError(
            f"Expected the features to form a graph without cycles, got a cycle: {cycle}."
        ) from error


def _rows_before(warmup: int, timeframe: Timeframe, reader: Timeframe) -> int:
    """The rows of `reader`'s grid before a feature on `timeframe`'s grid with `warmup` has its
    first value there: as many as `reader`'s bars span up to that feature's first value, its
    bar `warmup` closed, at most, so that a coarser feature is never read in progress."""
    ratio = Fraction(timeframe.nominal_seconds(), reader.nominal_seconds())
    return ceil((warmup + 1) * ratio) - 1


def _fewest_buckets(session: Session, timeframe: Timeframe) -> int:
    """The fewest buckets of `timeframe` the session's grid holds: its hours outside its halts
    in whole buckets, and at least one."""
    halted = sum(halt.end - halt.start for halt in session.halts)
    open_for = session.close - session.open - halted
    return max(1, floor(open_for / timeframe.nominal_nanoseconds()))


def _bars_of(inputs: InputBars, grid: Grid, reader: str) -> pl.DataFrame:
    bars = inputs.get(grid)
    if bars is None:
        held = ", ".join(str(each) for each in inputs) or "none"
        raise ValueError(
            f"Expected the bars of {grid} that {reader} reads, got bars of {held}: "
            "ff.features.compute and ff.backtest.run load them."
        )
    return bars
