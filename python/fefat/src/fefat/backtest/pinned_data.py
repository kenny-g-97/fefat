"""The data a saved run read, found again in the store as the run read it (steps 2.11 and 3.7,
ADR-0019), or refused: `Run.explain`, the fidelity check, and the tick check replay a run on
its own records, so they first compare a snapshot of each dataset its record names with the
hash the record pins. The data changes when a file is rewritten, removed, or merged into
(ADR-0021); the refusal then names the partitions written since the run was saved, and the
run's record and results stand."""

from typing import TYPE_CHECKING

from fefat.backtest.artifacts import RECORD_FILE
from fefat.backtest.record import DatasetRecord, RunRecord
from fefat.market.coverage import session_datasets
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.schema import parse_schema_name
from fefat.market.snapshot import Snapshot
from fefat.market.store import Store

if TYPE_CHECKING:
    from fefat.backtest.runs import Run

_PARTITIONS_NAMED_AT_MOST = 3
"""How many partitions written since a run its refusal names before it counts the rest."""


def pinned_snapshots(store: Store, run: "Run") -> dict[str, Snapshot]:
    """A snapshot of each dataset of the run's instrument that the run read, by schema, refused
    unless it is the one the run's record pins, as is one of another instrument its features read
    (step 3.7), and refused when the store holds trades or bars of the run's provider in its
    dates that the run did not read: the data changed since the run otherwise, as when an import
    merged a file into a partition it read (ADR-0021), and the refusal names the partitions
    written since the run was saved. `fidelity_check` reruns a saved run on the data this
    guards too."""
    record = run.record
    snapshots = {}
    for dataset in record.datasets:
        request = _request(dataset)
        snapshot = store.snapshot(request)
        if snapshot.sha256 != dataset.snapshot:
            raise ValueError(
                f"Expected the store's {dataset.schema_name} of {dataset.root} as the run read "
                f"it, snapshot {dataset.snapshot[:12]}, got {snapshot.sha256[:12]}: the data "
                f"changed since the run. {_written_since(store, request, run)} The run's record "
                "and results stand; run the strategy again for a run on the data as it is now."
            )
        if dataset.root == record.instrument.root:
            snapshots[dataset.schema_name] = snapshot
    _require_no_dataset_since(store, record)
    return snapshots


def _written_since(store: Store, request: PartitionRequest, run: "Run") -> str:
    """Which partitions of `request` were written since the run was saved, the first few by
    their paths: a run's record keeps its snapshots' hashes, not each file's, so the files'
    times tell, as they tell a stale quality report (D-94). Where none is newer than the run's
    record, a partition it read was removed, or put back with an older time."""
    saved = (run.folder / RECORD_FILE).stat().st_mtime_ns
    written = sorted(
        file.partition.relative_path().as_posix()
        for file in store.list_partitions(request.dataset)
        if request.selects(file.partition) and file.modified_ns >= saved
    )
    if not written:
        return (
            "None of its partitions was written since the run was saved, so one was removed or "
            "put back from a copy."
        )
    more = len(written) - _PARTITIONS_NAMED_AT_MOST
    others = f", and {more:,} more" if more > 0 else ""
    named = ", ".join(written[:_PARTITIONS_NAMED_AT_MOST])
    return f"Written since the run was saved: {named}{others}."


def _require_no_dataset_since(store: Store, record: RunRecord) -> None:
    """Refuse a dataset of trades, TBBO, or bars of a provider and root the run read, its own or
    another instrument's its features read (step 3.7), with partitions in the dates it read them
    for that its record does not name: an import since the run, which the engine cache a rerun
    builds, or its features, would read."""
    read: dict[tuple[str, str], list[DatasetRecord]] = {}
    for named in record.datasets:
        read.setdefault((named.provider, named.root), []).append(named)
    for dataset in session_datasets(store):
        held = read.get((dataset.provider, dataset.root), [])
        if not held or str(dataset.schema_name) in {each.schema_name for each in held}:
            continue
        first, last = min(each.first for each in held), max(each.last for each in held)
        request = PartitionRequest(dataset=dataset, start=first, end=last)
        if any(request.selects(file.partition) for file in store.list_partitions(dataset)):
            root, provider = dataset.root, dataset.provider
            raise ValueError(
                f"Expected the store's data of {root} as the run read it, got "
                f"{dataset.schema_name} of {root} from {provider} in the run's dates, which it "
                "did not read: it was imported since the run, so run it again first."
            )


def _request(dataset: DatasetRecord) -> PartitionRequest:
    named = Dataset(
        provider=dataset.provider,
        schema_name=parse_schema_name(dataset.schema_name),
        root=dataset.root,
    )
    return PartitionRequest(dataset=named, start=dataset.first, end=dataset.last)
