"""The features a feature graph evaluates (`fefat.features.runtime`, steps 3.2 and 3.7, D-72):
each node a feature with its parameters on the grid of a timeframe, with the nodes it reads in the
order it declares them, evaluated in an order that puts each after them.

A feature another reads (`FeatureInput`) is found by its content hash: with the parameters its
reader binds, where its decorator binds them, as a combination's does (`fefat.features.combine`);
else the one given in a slot of that hash, so that its parameters are named once; and where no
slot gives it, with its defaults (`BACKLOG.md`). Its definition comes from a slot of its hash, or
else from those this process defined (`fefat.features.registry`). A feature read without bound
parameters while two slots give it with others, one read without a slot whose parameters lack a
default, and a cycle are refused, each with its features named. The dataset input waits for
Phase 10."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import DatasetInput, FeatureInput, TimeframeInput
from fefat.features.registry import registered
from fefat.market.schema import Timeframe

if TYPE_CHECKING:
    from fefat.features.definition import FeatureDef


@dataclass(frozen=True, eq=False)
class FeatureNode:
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
        return isinstance(other, FeatureNode) and other._key == self._key

    def __hash__(self) -> int:
        return hash(self._key)


def timeframe_of(spec: FeatureSpec, reader: Timeframe) -> Timeframe:
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


def nodes_read(
    nodes: Iterable[FeatureNode], slots: Iterable[FeatureSpec]
) -> dict[FeatureNode, tuple[FeatureNode, ...]]:
    """Each node reachable from `nodes` with the nodes it reads, in the order it declares them,
    the features read found among the specs of the `slots` (module docstring)."""
    given = _specs_by_hash(slots)
    reads: dict[FeatureNode, tuple[FeatureNode, ...]] = {}
    pending = list(nodes)
    while pending:
        node = pending.pop()
        if node in reads:
            continue
        _require_inputs_the_runtime_evaluates(node.spec)
        inputs = tuple(
            FeatureNode(spec, timeframe_of(spec, node.timeframe))
            for spec in _read_specs(node.spec, given)
        )
        reads[node] = inputs
        pending.extend(inputs)
    return reads


def evaluation_order(
    reads: Mapping[FeatureNode, tuple[FeatureNode, ...]],
) -> tuple[FeatureNode, ...]:
    """The nodes, each after the nodes it reads; a cycle is refused with its features."""
    try:
        return tuple(TopologicalSorter(reads).static_order())
    except CycleError as error:
        cycle = " -> ".join(node.name for node in error.args[1])
        raise ValueError(
            f"Expected the features to form a graph without cycles, got a cycle: {cycle}."
        ) from error


def _specs_by_hash(specs: Iterable[FeatureSpec]) -> dict[str, list[FeatureSpec]]:
    """The specs given, apart, by their feature's content hash."""
    found: dict[str, dict[str, FeatureSpec]] = {}
    for spec in specs:
        found.setdefault(spec.definition.hash, {})[spec.parameters.model_dump_json()] = spec
    return {feature: list(apart.values()) for feature, apart in found.items()}


def _read_specs(spec: FeatureSpec, given: Mapping[str, Sequence[FeatureSpec]]) -> list[FeatureSpec]:
    """The spec of each feature `spec` reads (module docstring)."""
    reader = spec.definition.name
    return [
        _read_spec(reader, declared, given)
        for declared in spec.definition.inputs
        if isinstance(declared, FeatureInput)
    ]


def _read_spec(
    reader: str, declared: FeatureInput, given: Mapping[str, Sequence[FeatureSpec]]
) -> FeatureSpec:
    """The feature `declared` with the parameters `reader` binds, else that of its one slot
    among those `given`, else its defaults, beside no slot of another version of it."""
    slots = given.get(declared.hash, ())
    if declared.parameters is not None:
        definition = _definition_of(reader, declared, slots)
        return _bound(reader, declared.name, declared.parameters, definition)
    if len(slots) == 1:
        return slots[0]
    definition = None if slots else registered(declared.hash)
    lacking = [] if definition is None else _without_defaults(definition)
    if definition is None or lacking:
        got = ", ".join(repr(each.parameters) for each in slots) if slots else "none"
        if lacking:
            got += f", and no default of {', '.join(lacking)}"
        raise ValueError(
            f"Expected the feature {declared.name} that {reader} reads among the features given, "
            f"once with its parameters, got {got}: give it a slot, such as {declared.name}(...)."
        )
    _require_no_other_version(reader, declared, given)
    return definition()


def _require_no_other_version(
    reader: str, declared: FeatureInput, given: Mapping[str, Sequence[FeatureSpec]]
) -> None:
    """Refuse a feature read with its defaults beside a slot of another version of its name,
    as a reader defined before that version's cell ran again reads the old one unseen."""
    others = sorted(
        {
            spec.definition.hash[:12]
            for specs in given.values()
            for spec in specs
            if spec.definition.name == declared.name
        }
    )
    if others:
        raise ValueError(
            f"Expected the feature {declared.name} that {reader} reads, {declared.hash[:12]}, "
            f"got another {declared.name} in a slot, {', '.join(others)}: define {reader} again, "
            f"so that it reads the {declared.name} given, or give its own {declared.name} a slot."
        )


def _definition_of(
    reader: str, declared: FeatureInput, slots: Sequence[FeatureSpec]
) -> "FeatureDef":
    """The definition of the feature `declared`: a slot's of its hash, else this process's."""
    definition = slots[0].definition if slots else registered(declared.hash)
    if definition is None:
        raise ValueError(
            f"Expected the feature {declared.name} that {reader} reads, {declared.hash[:12]}, "
            "defined in this process, got none: define it, or read it from the library with "
            f"ff.features.ref({declared.name!r}, version=...)."
        )
    return definition


def _bound(
    reader: str, name: str, parameters: Mapping[str, object], definition: "FeatureDef"
) -> FeatureSpec:
    """`definition`, of the feature `name`, with the `parameters` `reader` binds for it, refused
    where they are not its."""
    try:
        return definition(**parameters)
    except ValueError as error:
        raise ValueError(
            f"Expected the parameters feature {reader} binds for the feature {name} it reads "
            f"among that feature's, got: {error}"
        ) from error


def _without_defaults(definition: "FeatureDef") -> list[str]:
    """The parameters of `definition` that have no default."""
    fields = definition.parameter_model.model_fields
    return [name for name, field in fields.items() if field.is_required()]


def _require_inputs_the_runtime_evaluates(spec: FeatureSpec) -> None:
    for declared in spec.definition.inputs:
        if isinstance(declared, DatasetInput):
            raise ValueError(
                f"Expected inputs the runtime evaluates, got the dataset input {declared.name} of "
                f"feature {spec.definition.name}, reserved for Phase 10."
            )
