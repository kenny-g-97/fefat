"""The saved features and strategies as the app serves them (step 5.2, D-84, ADR-0020): each as the
index holds it, with its row's id, its name, and its versions' numbers, hashes, and times, a
strategy's versions with their instrument, timeframe, hypothesis, and changelog, which the API's
lists read from the database, a version's whole record being read from its file through the SDK;
the diff of two versions' code; and what a save gives. Frozen models, as at every boundary, kept
apart from the port in `fefat_app.ports`, which would otherwise pass 400 lines, as
`fefat_app.execution` is."""

from dataclasses import dataclass

from pydantic import AwareDatetime, BaseModel, ConfigDict

from fefat.strategy import StrategyKind


class IndexedVersion(BaseModel):
    """A saved version as the index holds it: its row's id, its number, its content hash, and when
    it was saved."""

    model_config = ConfigDict(frozen=True)

    id: str
    version: int
    hash: str
    created_at: AwareDatetime


class IndexedStrategyVersion(IndexedVersion):
    """A strategy's version as the index holds it, with the instrument and the timeframe its
    strategy names, its hypothesis, and its changelog."""

    instrument: str
    timeframe: str
    hypothesis: str
    changelog: str


class IndexedFeature(BaseModel):
    """A saved feature as the index holds it: its row's id, its name, and its versions in order."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    versions: tuple[IndexedVersion, ...]


class IndexedStrategy(BaseModel):
    """A saved strategy as the index holds it: its row's id, its name, its kind, and its versions
    in order."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    kind: StrategyKind
    versions: tuple[IndexedStrategyVersion, ...]


class VersionDiff(BaseModel):
    """The unified diff of the code of two versions, `earlier`'s and `later`'s, empty where their
    code is the same; the structured diff of a builder's spec joins it with the builder of
    Phase 6."""

    model_config = ConfigDict(frozen=True)

    earlier: int
    later: int
    code_diff: str


@dataclass(frozen=True)
class Saved[Version]:
    """What a save gives: the version, and whether the save wrote it or found it saved with the
    same content and words, as a retry finds it."""

    version: Version
    created: bool


class LibraryRefusedError(ValueError):
    """Files of the library the index cannot follow, in the indexer's words: a version file the
    SDK refuses, or one deleted or replaced by hand after it was indexed."""
