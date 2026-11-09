"""A snippet of Python in the runner (step 4.5): run as a script runs, under the name `__main__`,
with `ff` and `pl` bound, and `bars`, the lazy frame `ff.market.load` gives, where its spec names
a dataset of the store; what it prints to `sys.stdout` kept to its last characters; and what it
raises, a `MemoryError` at the limit included, a failure with the end of its traceback, its
names dropped first so that the memory they held is free to write the result."""

import contextlib
import io
import linecache
from typing import Any

import polars as pl

import fefat as ff
from fefat_app.execution import (
    ExecutionProgress,
    ProgressReport,
    PythonSnippetOutput,
    PythonSnippetSpec,
)
from fefat_app.executor.protocol import RunnerResult, RunnerSucceeded, failed_with

TAIL_CHARS = 4096
"""How many of the last characters a snippet printed its result keeps."""
SNIPPET_FILE = "<snippet>"
"""The file name a snippet's traceback gives its lines."""


class PrintedTail(io.StringIO):
    """What a snippet prints, cut back to its last `TAIL_CHARS` characters whenever it holds
    twice as many, so that a loop of prints holds little."""

    def write(self, text: str, /) -> int:
        written = super().write(text)
        if self.tell() > 2 * TAIL_CHARS:
            kept = self.tail()
            self.seek(0)
            self.truncate()
            super().write(kept)
        return written

    def tail(self) -> str:
        return self.getvalue()[-TAIL_CHARS:]


def snippet(spec: PythonSnippetSpec, report: ProgressReport) -> RunnerResult:
    """Run `spec`'s snippet (module docstring); what it printed, or why it failed."""
    names: dict[str, Any] = {"__name__": "__main__", "ff": ff, "pl": pl}
    bars = spec.bars
    if bars is not None:
        names["bars"] = ff.market.load(
            bars.instrument, bars.timeframe, bars.start, bars.end, provider=bars.provider
        )
        loaded = f"Loaded the bars of {bars.instrument} at {bars.timeframe} from {bars.start}"
        report(ExecutionProgress(percent=20, message=f"{loaded} to {bars.end}", details={}))
    report(ExecutionProgress(percent=30, message="Running the snippet", details={}))
    code = spec.code
    linecache.cache[SNIPPET_FILE] = (len(code), None, code.splitlines(keepends=True), SNIPPET_FILE)
    printed = PrintedTail()
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(code, SNIPPET_FILE, "exec"), names)
    except Exception as failure:
        names.clear()
        return failed_with(failure, printed.tail())
    return RunnerSucceeded(output=PythonSnippetOutput(stdout_tail=printed.tail()))
