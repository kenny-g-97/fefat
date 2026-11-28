"""A saved run made again (step 5.10, D-93, D-99, D-126): its strategy, rebuilt by the caller, read
on the data the run read and run through the engine into a folder of its own, past the request
lookup and the saved run that `ff.backtest.run` would return, then its trades table's hash
(`fefat_engine.table_hash`) compared with the saved run's, the proof that what the run read is
pinned (D-11).

What the run read is checked before the engine runs, so that only a run of the same inputs is
compared: the engine's versions; the strategy's saved version and its features' code, before
anything loads or the feature library takes a version; the data's snapshots (`pinned_snapshots`),
whose refusal names the files written since the run when an import merged into them (ADR-0021);
the strategy's specification; the rolls the run crossed; the signal frame; and the engine's
config, the fee table, the calendar, the funding, and the instrument among it; each refused in
words that say which changed, the run's record and results standing, as is data that changed
while the engine ran. Trades that differ then are the sign of something the run did not pin, and
their folder is kept for a notebook to open; trades that match leave nothing behind. The folder
takes the run's artifacts and record alone: one that holds anything else is refused and left as
it is, and an earlier reproduction of the run is removed once every check has passed, its record
last, so that a refusal keeps a reproduction whose trades differed.

    reproduction = ff.backtest.reproduce(run, strategy, Path("reproduced"))
    reproduction.verdict  # matched, or differed with both hashes and the folder kept
"""

import json
import os
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Literal

import fefat_engine

from fefat.backtest.artifacts import RECORD_FILE, read_artifact, write_run
from fefat.backtest.pinned_data import pinned_snapshots
from fefat.backtest.record import EngineVersions, RollRecord, RunRecord, StrategyRecord
from fefat.backtest.run_config import RunConfig
from fefat.backtest.run_inputs import RunInputs, run_inputs
from fefat.backtest.run_signals import RunProgress, RunStage, tell_no_one
from fefat.backtest.runs import Run, engine_run, run_key, strategy_record
from fefat.backtest.schemas import ARTIFACT_SCHEMAS
from fefat.config import resolve_paths
from fefat.features.evaluation import FeatureSpec
from fefat.market.schema import FrozenModel
from fefat.market.store import Store
from fefat.strategy.signal_strategy import SignalStrategy, StrategyPin

_CONFIG_PARTS = {
    "fees": "fee table",
    "hours": "calendar",
    "funding": "funding rates",
    "instrument": "instrument's specification",
}
"""The parts of the engine's config a store or a FEFAT update can change, in words."""
_OWN_FILES = frozenset({RECORD_FILE, *(f"{name}.parquet" for name in ARTIFACT_SCHEMAS)})
"""The files a reproduction's folder holds: a run's record and artifacts."""


class ReproductionVerdict(StrEnum):
    """How a reproduction's trades compare with the saved run's."""

    MATCHED = "matched"
    DIFFERED = "differed"


class ReproductionMatched(FrozenModel):
    """A reproduction whose trades table hashes as the saved run's."""

    verdict: Literal[ReproductionVerdict.MATCHED] = ReproductionVerdict.MATCHED
    trades_hash: str


class ReproductionDiffered(FrozenModel):
    """A reproduction whose trades table hashes otherwise than the saved run's, kept in `folder`."""

    verdict: Literal[ReproductionVerdict.DIFFERED] = ReproductionVerdict.DIFFERED
    saved_trades_hash: str
    reproduced_trades_hash: str
    folder: Path


def reproduce(
    run: Run, strategy: SignalStrategy, into: Path, *, progress: RunProgress = tell_no_one
) -> ReproductionMatched | ReproductionDiffered:
    """`run` made again from `strategy`, which the caller builds as the run's record names it, in
    `into` (module docstring), each stage told to `progress`; refused before the engine runs where
    something the run read changed, and where `into` holds anything but an earlier reproduction of
    the run, which it replaces once every check has passed, so that a refusal keeps it."""
    record = run.record
    _require_this_engine(record.versions)
    _require_a_folder_of_its_own(run, into)
    _require_the_runs_version_and_features(record.strategy, strategy)
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    pinned_snapshots(store, run)
    config = RunConfig.model_validate(record.config.model_dump())
    inputs = run_inputs(strategy, record.window.start, record.window.end, config, paths, progress)
    frame_hash = fefat_engine.table_hash(inputs.signals)
    written = strategy_record(inputs, strategy)
    _require_the_runs_strategy(record.strategy, written)
    _require_the_runs_inputs(record, inputs, frame_hash)
    _remove_earlier(into)
    progress(RunStage.ENGINE_RUNNING)
    artifacts, again = engine_run(inputs, inputs.cache_paths(paths), written, run.hash, frame_hash)
    pinned_snapshots(store, run)
    write_run(into, artifacts, again)
    progress(RunStage.ARTIFACTS_WRITTEN)
    return _verdict(run, into)


def _verdict(run: Run, into: Path) -> ReproductionMatched | ReproductionDiffered:
    """The reproduction in `into` beside `run` by their trades tables' hashes, each read back
    from its file; a match leaves no folder, as far as no file of it is held open, which leaves
    the folder for the next reproduction to remove and the verdict as it is."""
    saved = fefat_engine.table_hash(run.trades)
    reproduced = fefat_engine.table_hash(read_artifact(into, "trades"))
    if reproduced == saved:
        with suppress(ValueError):
            _remove_earlier(into)
        return ReproductionMatched(trades_hash=saved)
    return ReproductionDiffered(
        saved_trades_hash=saved, reproduced_trades_hash=reproduced, folder=into
    )


def _require_this_engine(versions: EngineVersions) -> None:
    running = EngineVersions.running()
    if versions != running:
        raise ValueError(
            f"Expected a run of this engine, {_versions(running)}, got one of {_versions(versions)}: "
            "another engine would fill it otherwise, so run the strategy again for a run of this one."
        )


def _require_a_folder_of_its_own(run: Run, into: Path) -> None:
    """Refuse `into` where it is the run's own folder, a file, or a folder that holds anything
    but an earlier reproduction of the run, its record and artifacts alone, which the
    reproduction replaces; an empty folder, as a removal stopped at the folder itself leaves it,
    takes the reproduction."""
    if into.resolve() == run.folder.resolve():
        raise ValueError(
            f"Expected a folder for the reproduction apart from the run's own, got {into}."
        )
    if not into.exists():
        return
    held = [entry.name for entry in into.iterdir()] if into.is_dir() else [into.name]
    others = [name for name in held if name not in _OWN_FILES]
    if others or (held and not _reproduces(into / RECORD_FILE, run.hash)):
        raise ValueError(
            f"Expected a folder for the reproduction that does not exist yet, or that holds an "
            f"earlier reproduction of run {run.hash[:12]}, got {into}, which holds something else."
        )


def _reproduces(record: Path, run_key: str) -> bool:
    """Whether `record` is the record of a reproduction of the run `run_key`; one that cannot be
    read counts as none."""
    try:
        held = json.loads(record.read_bytes())
    except (OSError, ValueError):
        return False
    return isinstance(held, dict) and held.get("run_key") == run_key


def _remove_earlier(into: Path) -> None:
    """Remove the reproduction in `into`, if any, its record last, so that a removal stopped by a
    file another program holds open keeps the record, which the next reproduction knows and
    removes again; refused in words where a file cannot be removed."""
    if not into.exists():
        return
    try:
        for entry in into.iterdir():
            if entry.name != RECORD_FILE:
                entry.unlink()
        (into / RECORD_FILE).unlink(missing_ok=True)
        into.rmdir()
    except OSError as held:
        raise ValueError(
            f"Expected to remove the earlier reproduction in {into}, got a file of it that could "
            f"not be removed ({held.strerror}): close what holds it open, then reproduce again."
        ) from held


def _require_the_runs_version_and_features(held: StrategyRecord, strategy: SignalStrategy) -> None:
    """Refuse, before anything loads or the library takes a version, a strategy of another saved
    version or parameters than the run's, or whose slots read features of other code."""
    if strategy.saved_version != held.saved_version:
        raise ValueError(
            f"Expected the strategy the run was built from, {_pinned(held.saved_version)}, got "
            f"{_pinned(strategy.saved_version)}: build it as the run's record names it."
        )
    built = {
        slot: (feature.definition.name, feature.definition.hash)
        for slot, feature in strategy.features.items()
        if isinstance(feature, FeatureSpec)
    }
    pinned = {pin.slot: (pin.name, pin.hash) for pin in held.feature_versions}
    if built != pinned:
        named = ", ".join(f"{pin.name} version {pin.version}" for pin in held.feature_versions)
        raise ValueError(
            f"Expected the features the run's slots read, {named or 'none'}, got features of other "
            "code: a feature's code changed since the run, so run the strategy again for a run of it."
        )


def _require_the_runs_strategy(held: StrategyRecord, built: StrategyRecord) -> None:
    """Refuse a strategy whose specification, features' columns, or features' versions and
    parameters are not those the run's record names."""
    if built.model_dump(mode="json") != held.model_dump(mode="json"):
        raise ValueError(
            "Expected the strategy's specification as the run's record holds it, got another: "
            "its execution or its features' columns differ, so build it as the run's record names "
            "it, or run it again."
        )


def _require_the_runs_inputs(record: RunRecord, inputs: RunInputs, frame_hash: str) -> None:
    """Refuse inputs other than those the run read: the rolls it crossed, its signal frame, and
    the engine's config, then its key, which covers them with the data's snapshots."""
    root = record.instrument.root
    again = "Run the strategy again for a run on the data and settings as they are now."
    if inputs.rolls != record.rolls:
        raise ValueError(
            f"Expected the rolls of {root} the run crossed, {_rolls(record.rolls)}, got "
            f"{_rolls(inputs.rolls)}: data imported since the run moved a roll. {again}"
        )
    if frame_hash != record.signal_frame_hash:
        raise ValueError(
            f"Expected the signal frame the run read, hash {record.signal_frame_hash[:12]}, got "
            f"{frame_hash[:12]}: its bars or its features give other values now, as after data "
            f"imported before the run's first trade date or a feature's code changed. {again}"
        )
    changed = _changed_config(record, inputs)
    if changed:
        raise ValueError(
            f"Expected the engine's config as the run read it, got another: the "
            f"{' and '.join(changed)} of {root} changed since the run. {again}"
        )
    if run_key(inputs, frame_hash) != record.run_key:
        raise ValueError(
            f"Expected the run key {record.run_key[:12]}, got another: the data the run reads "
            f"from before its first trade date changed. {again}"
        )


def _changed_config(record: RunRecord, inputs: RunInputs) -> list[str]:
    """The parts of the engine's config that differ from the run's, in words, in their order."""
    held: dict[str, object] = record.model_dump(mode="json")["engine_config"]
    now: dict[str, object] = json.loads(inputs.config_json())
    parts: list[str] = sorted(held.keys() | now.keys())
    return [_CONFIG_PARTS.get(part, part) for part in parts if held.get(part) != now.get(part)]


def _versions(versions: EngineVersions) -> str:
    return (
        f"engine {versions.engine}, fill model {versions.fill_model}, artifact schema "
        f"{versions.artifact_schema}"
    )


def _pinned(pin: StrategyPin | None) -> str:
    if pin is None:
        return "a strategy built in a notebook"
    return f"{pin.name} version {pin.version} with {dict(pin.parameters)}"


def _rolls(rolls: tuple[RollRecord, ...]) -> str:
    if not rolls:
        return "none"
    return ", ".join(
        f"{roll.rolled_from} to {roll.contract} on {roll.trade_date}" for roll in rolls
    )
