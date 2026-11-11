"""The features of the library over the API (step 5.2, D-93, ADR-0020), the strategies' mirror for
the feature lab of Phase 6: the features and their versions listed from the index
(`fefat_app.ports.LibraryIndex`), a version's record read from its file through the SDK, the diff
of two versions' code, and a version saved in the executor (`fefat_app.services.code_runs`),
never in the server, the library indexed before it and once a version is saved, as a strategy's
save does."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fefat.features.versions import FeatureVersion, code_diff, load_in
from fefat_app.execution import FeatureSaveSpec
from fefat_app.library import (
    IndexedFeature,
    IndexedVersion,
    LibraryRefusedError,
    Saved,
    VersionDiff,
)
from fefat_app.ports import Executor, LibraryIndex
from fefat_app.services.code_runs import LIBRARY_LIMITS, saved_feature


class NoSuchFeatureError(ValueError):
    """An id that names no feature the index holds, or a number that names none of its
    versions."""


class FeatureNameInUseError(ValueError):
    """A new feature under a name a saved feature has."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Expected a new feature's name, got {name!r}, which a saved feature has: save a "
            "version of it instead."
        )


class SavedFeatureVersion(FeatureVersion):
    """A feature version as the API gives it: its file's record (`fefat.features.versions`), and
    its row's id and its feature's in the index."""

    id: str
    feature_id: str


@dataclass(frozen=True)
class SavedFeatures:
    """The features of the library in `index`, their versions' files in `features_dir`, and the
    trader's code run through `executor` (module docstring)."""

    index: LibraryIndex
    executor: Executor
    features_dir: Path

    def features(self) -> tuple[IndexedFeature, ...]:
        """The saved features by name, each with its versions in order."""
        return self.index.features()

    def versions(self, feature_id: str) -> tuple[IndexedVersion, ...]:
        """The versions of the feature `feature_id`, in order."""
        return self._feature(feature_id).versions

    def version(self, feature_id: str, number: int) -> SavedFeatureVersion:
        """Version `number` of the feature `feature_id`, read from its file."""
        return self._read(self._feature(feature_id), number)

    def diff(self, feature_id: str, earlier: int, later: int) -> VersionDiff:
        """The unified diff of the code of two versions of the feature `feature_id`."""
        feature = self._feature(feature_id)
        labels = (f"{feature.name} v{earlier}", f"{feature.name} v{later}")
        changed = code_diff(
            self._read(feature, earlier).code, self._read(feature, later).code, labels
        )
        return VersionDiff(earlier=earlier, later=later, code_diff=changed)

    def create(self, name: str, code: str) -> Saved[SavedFeatureVersion]:
        """A new feature `name` with its first version, the feature `code` defines; refused with
        `FeatureNameInUseError` where a saved feature has the name."""
        self.index.refresh()
        if any(feature.name == name for feature in self.index.features()):
            raise FeatureNameInUseError(name)
        return self._saved(name, (), code)

    def save(self, feature_id: str, code: str) -> Saved[SavedFeatureVersion]:
        """The next version of the feature `feature_id`, or the version of the same content,
        unchanged."""
        self.index.refresh()
        feature = self._feature(feature_id)
        return self._saved(feature.name, feature.versions, code)

    def _saved(
        self, name: str, before: Sequence[IndexedVersion], code: str
    ) -> Saved[SavedFeatureVersion]:
        spec = FeatureSaveSpec(name=name, code=code, limits=LIBRARY_LIMITS)
        saved = saved_feature(self.executor, spec)
        self.index.refresh()
        feature = self._named(saved.name)
        created = saved.version not in {version.version for version in before}
        return Saved(version=self._read(feature, saved.version), created=created)

    def _feature(self, feature_id: str) -> IndexedFeature:
        for feature in self.index.features():
            if feature.id == feature_id:
                return feature
        raise NoSuchFeatureError(
            f"Expected the id of a saved feature, got {feature_id!r}, which names none."
        )

    def _named(self, name: str) -> IndexedFeature:
        for feature in self.index.features():
            if feature.name == name:
                return feature
        raise LibraryRefusedError(
            f"Expected the feature {name} the runner saved in the index, got none."
        )

    def _read(self, feature: IndexedFeature, number: int) -> SavedFeatureVersion:
        """Version `number` of `feature`, read from its file through the SDK, with its row's id;
        a file the SDK refuses, or one gone since it was indexed, is refused with
        `LibraryRefusedError`."""
        indexed = [version for version in feature.versions if version.version == number]
        if not indexed:
            raise NoSuchFeatureError(
                f"Expected a version of feature {feature.name}, from 1 to "
                f"{len(feature.versions)}, got {number}."
            )
        try:
            record = load_in(self.features_dir, feature.name, number)
        except (ValueError, FileNotFoundError) as refused:
            raise LibraryRefusedError(str(refused)) from refused
        return SavedFeatureVersion(**dict(record), id=indexed[0].id, feature_id=feature.id)
