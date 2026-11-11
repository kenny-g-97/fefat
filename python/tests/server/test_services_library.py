"""The library's services, step 5.2 (D-95): a save the runner refuses comes back as the runner said
it, with the line of the code, whatever the library holds after it, since a refused save writes
no version for the index to follow (the step's code review); and a runner that ran out of time or
failed is a refusal without a line (the step review)."""

from pathlib import Path

import pytest

from fefat_app.execution import (
    ExecutionFailed,
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ExecutionTimedOut,
    FeatureSaveOutput,
    ProgressReport,
    RefusedCode,
    StopCheck,
    StrategySaveOutput,
    keep_running,
)
from fefat_app.library import IndexedFeature, IndexedStrategy, LibraryRefusedError
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.features import SavedFeatures
from fefat_app.services.strategies import NewStrategyVersion, SavedStrategies

REFUSAL = RefusedCode(line=7, message="SyntaxError: invalid syntax")
FIRST = NewStrategyVersion(code="def strategy(:\n", hypothesis="It runs on.", changelog="")


class Finishing:
    """An executor whose every run ends as `result`."""

    def __init__(self, result: ExecutionResult) -> None:
        self.result = result

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        return self.result

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
    refusing = Finishing(ExecutionSucceeded(output=StrategySaveOutput(answer=REFUSAL)))
    strategies = SavedStrategies(index, refusing, tmp_path)

    with pytest.raises(CodeRefusedError) as refused:
        strategies.create("breakout", FIRST)

    assert (refused.value.line, str(refused.value)) == (7, "SyntaxError: invalid syntax")
    assert index.indexings == 1


def test_a_refused_feature_save_comes_back_with_its_line_whatever_the_library_holds_after_it(
    tmp_path: Path,
) -> None:
    index = LibraryChangedAfterItsFirstIndexing()
    refusing = Finishing(ExecutionSucceeded(output=FeatureSaveOutput(answer=REFUSAL)))
    features = SavedFeatures(index, refusing, tmp_path)

    with pytest.raises(CodeRefusedError) as refused:
        features.create("gap", "def gap(:\n")

    assert (refused.value.line, str(refused.value)) == (7, "SyntaxError: invalid syntax")
    assert index.indexings == 1


@pytest.mark.parametrize(
    ("result", "said"),
    [
        (ExecutionTimedOut(), "Expected the code to end within 60 s, got it still running then"),
        (ExecutionFailed(error="MemoryError", stdout_tail=""), "MemoryError"),
    ],
)
def test_a_run_that_timed_out_or_failed_is_a_refusal_without_a_line(
    result: ExecutionResult, said: str, tmp_path: Path
) -> None:
    strategies = SavedStrategies(LibraryChangedAfterItsFirstIndexing(), Finishing(result), tmp_path)

    with pytest.raises(CodeRefusedError) as refused:
        strategies.create("breakout", FIRST)

    assert refused.value.line is None
    assert str(refused.value).startswith(said)
