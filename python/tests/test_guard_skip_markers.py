import subprocess
import sys
from pathlib import Path

import pytest

import guard_skip_markers
from git_repository import GitRepository

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "guard_skip_markers.py"


def diff_adding(path: str, *lines: str, start: int = 1) -> str:
    """A diff that adds `lines` to `path` from line `start` on, as `git diff --unified=0` writes
    it."""
    header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    hunk = f"@@ -0,0 +{start},{len(lines)} @@\n"
    return header + hunk + "".join(f"+{line}\n" for line in lines)


@pytest.mark.parametrize(
    ("line", "marker"),
    [
        ("@pytest.mark.skip(reason='slow')", "pytest.mark.skip"),
        ("@pytest.mark.skipif(sys.platform == 'win32', reason='slow')", "pytest.mark.skipif"),
        ("@mark.skipif(True, reason='slow')", "mark.skipif"),
        ("@pytest.mark.xfail(strict=True)", "pytest.mark.xfail"),
        ("@skipif(True, reason='slow')", "skipif"),
        ("    pytest.skip('not yet')", "pytest.skip("),
        ("numpy = pytest.importorskip('numpy')", "pytest.importorskip("),
        ("@unittest.skip('slow')", "unittest.skip"),
        ("@unittest.skipIf(True, 'slow')", "unittest.skipIf"),
        ("@unittest.expectedFailure", "unittest.expectedFailure"),
        ("#[ignore]", "#[ignore]"),
        ('#[ignore = "slow"]', '#[ignore = "slow"]'),
        ("#[cfg_attr(windows, ignore)]", "#[cfg_attr(windows, ignore)]"),
        ("it.skip('renders the chart', () => {})", "it.skip"),
        ("test.skip('loads the runs', async () => {})", "test.skip"),
        ("describe.skip('the runs page', () => {})", "describe.skip"),
        ("test.skipIf(isWindows)('loads the runs', () => {})", "test.skipIf"),
        ("it.only('renders the chart', () => {})", "it.only"),
        ("test.todo('compares two runs')", "test.todo"),
        ("xit('renders the chart', () => {})", "xit("),
        # The Phase 2 exit's reviews: skips the first markers did not name.
        ("    raise unittest.SkipTest('slow')", "unittest.SkipTest"),
        ("    raise SkipTest('slow')", "SkipTest"),
        ("it.fails('renders the chart', () => {})", "it.fails"),
        ("it.runIf(isWindows)('renders the chart', () => {})", "it.runIf"),
        ("#[cfg(any())]", "#[cfg(any())]"),
    ],
)
def test_each_marker_on_an_added_line_of_code_is_found(line: str, marker: str) -> None:
    found = guard_skip_markers.added_skip_markers(diff_adding("python/tests/test_runs.py", line))

    assert [finding.marker for finding in found] == [marker]


@pytest.mark.parametrize(
    ("path", "line", "marker"),
    [
        (
            "pyproject.toml",
            'addopts = "--ignore=python/tests/test_backtest_golden.py"',
            "--ignore=",
        ),
        (
            "pyproject.toml",
            'addopts = "--deselect python/tests/test_runs.py::test_sums"',
            "--deselect",
        ),
        ("justfile", '    uv run pytest -k "not golden"', "-k"),
        (".github/workflows/ci.yml", "      - run: cargo test -- --skip golden", "--skip"),
    ],
)
def test_a_deselection_added_to_the_test_runners_configuration_is_found(
    path: str, line: str, marker: str
) -> None:
    # The Phase 2 exit's ponytail review: a test left out by the runner's options passes as
    # silently as one skipped in its code.
    found = guard_skip_markers.added_skip_markers(diff_adding(path, line))

    assert [finding.marker for finding in found] == [marker]


def test_a_finding_names_the_file_and_the_line_in_the_new_file() -> None:
    diff = diff_adding("engine/crates/fefat-core/src/lib.rs", "fn sum() {}", "#[ignore]", start=40)

    found = guard_skip_markers.added_skip_markers(diff)

    assert [finding.describe() for finding in found] == [
        "engine/crates/fefat-core/src/lib.rs:41: adds #[ignore]"
    ]


def test_removed_lines_documents_and_words_that_only_contain_a_marker_are_no_findings() -> None:
    removed = (
        "diff --git a/python/tests/test_runs.py b/python/tests/test_runs.py\n"
        "--- a/python/tests/test_runs.py\n"
        "+++ b/python/tests/test_runs.py\n"
        "@@ -3 +2,0 @@\n"
        "-@pytest.mark.skip\n"
    )
    document = diff_adding("docs/engine-guide.md", "Never add `pytest.mark.skip` to a test.")
    inside_words = diff_adding(
        "python/tests/test_runs.py", "audit.skip_rows = xfail_strict", "sys.exit(0)"
    )

    found = guard_skip_markers.added_skip_markers(removed + document + inside_words)

    assert found == []


def test_an_added_line_that_starts_with_plus_signs_is_read_as_a_line() -> None:
    diff = diff_adding("web/src/app.test.ts", "++counter;", "++ b/x; it.skip('x', () => {})")

    found = guard_skip_markers.added_skip_markers(diff)

    assert [finding.describe() for finding in found] == ["web/src/app.test.ts:2: adds it.skip"]


def test_a_name_with_a_space_or_a_quote_is_read_from_its_header() -> None:
    spaced = "+++ b/python/tests/test sums.py\t\n@@ -0,0 +1 @@\n+@pytest.mark.skip\n"
    quoted = '+++ "b/python/tests/test\\"sums.py"\n@@ -0,0 +1 @@\n+@pytest.mark.skip\n'

    found = guard_skip_markers.added_skip_markers(spaced + quoted)

    assert [finding.path for finding in found] == [
        "python/tests/test sums.py",
        'python/tests/test"sums.py',
    ]


def test_the_guard_and_its_test_may_name_the_markers() -> None:
    guard = diff_adding("scripts/guard_skip_markers.py", '("xfail", re.compile("xfail")),')

    assert guard_skip_markers.added_skip_markers(guard) == []


def run_guard(folder: Path, revisions: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), revisions],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_commit_that_adds_a_skip_marker_fails_the_guard(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    repository.stage("test_sums.py", b"def test_sum():\n    assert 1 + 1 == 2\n")
    assert repository.commit("Add a test").returncode == 0
    skipped = b"import pytest\n\n@pytest.mark.skip\ndef test_sum():\n    assert 1 + 1 == 2\n"
    repository.stage("test_sums.py", skipped)
    repository.stage("test more sums.py", skipped)
    assert repository.commit("Skip the tests").returncode == 0

    refused = run_guard(tmp_path, "HEAD~1...HEAD")
    unchanged = run_guard(tmp_path, "HEAD...HEAD")
    unreadable = run_guard(tmp_path, "no-such-branch...HEAD")

    assert refused.returncode == 1
    assert "test_sums.py:3: adds pytest.mark.skip" in refused.stdout
    assert "test more sums.py:3: adds pytest.mark.skip" in refused.stdout
    assert unchanged.returncode == 0
    assert unreadable.returncode == 2
