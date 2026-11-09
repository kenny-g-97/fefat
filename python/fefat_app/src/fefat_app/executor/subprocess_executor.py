"""`SubprocessExecutor`, this machine's executor (step 4.5, `01-architecture.md` sections 6 and
10, D-16): each execution's spec written to a folder of its own under
`FefatPaths.executions_dir`, run by a runner within its timeout and memory limit, and its result
read back and validated, then the folder removed. A snippet starts a runner of its own. A preview
runs in the executor's warm runner, where it keeps one: a runner that waits between previews with
the SDK imported and its caches warm, so that a preview starts no interpreter, one a workspace
since the server keeps one executor (`fefat_app.container`), and started again after it failed,
ran out of time, was asked to stop, or kept another memory limit, which a runner keeps from its
start."""

import tempfile
import threading
import time
from pathlib import Path

from fefat.config import FefatPaths
from fefat_app.execution import (
    EXECUTION_SPEC,
    ExecutionFailed,
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ExecutionTimedOut,
    FeaturePreviewOutput,
    FeaturePreviewSpec,
    ProgressReport,
    StopCheck,
    keep_running,
)
from fefat_app.executor.protocol import (
    SPEC_FILE,
    PreviewSummary,
    RunnerOutputError,
    RunnerResult,
    read_result_file,
    read_series,
)
from fefat_app.executor.runner_process import RunnerEnd, RunnerProcess, removed, start_runner


class SubprocessExecutor:
    """`Executor` over runners of the workspace's interpreter in the folders of `paths`; with
    `warm_previews`, the previews run in one warm runner, kept between them, which `close` ends
    (module docstring)."""

    def __init__(self, paths: FefatPaths, warm_previews: bool) -> None:
        self.paths = paths
        self.warm_previews = warm_previews
        self._warm_lock = threading.Lock()
        self._warm: RunnerProcess | None = None
        self._closed = False

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        folder = self._folder_of(spec)
        try:
            if self.warm_previews and isinstance(spec, FeaturePreviewSpec):
                return self._run_warm(spec, folder, report, check)
            return self._run_alone(spec, folder, report, check)
        finally:
            removed(folder)

    def close(self) -> None:
        """End the warm runner at once, a preview it runs then failing, and refuse any preview
        after, as the server stops."""
        self._closed = True
        running = self._warm
        if running is not None:
            running.stop()
        with self._warm_lock:
            warm, self._warm = self._warm, None
        if warm is not None:
            warm.close()

    def _folder_of(self, spec: ExecutionSpec) -> Path:
        """A new folder holding `spec`."""
        self.paths.executions_dir.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="execution-", dir=self.paths.executions_dir))
        (folder / SPEC_FILE).write_bytes(EXECUTION_SPEC.dump_json(spec))
        return folder

    def _run_alone(
        self, spec: ExecutionSpec, folder: Path, report: ProgressReport, check: StopCheck
    ) -> ExecutionResult:
        """Run `folder`'s execution in a runner of its own, ended with it."""
        deadline = time.monotonic() + spec.limits.timeout_seconds
        runner = start_runner(self.paths, spec.limits.memory_bytes, folder)
        try:
            return _relayed(spec, folder, runner, deadline, report, check)
        finally:
            runner.close()

    def _run_warm(
        self, spec: FeaturePreviewSpec, folder: Path, report: ProgressReport, check: StopCheck
    ) -> ExecutionResult:
        """Run `folder`'s preview in the warm runner, one at a time; a runner that turns out to
        have ended since the last preview is started again, and one whose preview did not end
        as a result of its own, by a timeout, a refused line, or a request to stop, is stopped,
        its state then unknown."""
        with self._warm_lock:
            deadline = time.monotonic() + spec.limits.timeout_seconds
            runner = self._sent(folder, spec.limits.memory_bytes)
            try:
                result = _relayed(spec, folder, runner, deadline, report, check)
            except BaseException:
                runner.stop()
                raise
            if isinstance(result, ExecutionTimedOut):
                runner.stop()
            return result

    def _sent(self, folder: Path, memory_bytes: int) -> RunnerProcess:
        """The warm runner, given `folder`'s preview: started again where it ended, even between
        the look and the sending, or kept another memory limit."""
        runner = self._warm_runner(memory_bytes)
        try:
            runner.send(folder)
        except OSError:
            runner.stop()
            runner = self._warm_runner(memory_bytes)
            runner.send(folder)
        return runner

    def _warm_runner(self, memory_bytes: int) -> RunnerProcess:
        """The warm runner, started again where it ended or keeps another memory limit."""
        if self._closed:
            raise ValueError(
                "Expected an open executor for a preview, got one closed as the server stops."
            )
        warm = self._warm
        if warm is not None and warm.is_running() and warm.memory_bytes == memory_bytes:
            return warm
        if warm is not None:
            warm.close()
        self._warm = start_runner(self.paths, memory_bytes, folder=None)
        return self._warm


def _relayed(
    spec: ExecutionSpec,
    folder: Path,
    runner: RunnerProcess,
    deadline: float,
    report: ProgressReport,
    check: StopCheck,
) -> ExecutionResult:
    """How `folder`'s execution in `runner` ended: timed out at `deadline`, or the result the
    runner left, validated; a line or a result of the runner's that is refused fails it, with the
    end of the runner's log, the runner stopped first. What `report` or `check` raises comes
    through."""
    try:
        if runner.relay(deadline, report, check) is RunnerEnd.TIMED_OUT:
            return ExecutionTimedOut()
        return _validated(spec, folder, read_result_file(folder))
    except RunnerOutputError as refused:
        exit_code = runner.stop()
        return ExecutionFailed(
            error=f"{refused} The runner ended with exit code {exit_code}; its log ends:\n"
            f"{runner.log_tail()}",
            stdout_tail="",
        )


def _validated(spec: ExecutionSpec, folder: Path, ran: RunnerResult) -> ExecutionResult:
    """`ran` as the result of `spec`, a preview's with its series read from `folder`; refused
    where it gave the output of another kind."""
    if isinstance(ran, ExecutionFailed):
        return ran
    output = ran.output
    if output.kind != spec.kind:
        raise RunnerOutputError(
            f"Expected the output of a {spec.kind}, got that of a {output.kind}."
        )
    if isinstance(output, PreviewSummary):
        series = read_series(folder)
        return ExecutionSucceeded(
            output=FeaturePreviewOutput(
                statistics=output.statistics, series=series, warnings=output.warnings
            )
        )
    return ExecutionSucceeded(output=output)
