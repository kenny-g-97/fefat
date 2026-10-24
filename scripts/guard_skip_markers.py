"""Refuse a pull request that adds a skip marker to a test (the step 2.4 amendment, D-51): a
skipped test, or one expected to fail, passes in silence, and CLAUDE.md never lets a test be
skipped to make it pass.

CI runs it beside the data guard, over the lines a pull request adds:

    uv run --no-project python scripts/guard_skip_markers.py origin/main...HEAD

It reads `git diff --unified=0` of the range and reports every added line of a code file (Python,
Rust, TypeScript, or JavaScript) that holds `pytest.mark.skip`, `skipif`, `xfail`, `pytest.skip(`,
`#[ignore]`, `it.skip`, or `test.skip`, except in this guard and its test, which name the markers.
Tests a pull request deletes stay the step-reviewer's check. Exits 0 when no added line holds a
marker, 1 with each one listed as `path:line: adds <marker>`, and 2 when git cannot be read.
Standard library only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

CODE_SUFFIXES = frozenset({".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
NAMES_THE_MARKERS = frozenset(
    {"scripts/guard_skip_markers.py", "python/tests/test_guard_skip_markers.py"}
)
MARKERS = (
    ("pytest.mark.skip", re.compile(r"\bpytest\.mark\.skip")),
    ("skipif", re.compile(r"\bskipif\b")),
    ("xfail", re.compile(r"\bxfail\b")),
    ("pytest.skip(", re.compile(r"\bpytest\.skip\(")),
    ("#[ignore]", re.compile(r"#\[ignore\b")),
    ("it.skip", re.compile(r"\bit\.skip\b")),
    ("test.skip", re.compile(r"\btest\.skip\b")),
)
HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
REMEDY = (
    "Remove the marker and fix the test: tests are never weakened, skipped, or deleted to make "
    "them pass (CLAUDE.md)."
)


class GitError(Exception):
    """Git could not read the range."""


@dataclass(frozen=True)
class Finding:
    """An added line that skips a test or expects it to fail."""

    path: str
    line: int
    marker: str

    def describe(self) -> str:
        return f"{self.path}:{self.line}: adds {self.marker}"


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Each line that `diff`, written by `git diff --unified=0`, adds: its file, its line number
    in the new file, and its text. A hunk header says how many lines it adds, so an added line
    that itself starts with `+++` is not taken for a file's header."""
    path: str | None = None
    number = 0
    remaining = 0
    for raw in diff.splitlines():
        if remaining > 0 and raw.startswith("+"):
            if path is not None:
                yield path, number, raw[1:]
            number += 1
            remaining -= 1
        elif raw.startswith("+++ "):
            path = raw.removeprefix("+++ b/") if raw.startswith("+++ b/") else None
        elif hunk := HUNK.match(raw):
            number, remaining = int(hunk[1]), int(hunk[2] or "1")


def added_skip_markers(diff: str) -> list[Finding]:
    """The added lines of code files in `diff` that hold a skip marker, each with its first."""
    found: list[Finding] = []
    for path, number, text in added_lines(diff):
        if PurePosixPath(path).suffix not in CODE_SUFFIXES or path in NAMES_THE_MARKERS:
            continue
        marker = next((name for name, pattern in MARKERS if pattern.search(text)), None)
        if marker is not None:
            found.append(Finding(path, number, marker))
    return found


def diff_of(revisions: str) -> str:
    """The lines `revisions` adds and changes, without context, file names unquoted."""
    command = ["git", "-c", "core.quotePath=false", "diff", "--unified=0", "--no-color"]
    command += ["--no-ext-diff", "--diff-filter=AMR", "--end-of-options", revisions, "--"]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if completed.returncode != 0:
        raise GitError(
            f"Expected git diff to read {revisions}, got exit code {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: guard_skip_markers.py <range, such as origin/main...HEAD>", file=sys.stderr)
        return 2
    revisions = argv[0]
    try:
        found = added_skip_markers(diff_of(revisions))
    except (GitError, OSError) as error:
        print(f"Skip-marker guard: could not read {revisions}. {error}", file=sys.stderr)
        return 2
    if not found:
        print(f"Skip-marker guard: no line {revisions} adds skips a test or expects it to fail.")
        return 0
    print(
        f"Skip-marker guard: refused; these lines {revisions} adds skip a test or expect it to fail:"
    )
    for finding in found:
        print(f"  {finding.describe()}")
    print(REMEDY)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
