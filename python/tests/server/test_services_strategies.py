"""The strategies' service, step 5.2 (D-95): a save the runner refuses comes back as the runner said
it, with the line of the code, whatever the library holds after it, since a refused save writes
no version for the index to follow (the step's code review)."""

from pathlib import Path

import pytest

from fefat_app.execution import (
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ProgressReport,
    RefusedCode,
    StopCheck,
    StrategySaveOutput,
    keep_running,
)
from fefat_app.library import IndexedFeature, IndexedStrategy, LibraryRefusedError
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.strategies import NewStrategyVersion, SavedStrategies

REFUSAL = RefusedCode(line=7, message="SyntaxError: invalid syntax")


class RefusingExecutor:
    """An executor whose runner refuses every strategy's code at line 7."""

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        return ExecutionSucceeded(output=StrategySaveOutput(answer=REFUSAL))

    def close(self) -> None:
        """Nothing to end."""


class LibraryChangedAfterItsFirstIndexing:
    """An index that indexes the library once, then finds a file it cannot follow, as a version
    file a notebook wrote meanwhile by hand would be."""

    def __init__(self) -> None:
        self.indexings = 0

    def refresh(self) -> None:
        self.indexings += 1
        if self.indexings > 1:
            raise LibraryRefusedError("Expected the files as indexed, got one changed by hand.")

    def strategies(self) -> tuple[IndexedStrategy, ...]:
        return ()

    def features(self) -> tuple[IndexedFeature, ...]:
        return ()


def test_a_refused_save_comes_back_with_its_line_whatever_the_library_holds_after_it(
    tmp_path: Path,
) -> None:
    index = LibraryChangedAfterItsFirstIndexing()
    strategies = SavedStrategies(index, RefusingExecutor(), tmp_path)
    first = NewStrategyVersion(code="def strategy(:\n", hypothesis="It runs on.", changelog="")

    with pytest.raises(CodeRefusedError) as refused:
        strategies.create("breakout", first)

    assert (refused.value.line, str(refused.value)) == (7, "SyntaxError: invalid syntax")
    assert index.indexings == 1
