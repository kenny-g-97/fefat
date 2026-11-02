"""Refuse a pull request that adds a skip marker to a test (the step 2.4 amendment, D-51): a
skipped test, or one expected to fail, passes in silence, and CLAUDE.md never lets a test be
skipped to make it pass.

CI runs it beside the data guard, over the lines a pull request adds:

    uv run --no-project python scripts/guard_skip_markers.py origin/main...HEAD

It reads `git diff --unified=0` of the range and reports every added line of a code file (Python,
Rust, TypeScript, or JavaScript) that skips a test, expects it to fail, or runs others alone:
pytest's `mark.skip`, `skipif`, `xfail`, `pytest.skip(`, and `pytest.importorskip(`; unittest's
`skip`, `skipIf`, `skipUnless`, `expectedFailure`, and `SkipTest`; Rust's `#[ignore]`, a
`#[cfg_attr(...)]` that ignores, and `#[cfg(any())]`; and vitest's `it`, `test`, and `describe`
with `.skip`, `.skipIf`, `.runIf`, `.only`, `.fails`, or `.todo`, and `xit(`, `xtest(`, and
`xdescribe(`. In `pyproject.toml`, the justfile, and CI's workflows it reports an added option
that leaves tests out of a run: `--ignore=`, `--deselect`, `-k`, and `--skip` (the Phase 2
exit). This guard and its test, which name the markers, are left out. Tests a pull request
deletes stay the step-reviewer's check. Exits 0 when no added
line holds a marker, 1 with each one listed as `path:line: adds <marker>`, and 2 when git cannot
be read. Standard library only.
"""

from __future__ import annotations

import ast
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
SKIP_MARKER = re.compile(
    "|".join(
        (
            r"\b(?:pytest\.)?mark\.(?:skip(?:if)?|xfail)\b",
            r"\bpytest\.(?:skip|xfail|importorskip)\(",
            r"\bunittest\.(?:skip(?:If|Unless)?|expectedFailure|SkipTest)\b",
            r"\bSkipTest\b",
            r"\bskip(?:if|If|Unless)\b",
            r"\bxfail\b",
            r"\bexpectedFailure\b",
            r"#\[ignore\b[^\]]*\]?",
            r"#\[cfg_attr\([^\]]*\bignore\b[^\]]*\]?",
            r"#\[cfg\(any\(\)\)\]",
            r"\b(?:it|test|describe)\.(?:skip(?:If)?|only|todo|fails|runIf)\b",
            r"\bx(?:it|test|describe)\(",
        )
    )
)
TEST_RUNNERS_CONFIGURATION = frozenset({"pyproject.toml", "justfile"})
"""The files that set which tests pytest, cargo, and vitest run, beside CI's workflows."""
DESELECTION = re.compile(r"--ignore(?:-glob)?=|--deselect\b|(?<!\S)-k(?=\s)|--skip\b")
"""An option that leaves tests out of a run: pytest's `--ignore`, `--deselect`, and `-k`, and
the `--skip` of `cargo test` and of vitest."""
HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
REMEDY = (
    "Remove the marker and fix the test: tests are never weakened, skipped, or deleted to make "
    "them pass (CLAUDE.md)."
)


class GitError(Exception):
    """Git could not read the range."""


@dataclass(frozen=True)
class Finding:
    """An added line that skips a test or expects it to fail, with the marker's text."""

    path: str
    line: int
    marker: str

    def describe(self) -> str:
        return f"{self.path}:{self.line}: adds {self.marker}"


def new_path(header: str) -> str | None:
    """The new file's path in a `+++` header, none for a deleted file. Git ends a name that holds
    a space with a TAB, and quotes, C-style, a name that holds a quote, a backslash, or a control
    character."""
    name = header.removeprefix("+++ ").rstrip("\t")
    if name.startswith('"') and name.endswith('"'):
        name = str(ast.literal_eval(name))
    return name.removeprefix("b/") if name.startswith("b/") else None


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
            path = new_path(raw)
        elif hunk := HUNK.match(raw):
            number, remaining = int(hunk[1]), int(hunk[2] or "1")


def added_skip_markers(diff: str) -> list[Finding]:
    """The added lines in `diff` of code files that hold a skip marker, and of the test runners'
    configuration that hold a deselection, each with its first."""
    found: list[Finding] = []
    for path, number, text in added_lines(diff):
        markers = _markers_of(path)
        marker = None if markers is None else markers.search(text)
        if marker is not None:
            found.append(Finding(path, number, marker.group(0)))
    return found


def _markers_of(path: str) -> re.Pattern[str] | None:
    """What an added line of `path` may skip tests with: a marker in code, an option in the
    test runners' configuration or CI's workflows; none for other files and this guard's own."""
    if path in NAMES_THE_MARKERS:
        return None
    if PurePosixPath(path).suffix in CODE_SUFFIXES:
        return SKIP_MARKER
    if path in TEST_RUNNERS_CONFIGURATION or path.startswith(".github/workflows/"):
        return DESELECTION
    return None


def diff_of(revisions: str) -> str:
    """The lines `revisions` adds and changes, without context, file names unquoted where git
    allows it."""
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
