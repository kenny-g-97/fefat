"""The runner's own loop (step 4.5, `python -m fefat_app.executor`): for one execution's folder,
given at its start, or, warm, for each folder the executor sends on its stdin, it reads the spec,
runs it by its kind, printing a line of JSON for each report of its progress, leaves its result in
the folder, what its kind gave or the end of the traceback that failed it, and prints an empty
line. The end of its stdin, which the executor's close or its own end gives, ends the runner at
once, whatever it runs, with its session elsewhere than on Windows, whose Job Object ends it, so
that neither the runner nor a process the trader's code started outlives its executor."""

import os
import queue
import signal
import sys
import threading
from functools import partial
from pathlib import Path
from typing import TextIO

from fefat_app.execution import (
    EXECUTION_SPEC,
    ExecutionProgress,
    ExecutionSpec,
    FeaturePreviewSpec,
    ProgressReport,
)
from fefat_app.executor.preview import preview
from fefat_app.executor.protocol import (
    END_OF_EXECUTION,
    SPEC_FILE,
    RunnerResult,
    RunnerSucceeded,
    failed_with,
    write_result_file,
)
from fefat_app.executor.snippet import snippet


def serve(folder: Path | None) -> int:
    """Run `folder`'s execution, or each folder the executor sends, until stdin ends (module
    docstring)."""
    channel = _progress_channel()
    folders: queue.Queue[Path] = queue.Queue()
    threading.Thread(
        target=_folders_until_stdin_ends,
        args=(folders,),
        name="the executor's folders",
        daemon=True,
    ).start()
    if folder is not None:
        _serve_folder(folder, channel)
        return 0
    while True:
        _serve_folder(folders.get(), channel)


def _serve_folder(folder: Path, channel: TextIO) -> None:
    """Run `folder`'s execution, reporting on `channel`, leave its result in the folder, then say
    so; a `SystemExit` of the trader's code fails the execution rather than ending the runner."""
    try:
        spec = EXECUTION_SPEC.validate_json((folder / SPEC_FILE).read_bytes())
        result = _ran(spec, folder, partial(_report, channel))
    except (Exception, SystemExit) as failure:
        result = failed_with(failure, stdout_tail="")
    write_result_file(folder, result)
    channel.write(END_OF_EXECUTION)
    channel.flush()


def _ran(spec: ExecutionSpec, folder: Path, report: ProgressReport) -> RunnerResult:
    if isinstance(spec, FeaturePreviewSpec):
        return RunnerSucceeded(output=preview(spec, folder, report))
    return snippet(spec, report)


def _report(channel: TextIO, progress: ExecutionProgress) -> None:
    channel.write(f"{progress.model_dump_json()}\n")
    channel.flush()


def _progress_channel() -> TextIO:
    """The pipe the executor reads progress from, the runner's stdout as it started; from here on,
    file descriptor 1 writes to the runner's log as 2 does, so that what the trader's code prints
    from C or Rust never reaches the executor as a line of progress."""
    channel = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    return channel


def _folders_until_stdin_ends(folders: queue.Queue[Path]) -> None:
    """Queue each folder the executor sends, a line of stdin each; at the end of stdin, end the
    runner at once, with its session where it has one (module docstring)."""
    for line in sys.stdin:
        folders.put(Path(line.rstrip("\n")))
    if sys.platform != "win32":
        os.killpg(os.getpgrp(), signal.SIGKILL)
    os._exit(0)
