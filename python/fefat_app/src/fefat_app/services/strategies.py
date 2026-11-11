"""The strategies of the library over the API (step 5.2, D-93, ADR-0020): the strategies and their
versions listed from the index (`fefat_app.ports.LibraryIndex`); a version's record read from its
file through the SDK, with the lint's findings in its code; the diff of two versions' code; the
templates; and a strategy's code validated and a version saved, each in the executor
(`fefat_app.services.code_runs`), never in the server. A save indexes the library first, so that
a strategy a notebook saved is seen and a library the index cannot follow refuses the save before
anything is written, and again once a version is saved; a refusal of the code writes no version,
so it comes back as it is, with its line, and the next indexing reads any feature its pins
saved."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fefat.features.versions import code_diff
from fefat.strategy import StrategyLintFinding, StrategyVersion, lint
from fefat.strategy.starting_points import StrategyTemplate, templates
from fefat.strategy.versions import load_in
from fefat_app.execution import RefusedCode, StrategySaveSpec, ValidStrategy
from fefat_app.library import (
    IndexedStrategy,
    IndexedStrategyVersion,
    LibraryRefusedError,
    Saved,
    VersionDiff,
    require_as_indexed,
)
from fefat_app.ports import Executor, LibraryIndex
from fefat_app.services.code_runs import LIBRARY_LIMITS, saved_strategy, validated


class NoSuchStrategyError(ValueError):
    """An id that names no strategy the index holds, or a number that names none of its
    versions."""


class StrategyNameInUseError(ValueError):
    """A new strategy under a name a saved strategy has."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Expected a new strategy's name, got {name!r}, which a saved strategy has: save a "
            "version of it instead."
        )


class SavedStrategyVersion(StrategyVersion):
    """A strategy version as the API gives it: its file's record (`fefat.strategy.versions`),
    its row's id and its strategy's in the index, and the lint's findings in its code, which
    warn."""

    id: str
    strategy_id: str
    lint: tuple[StrategyLintFinding, ...]


@dataclass(frozen=True)
class NewStrategyVersion:
    """What a save takes: the version's code, its hypothesis, and its changelog."""

    code: str
    hypothesis: str
    changelog: str


@dataclass(frozen=True)
class SavedStrategies:
    """The strategies of the library in `index`, their versions' files in `strategies_dir`, and
    the trader's code run through `executor` (module docstring)."""

    index: LibraryIndex
    executor: Executor
    strategies_dir: Path

    def strategies(self) -> tuple[IndexedStrategy, ...]:
        """The saved strategies by name, each with its versions in order."""
        return self.index.strategies()

    def versions(self, strategy_id: str) -> tuple[IndexedStrategyVersion, ...]:
        """The versions of the strategy `strategy_id`, in order."""
        return self._strategy(strategy_id).versions

    def version(self, strategy_id: str, number: int) -> SavedStrategyVersion:
        """Version `number` of the strategy `strategy_id`, read from its file."""
        return self._read(self._strategy(strategy_id), number)

    def diff(self, strategy_id: str, earlier: int, later: int) -> VersionDiff:
        """The unified diff of the code of two versions of the strategy `strategy_id`."""
        strategy = self._strategy(strategy_id)
        labels = (f"{strategy.name} v{earlier}", f"{strategy.name} v{later}")
        changed = code_diff(
            self._read(strategy, earlier).code, self._read(strategy, later).code, labels
        )
        return VersionDiff(earlier=earlier, later=later, code_diff=changed)

    def templates(self) -> tuple[StrategyTemplate, ...]:
        """The strategies to start from (`fefat.strategy.starting_points`)."""
        return templates()

    def validate(self, code: str) -> ValidStrategy | RefusedCode:
        """`code` built in a runner as a version's is, valid or refused."""
        return validated(self.executor, code)

    def create(self, name: str, first: NewStrategyVersion) -> Saved[SavedStrategyVersion]:
        """A new strategy `name` with its first version; refused with `StrategyNameInUseError`
        where a saved strategy has the name."""
        self.index.refresh()
        if any(strategy.name == name for strategy in self.index.strategies()):
            raise StrategyNameInUseError(name)
        return self._saved(name, (), first)

    def save(self, strategy_id: str, new: NewStrategyVersion) -> Saved[SavedStrategyVersion]:
        """The next version of the strategy `strategy_id`, or the version of the same code saved
        with the same words, unchanged."""
        self.index.refresh()
        strategy = self._strategy(strategy_id)
        return self._saved(strategy.name, strategy.versions, new)

    def _saved(
        self, name: str, before: Sequence[IndexedStrategyVersion], new: NewStrategyVersion
    ) -> Saved[SavedStrategyVersion]:
        spec = StrategySaveSpec(
            name=name,
            code=new.code,
            hypothesis=new.hypothesis,
            changelog=new.changelog,
            limits=LIBRARY_LIMITS,
        )
        saved = saved_strategy(self.executor, spec)
        self.index.refresh()
        strategy = self._named(saved.name)
        created = saved.version not in {version.version for version in before}
        return Saved(version=self._read(strategy, saved.version), created=created)

    def _strategy(self, strategy_id: str) -> IndexedStrategy:
        for strategy in self.index.strategies():
            if strategy.id == strategy_id:
                return strategy
        raise NoSuchStrategyError(
            f"Expected the id of a saved strategy, got {strategy_id!r}, which names none."
        )

    def _named(self, name: str) -> IndexedStrategy:
        for strategy in self.index.strategies():
            if strategy.name == name:
                return strategy
        raise LibraryRefusedError(
            f"Expected the strategy {name} the runner saved in the index, got none."
        )

    def _read(self, strategy: IndexedStrategy, number: int) -> SavedStrategyVersion:
        """Version `number` of `strategy`, read from its file through the SDK, with its row's
        id; a file the SDK refuses, or one gone or replaced since it was indexed, is refused with
        `LibraryRefusedError`."""
        indexed = [version for version in strategy.versions if version.version == number]
        if not indexed:
            raise NoSuchStrategyError(
                f"Expected a version of strategy {strategy.name}, from 1 to "
                f"{len(strategy.versions)}, got {number}."
            )
        record = read_as_indexed(self.strategies_dir, strategy.name, indexed[0])
        return SavedStrategyVersion(
            **dict(record), id=indexed[0].id, strategy_id=strategy.id, lint=lint(record.code)
        )


def read_as_indexed(
    strategies_dir: Path, name: str, indexed: IndexedStrategyVersion
) -> StrategyVersion:
    """The version `indexed` of the strategy `name`, read from its file in `strategies_dir`
    through the SDK; refused with `LibraryRefusedError` where the SDK refuses the file, or where
    it is gone or replaced since it was indexed (`require_as_indexed`)."""
    try:
        record = load_in(strategies_dir, name, indexed.version)
    except (ValueError, FileNotFoundError) as refused:
        raise LibraryRefusedError(str(refused)) from refused
    require_as_indexed(indexed, record.hash, f"version {indexed.version} of strategy {name}")
    return record
