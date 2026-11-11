"""Saved strategy versions (step 5.2, D-93, D-84): `save` writes a strategy's version record, which
never changes, to `<FEFAT_HOME>/workspaces/default/strategies/<name>/v<n>.json`, `n` counting from
1 per name, as the feature library keeps its versions (`fefat.features.versions`); the files are
the record, which the app's database indexes (ADR-0020), and the app saves through `save` too.

    version = ff.strategy.save("breakout", code, hypothesis="A close above ...", changelog="...")
    ff.strategy.load("breakout", 1)
    ff.strategy.diff("breakout", 1, 2)  # the unified diff of their code
    ff.strategy.library()  # a row for each saved version
    version.strategy(lookback=24)  # the strategy it gives, which a run's record names (step 5.3)

A version holds the strategy's name, number, and kind; its code, a module whose function
`strategy` gives the `SignalStrategy` (`fefat.strategy.source_code`), the only complete record of
a strategy whose expressions call Python (D-71); its hypothesis, one sentence on one line stating
the edge (D-29); the instrument and the timeframe its strategy names with its defaults; the JSON
schema of its parameters; the feature versions its slots read with its defaults, saved in the
library at the save as a run saves them (D-79); its changelog; and when it was saved. Its content
hash covers the code, the parameter schema, and the feature versions it pins, so that the same
code saved again with the same words returns its version, writing nothing, and with other words
is refused, since a version never changes. A version's file is only ever created, whole
(`create_atomically`): a second process saving under the same number at the same moment is
refused, to save again. The lint's findings in its code (`fefat.strategy.source_lint`) are
raised as warnings."""

import hashlib
import json
import os
import re
import warnings
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import AwareDatetime, Field

from fefat.config import resolve_paths
from fefat.features.evaluation import FeatureSpec
from fefat.features.versions import code_diff, create_version, version_numbers
from fefat.features.versions import save as save_feature
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256
from fefat.market.store_files import parsed_json
from fefat.strategy.signal_strategy import SignalStrategy, StrategyPin
from fefat.strategy.source_code import from_source
from fefat.strategy.source_lint import lint
from fefat.strategy.spec import InstrumentRoot, TimeframeText

STRATEGY_NAME = r"^[a-z][a-z0-9_]{0,63}$"
"""A strategy's name, the name of its folder: a lower-case identifier of at most 64 characters,
lower-case since Windows takes `Breakout` and `breakout` for one folder."""
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"{port}{n}" for port in ("com", "lpt") for n in range(10))}
)
"""The names Windows keeps for its devices, which no folder takes."""
LIBRARY_COLUMNS = pl.Schema(
    {
        "name": pl.String,
        "version": pl.Int64,
        "hash": pl.String,
        "instrument": pl.String,
        "timeframe": pl.String,
        "created_at": pl.Datetime("us", "UTC"),
    }
)
"""A row of `library`: a saved version's name, number, content hash, the instrument and the
timeframe its strategy names, and when it was saved."""


class StrategyKind(StrEnum):
    """What a strategy is: a signal strategy (`SignalStrategy`), the only kind until the event
    strategies of Phase 9."""

    SIGNAL = "signal"


class PinnedFeature(FrozenModel):
    """A feature version a strategy's slots read, as the library keeps it: its name, its number,
    and its content hash."""

    name: str
    version: int = Field(ge=1)
    hash: Sha256


class StrategyVersion(FrozenModel):
    """A saved version of a strategy, as its file keeps it (module docstring)."""

    name: str = Field(pattern=STRATEGY_NAME)
    version: int = Field(ge=1)
    kind: StrategyKind
    hash: Sha256
    code: str
    hypothesis: str = Field(min_length=1)
    instrument: InstrumentRoot
    timeframe: TimeframeText
    parameter_schema: dict[str, Any]
    pinned_features: tuple[PinnedFeature, ...]
    changelog: str
    created_at: AwareDatetime

    def content_hash(self) -> str:
        """The hash its code, its parameter schema, and the feature versions it pins give."""
        return content_hash(self.code, self.parameter_schema, self.pinned_features)

    def strategy(self, **parameters: object) -> SignalStrategy:
        """The strategy this version's code gives with `parameters`, its defaults filling those
        left out, validated strictly, and stamped with the version (`saved_version`), which a
        run's record names (step 5.3). Refused where the code, with its defaults, now reads
        another version of a feature than the version pinned, as an indicator of the SDK does
        once the SDK changes it: its runs would read values the version never read, so save the
        code again. A version pins what its slots read with its defaults; a feature only other
        parameters read is pinned by the run that reads it (`feature_versions` in `run.json`)."""
        definition = from_source(self.code)
        _require_its_pins(self, definition.with_defaults)
        built = definition(**parameters)
        bound = definition.parameter_model(**parameters).model_dump(mode="json")
        pin = StrategyPin(name=self.name, version=self.version, hash=self.hash, parameters=bound)
        return built.model_copy(update={"saved_version": pin})


def content_hash(
    code: str, parameter_schema: Mapping[str, object], pinned: Sequence[PinnedFeature]
) -> str:
    """A strategy version's content hash: SHA-256 through `hashlib`, as a feature's
    (`fefat.features.definition.content_hash`), over its code, the hashes of the feature versions
    it pins in the order of their names and hashes, since a library's numbers are its own, and
    its parameter schema as JSON with sorted keys, each on lines of its own."""
    read = [pin.hash for pin in sorted(pinned, key=lambda pin: (pin.name, pin.hash))]
    schema = json.dumps(parameter_schema, sort_keys=True, allow_nan=False)
    return hashlib.sha256("\n".join([code, *read, schema]).encode()).hexdigest()


def save(name: str, code: str, *, hypothesis: str, changelog: str = "") -> StrategyVersion:
    """Save `code` as the next version of the strategy `name`, with its `hypothesis` and
    `changelog`, or return the saved version of its content hash where its words are these,
    writing nothing; the name and the hypothesis are checked before the code runs (module
    docstring)."""
    strategies_dir = resolve_paths(os.environ).strategies_dir
    folder = _folder_in(strategies_dir, name)
    stated = _stated(hypothesis)
    definition = from_source(code)
    strategy = definition.with_defaults
    pinned = _pinned(strategy)
    found = content_hash(definition.code, definition.parameter_schema, pinned)
    for finding in lint(definition.code):
        warnings.warn(f"Strategy {name}, {finding}", UserWarning, stacklevel=2)
    numbers = version_numbers(folder)
    for number in numbers:
        saved = load_in(strategies_dir, name, number)
        if saved.hash == found:
            return _with_its_words(saved, stated, changelog.strip())
    record = StrategyVersion(
        name=name,
        version=max(numbers, default=0) + 1,
        kind=StrategyKind.SIGNAL,
        hash=found,
        code=definition.code,
        hypothesis=stated,
        instrument=strategy.instrument,
        timeframe=strategy.timeframe,
        parameter_schema=definition.parameter_schema,
        pinned_features=pinned,
        changelog=changelog.strip(),
        created_at=datetime.now(UTC),
    )
    described = f"version {record.version} of strategy {name}"
    create_version(folder / f"v{record.version}.json", record, described)
    return record


def _stated(hypothesis: str) -> str:
    """The hypothesis without the spaces around it, refused unless it is one line of text."""
    stated = hypothesis.strip()
    if len(stated.splitlines()) != 1:
        raise ValueError(
            "Expected the hypothesis as one sentence on one line stating the edge, such as "
            f"'A close above the highest of the last hour runs on', got {hypothesis!r}."
        )
    return stated


def _pinned(strategy: SignalStrategy) -> tuple[PinnedFeature, ...]:
    """The feature versions the strategy's slots read, each saved in the library where it is not
    yet, as a run saves them (step 3.7), once each, by name and number."""
    saved = (
        save_feature(feature.definition)
        for feature in strategy.features.values()
        if isinstance(feature, FeatureSpec)
    )
    pins = {
        (each.name, each.version): PinnedFeature(
            name=each.name, version=each.version, hash=each.hash
        )
        for each in saved
    }
    return tuple(pins[key] for key in sorted(pins))


def _require_its_pins(record: StrategyVersion, strategy: SignalStrategy) -> None:
    """Refuse `strategy`, built from `record`'s code with its defaults, where its slots read other
    feature versions, by name and hash, than `record` pins (`StrategyVersion.strategy`)."""
    read = {
        (feature.definition.name, feature.definition.hash)
        for feature in strategy.features.values()
        if isinstance(feature, FeatureSpec)
    }
    pinned = {(pin.name, pin.hash) for pin in record.pinned_features}
    if read == pinned:
        return
    changed = sorted({name for name, _ in read ^ pinned})
    raise ValueError(
        f"Expected the code of version {record.version} of strategy {record.name} to read the "
        f"feature versions it pinned, got another {', '.join(changed)}: its code names a feature, "
        "such as an indicator of the SDK, whose version changed since it was saved; save the code "
        "again as a new version, which pins the features it reads now."
    )


def _with_its_words(saved: StrategyVersion, hypothesis: str, changelog: str) -> StrategyVersion:
    """`saved`, whose code is being saved again, refused where it comes with other words."""
    if (saved.hypothesis, saved.changelog) == (hypothesis, changelog):
        return saved
    raise ValueError(
        f"Expected the hypothesis and the changelog of version {saved.version} of strategy "
        f"{saved.name}, whose code this is, or new code, got other words: a version never "
        "changes, so change the code to save a new version."
    )


def load(name: str, version: int) -> StrategyVersion:
    """The saved version `version` of the strategy `name` (`load_in`)."""
    return load_in(resolve_paths(os.environ).strategies_dir, name, version)


def load_in(strategies_dir: Path, name: str, version: int) -> StrategyVersion:
    """The saved version `version` of the strategy `name` in `strategies_dir`, refused when its
    file holds another strategy or version, or when its content no longer gives its hash; its
    code is read, never run."""
    path = _folder_in(strategies_dir, name) / f"v{version}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected version {version} of strategy {name} at {path}, got no such file."
        )
    record = parsed_json(StrategyVersion, path.read_bytes(), str(path))
    if (record.name, record.version) != (name, version):
        raise ValueError(
            f"Expected version {version} of strategy {name} in {path}, got version "
            f"{record.version} of strategy {record.name}."
        )
    found = record.content_hash()
    if found != record.hash:
        raise ValueError(
            f"Expected the content of {path} to give its hash {record.hash}, got {found}: the "
            "file was changed after it was written."
        )
    return record


def saved_versions_in(strategies_dir: Path) -> list[StrategyVersion]:
    """Every version saved in `strategies_dir`, by name and then number, each read through
    `load_in`; none while nothing is saved."""
    names = (
        sorted(each.name for each in strategies_dir.iterdir() if each.is_dir())
        if strategies_dir.is_dir()
        else []
    )
    return [
        load_in(strategies_dir, name, number)
        for name in names
        for number in version_numbers(strategies_dir / name)
    ]


def library() -> pl.DataFrame:
    """The saved strategies, a row for each version by name and then number, with the columns of
    `LIBRARY_COLUMNS`; none while nothing is saved."""
    rows = [
        (each.name, each.version, each.hash, each.instrument, each.timeframe, each.created_at)
        for each in saved_versions_in(resolve_paths(os.environ).strategies_dir)
    ]
    return pl.DataFrame(rows, schema=LIBRARY_COLUMNS, orient="row")


def diff(name: str, earlier: int, later: int) -> str:
    """The unified diff of the code of versions `earlier` and `later` of the strategy `name`;
    empty where their code is the same."""
    strategies_dir = resolve_paths(os.environ).strategies_dir
    labels = (f"{name} v{earlier}", f"{name} v{later}")
    return code_diff(
        load_in(strategies_dir, name, earlier).code,
        load_in(strategies_dir, name, later).code,
        labels,
    )


def _folder_in(strategies_dir: Path, name: str) -> Path:
    """The folder of the strategy `name`'s versions in `strategies_dir`, refused unless `name` is
    a strategy's (`STRATEGY_NAME`) and no name Windows keeps for a device, so that no name reaches
    outside the folder of strategies."""
    if re.fullmatch(STRATEGY_NAME, name) is None or name in _RESERVED_NAMES:
        raise ValueError(
            "Expected a strategy's name, a lower-case identifier of at most 64 characters that "
            f"Windows keeps for no device, got {name!r}."
        )
    return strategies_dir / name
