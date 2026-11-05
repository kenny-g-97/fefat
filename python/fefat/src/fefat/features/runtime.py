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
input's first bar (D-12). A feature's outputs are null on the rows of its warm-up: from the first
row closing at or after the first values of the features it reads, its whole sessions and then its
bars, counted on its grid (`fefat.features.evaluation.first_warm_row`, D-78). A graph is evaluated
over bars read from as many sessions before a window as the largest warm-up needs, its bars
counted back by the session table at the fewest buckets each session holds, then its sessions,
one more where a feature counting sessions reads one whose first value may fall inside a session
(`FeatureGraph.lead_in`), so the window's first row has every value where the data reaches back
so far; `compute` does so for each partition of the feature cache, each slot apart
(`FeatureGraph.of_slot`, `fefat.features.cache`, step 3.3). A feature read by another is one of
the features given, found by its content hash, so each one's parameters are named once; the
features form a graph without cycles. A feature of one output gives its slot's column, and one of
several `<slot>_<output>` columns. A feature declaring the trades input (`TradesInput`, step 3.6)
reads the volume of its instrument's prints by aggressor side in each bucket of its grid,
`buy_volume`, `sell_volume`, and `unknown_side_volume`, joined on the row's own close, when the
bucket's prints are all in hand, and null where none are, on a trade date without prints or in a
bucket held back (`fefat.market.aggressor`, D-78). The dataset input waits for Phase 10.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from functools import cached_property
from graphlib import CycleError, TopologicalSorter
from math import ceil, floor
from types import MappingProxyType

import polars as pl

from fefat.features.as_of import with_feature, with_instrument, with_side_volumes
from fefat.features.evaluation import FeatureSpec, first_warm_row
from fefat.features.grids import Grid, InputBars, PrintsGrid, grid_frame
from fefat.features.inputs import (
    DatasetInput,
    FeatureInput,
    InstrumentInput,
    TimeframeInput,
    TradesInput,
)
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import Session, SessionTable, counted
from fefat.market.schema import Timeframe


@dataclass(frozen=True, eq=False)
class _Node:
    """A feature with its parameters, evaluated on its instrument's grid at `timeframe`; two
    nodes are one where their feature, parameters, and timeframe are."""

    spec: FeatureSpec
    timeframe: Timeframe

    @property
    def name(self) -> str:
        return self.spec.definition.name

    @cached_property
    def _key(self) -> tuple[str, str, str]:
        parameters = self.spec.parameters.model_dump_json()
        return (self.spec.definition.hash, parameters, str(self.timeframe))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Node) and other._key == self._key

    def __hash__(self) -> int:
        return hash(self._key)


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
    features they read, the order to evaluate them in, and the most each one's warm-up may span on
    its grid, in bars and in whole sessions, which the lead-in reads before a window (module
    docstring)."""

    root: str
    timeframe: Timeframe
    slots: Mapping[str, _Node]
    reads: Mapping[_Node, tuple[_Node, ...]]
    order: tuple[_Node, ...]
    warmups: Mapping[_Node, int]
    session_warmups: Mapping[_Node, int]

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
        sessions: dict[_Node, int] = {}
        for node in order:
            inherited = max(
                (
                    _rows_before(warmups[input_node], input_node.timeframe, node.timeframe)
                    for input_node in reads[node]
                ),
                default=0,
            )
            warmups[node] = node.spec.warmup + inherited
            sessions[node] = _session_warmup(
                node, inherited, [sessions[each] for each in reads[node]]
            )
        return cls(
            root=root,
            timeframe=timeframe,
            slots=MappingProxyType(nodes),
            reads=MappingProxyType(reads),
            order=order,
            warmups=MappingProxyType(warmups),
            session_warmups=MappingProxyType(sessions),
        )

    @property
    def signal_grid(self) -> Grid:
        return Grid(self.root, self.timeframe)

    def of_slot(self, slot: str) -> "FeatureGraph":
        """The graph of the one slot `slot` with the features it reads, as this graph evaluates
        them, which the feature cache evaluates and keys apart (`fefat.features.cache`)."""
        node = self.slots[slot]
        read: dict[_Node, None] = {}
        pending = [node]
        while pending:
            current = pending.pop()
            if current not in read:
                read[current] = None
                pending.extend(self.reads[current])
        return FeatureGraph(
            root=self.root,
            timeframe=self.timeframe,
            slots=MappingProxyType({slot: node}),
            reads=MappingProxyType({each: self.reads[each] for each in read}),
            order=tuple(each for each in self.order if each in read),
            warmups=MappingProxyType({each: self.warmups[each] for each in read}),
            session_warmups=MappingProxyType({each: self.session_warmups[each] for each in read}),
        )

    def grid_dates(
        self, grid: Grid, dates: tuple[date, date], sessions: SessionTable
    ) -> tuple[date, date]:
        """The trade dates the bars of `grid` are read for, for the graph's window from `dates`'
        first to its last: the window, on the graph's instrument; and on another, from the trade
        date before the first to the one after the last in its calendar, `sessions`, whose
        sessions may open before the first row's close and before the last row's, so that no
        row's value depends on the window's end."""
        if grid.root == self.root:
            return dates
        first, last = dates
        return sessions.preceding(first).trade_date, sessions.following(last).trade_date

    def grids(self) -> tuple[Grid, ...]:
        """Every grid the graph reads, the signal grid first: its features' grids, the other
        instruments they read, and the prints by side of those reading the trades input."""
        found = dict.fromkeys([self.signal_grid])
        for node in self.order:
            found[Grid(self.root, node.timeframe)] = None
            for declared in node.spec.definition.inputs:
                if isinstance(declared, InstrumentInput):
                    found[Grid(declared.root, node.timeframe)] = None
                if isinstance(declared, TradesInput):
                    found[PrintsGrid(self.root, node.timeframe)] = None
        return tuple(found)

    def lead_in_bars(self) -> int:
        """The most signal bars before its first value that a slot's warm-up needs."""
        needed = (
            _rows_before(self.warmups[node], node.timeframe, self.timeframe)
            for node in self.slots.values()
        )
        return max(needed, default=0)

    def lead_in_sessions(self) -> int:
        """The most whole sessions before its first value that a slot's warm-up needs, beside
        its bars: a session is one on every grid."""
        return max((self.session_warmups[node] for node in self.slots.values()), default=0)

    def lead_in(self, sessions: SessionTable, start: date) -> date:
        """The trade date to read the graph's bars from for a window from `start`: the sessions
        before it, counted back by the session table until they hold the bars `lead_in_bars`
        needs, at the fewest buckets each holds, then `lead_in_sessions` more, so that every slot
        has its value on the first row of `start` where the data reaches back so far (D-71,
        D-78); `start` without a warm-up."""
        needed, day = self.lead_in_bars(), start
        while needed > 0:
            session = sessions.preceding(day)
            needed -= _fewest_buckets(session, self.timeframe)
            day = session.trade_date
        for _ in range(self.lead_in_sessions()):
            day = sessions.preceding(day).trade_date
        return day

    def warmup_text(self, node: _Node) -> str:
        """The most the node's warm-up may span, in words, as `350 bars of 5m` or `1 session of
        5m`."""
        bars, sessions = self.warmups[node], self.session_warmups[node]
        counts = [counted(sessions, "session")] if sessions else []
        if bars or not sessions:
            counts.append(counted(bars, "bar"))
        return f"{' and '.join(counts)} of {node.timeframe}"

    def evaluate(self, inputs: InputBars) -> pl.DataFrame:
        """The slots' columns on the signal grid, after its `ts_close`: each feature evaluated in
        order over the bars of its grid in `inputs` with the inputs it declares, its outputs null
        on the rows of its warm-up, and each slot's joined as of the signal grid's closes under
        its columns (`slot_columns`)."""
        values: dict[_Node, pl.DataFrame] = {}
        warm_from: dict[_Node, int | None] = {}
        for node in self.order:
            values[node], warm_from[node] = self._values_of(node, inputs, values, warm_from)
        frame = grid_frame(inputs, self.signal_grid, "the strategy").select("ts_close")
        for slot, node in self.slots.items():
            renamed = values[node].rename(slot_columns(slot, node.spec))
            frame = frame.join_asof(renamed, on="ts_close", strategy="backward")
        return frame

    def _values_of(
        self,
        node: _Node,
        inputs: InputBars,
        values: Mapping[_Node, pl.DataFrame],
        warm_from: Mapping[_Node, int | None],
    ) -> tuple[pl.DataFrame, int | None]:
        """`ts_close` and the node's outputs on its grid, null on the rows of its warm-up, and the
        close of its first row past it, None where none is."""
        bars = grid_frame(inputs, Grid(self.root, node.timeframe), node.name)
        frame = bars
        dependencies = iter(self.reads[node])
        for declared in node.spec.definition.inputs:
            if isinstance(declared, FeatureInput):
                frame = with_feature(frame, values[next(dependencies)], node.name)
            if isinstance(declared, InstrumentInput):
                other = grid_frame(inputs, Grid(declared.root, node.timeframe), node.name)
                frame = with_instrument(frame, other, declared.root, node.name)
            if isinstance(declared, TradesInput):
                prints = grid_frame(inputs, PrintsGrid(self.root, node.timeframe), node.name)
                frame = with_side_volumes(frame, prints, node.name)
        try:
            outputs = node.spec.outputs_over(frame).collect()
        except pl.exceptions.PolarsError as error:
            grid = Grid(self.root, node.timeframe).described
            raise ValueError(
                f"Expected feature {node.name} to evaluate over the {grid}, got: "
                f"{str(error).splitlines()[0]}"
            ) from error
        first = self._first_warm_row(node, bars, [warm_from[each] for each in self.reads[node]])
        warm = pl.int_range(pl.len()) >= first
        masked = outputs.with_columns(
            pl.when(warm).then(pl.col(output)).alias(output)
            for output in node.spec.definition.outputs
        )
        return masked, bars.item(first, "ts_close") if first < bars.height else None

    def _first_warm_row(
        self, node: _Node, bars: pl.DataFrame, read_from: Sequence[int | None]
    ) -> int:
        """The node's first row past its warm-up, from the first row closing at or after the
        first values of the features it reads, `read_from`, each None where it has none."""
        known = [each for each in read_from if each is not None]
        if len(known) < len(read_from):
            return bars.height
        spec, owner = node.spec, f"feature {node.name}"
        return first_warm_row(
            bars, max(known, default=None), spec.warmup_sessions, spec.warmup, owner
        )


def clashing(columns: Sequence[str], reserved: Iterable[str]) -> list[str]:
    """The `columns` named twice or named as one of the `reserved` columns, sorted."""
    twice = {column for column in columns if columns.count(column) > 1}
    return sorted(twice | (set(columns) & set(reserved)))


def _require_columns_apart(slots: Mapping[str, FeatureSpec]) -> None:
    """Refuse slots whose columns meet each other's or the bars'."""
    columns = [
        column for slot, spec in slots.items() for column in slot_columns(slot, spec).values()
    ]
    taken = clashing(columns, SIGNAL_BAR_COLUMNS)
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


def _session_warmup(node: _Node, inherited_bars: int, inherited: Sequence[int]) -> int:
    """The most whole sessions the node's warm-up may span before its bars: its own, after the
    most the features it reads need, and one more where it counts sessions and those features
    have a warm-up in bars, whose first value may fall inside a session that is then not whole."""
    own = node.spec.warmup_sessions
    straddled = 1 if own and inherited_bars else 0
    return own + max(inherited, default=0) + straddled


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
