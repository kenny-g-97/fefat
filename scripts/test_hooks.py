"""Smoke tests for the Claude Code hooks in .claude/hooks/.

Each case sends one JSON payload, shaped like the ones Claude Code sends, to a
hook script run by `node`, and checks the hook's answer: allow (no decision,
so the permission rules in .claude/settings.json apply as usual), deny, ask,
or a clean exit for the hooks that never block. Run it through uv (bare
`python` is a Microsoft Store stub on this PC):

    uv run python scripts/test_hooks.py             # every case
    uv run python scripts/test_hooks.py -k push     # the cases whose name contains "push"
    uv run python scripts/test_hooks.py --verbose   # also print what each hook printed

`just test` runs it, and it exits 1 when a case fails. It needs node and git
on PATH. It makes two throwaway git repositories (one on main, one on a step
branch) in a temporary folder, and the formatter cases write their files
under .tmp/, which git ignores. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
SCRATCH = ROOT / ".tmp" / f"hook-tests-{os.getpid()}"
HOOK_TIMEOUT_SECONDS = 60
PARALLEL_HOOKS = 8
ON_WINDOWS = sys.platform == "win32"
STEP_BRANCH = "step/0.5-hook-tests"
RUFF = ROOT / ".venv" / ("Scripts/ruff.exe" if ON_WINDOWS else "bin/ruff")
PRETTIER = ROOT / "web" / "node_modules" / "prettier" / "bin" / "prettier.cjs"
DESIGN_SKILL_SCRIPT = (
    ROOT / ".claude" / "skills" / "backtest-expert" / "scripts" / "evaluate_backtest.py"
)
WEB_SOURCE = ROOT / "web" / "src" / "App.tsx"


class Hook(Enum):
    FILE_GUARD = "guard-file-paths.mjs"
    SHELL_GUARD = "guard-shell-commands.mjs"
    FORMATTER = "format-on-edit.mjs"
    SESSION_BRIEF = "session-brief.mjs"
    REVIEWER_SHELL = "reviewer-shell-commands.mjs"

    @property
    def decides_tool_calls(self) -> bool:
        return self in {Hook.FILE_GUARD, Hook.SHELL_GUARD, Hook.REVIEWER_SHELL}

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", " ")


class Expect(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    CLEAN_EXIT = "exit 0"


@dataclass(frozen=True)
class Repositories:
    on_main: Path
    on_step_branch: Path


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    stdout: str
    stderr: str
    decision: str | None
    reason: str


Check = Callable[[Outcome], str | None]


@dataclass(frozen=True)
class Case:
    name: str
    hook: Hook
    stdin: str
    expect: Expect
    directory: Path = ROOT
    reason_contains: str = ""
    checks: tuple[Check, ...] = ()


@dataclass(frozen=True)
class Result:
    case: Case
    outcome: Outcome
    failure: str | None


def payload(directory: Path, **fields: object) -> str:
    common: dict[str, object] = {
        "session_id": "hook-tests",
        "transcript_path": "",
        "cwd": str(directory),
        "permission_mode": "default",
    }
    return json.dumps({**common, **fields})


def tool_call(
    tool: str, tool_input: dict[str, object], directory: Path = ROOT, event: str = "PreToolUse"
) -> str:
    return payload(
        directory,
        hook_event_name=event,
        tool_name=tool,
        tool_input=tool_input,
        tool_use_id="toolu_hook_tests",
    )


def edit(path: Path | str) -> str:
    return tool_call("Edit", {"file_path": str(path), "old_string": "a", "new_string": "b"})


def write(path: Path | str) -> str:
    return tool_call("Write", {"file_path": str(path), "content": "x"})


def bash(command: str, directory: Path) -> str:
    return tool_call("Bash", {"command": command, "description": "hook test"}, directory)


def powershell(command: str, directory: Path) -> str:
    return tool_call("PowerShell", {"command": command, "description": "hook test"}, directory)


def after_write(path: Path | str) -> str:
    return tool_call("Write", {"file_path": str(path), "content": ""}, event="PostToolUse")


def session_start(source: str, directory: Path) -> str:
    return payload(directory, hook_event_name="SessionStart", source=source)


def output_contains(text: str) -> Check:
    def check(outcome: Outcome) -> str | None:
        return None if text in outcome.stdout else f"expected the output to contain {text!r}"

    return check


def output_contains_one_of(texts: Sequence[str]) -> Check:
    def check(outcome: Outcome) -> str | None:
        found = any(text in outcome.stdout for text in texts)
        return None if found else f"expected the output to contain one of {list(texts)!r}"

    return check


def file_reads(path: Path, expected: str) -> Check:
    def check(_: Outcome) -> str | None:
        actual = path.read_text(encoding="utf-8")
        return (
            None
            if actual == expected
            else f"expected {path.name} to read {expected!r}, got {actual!r}"
        )

    return check


def file_unchanged(path: Path, original: bytes) -> Check:
    def check(_: Outcome) -> str | None:
        if path.read_bytes() == original:
            return None
        path.write_bytes(original)
        return f"expected {path.relative_to(ROOT).as_posix()} to stay unchanged; it changed and was restored"

    return check


def file_guard_cases() -> list[Case]:
    outside = Path(tempfile.gettempdir())

    def case(name: str, stdin: str, expect: Expect, reason: str = "") -> Case:
        return Case(name, Hook.FILE_GUARD, stdin, expect, reason_contains=reason)

    cases = [
        case("edit .env is denied", edit(ROOT / ".env"), Expect.DENY, ".env"),
        case(
            "write .env.example is left to the permission rules",
            write(ROOT / ".env.example"),
            Expect.ALLOW,
        ),
        case("write web/.env.local is denied", write(ROOT / "web" / ".env.local"), Expect.DENY),
        case(
            "write data/x.parquet is denied",
            write(ROOT / "data" / "x.parquet"),
            Expect.DENY,
            "fixtures/synthetic/",
        ),
        case(
            "write fixtures/synthetic/x.parquet is allowed",
            write(ROOT / "fixtures" / "synthetic" / "x.parquet"),
            Expect.ALLOW,
        ),
        case(
            "write fixtures/synthetic/es/trades.dbn.zst with forward slashes is allowed",
            write(f"{ROOT.as_posix()}/fixtures/synthetic/es/trades.dbn.zst"),
            Expect.ALLOW,
        ),
        case(
            "write data/trades.dbn.zst is denied",
            write(ROOT / "data" / "trades.dbn.zst"),
            Expect.DENY,
        ),
        case(
            "write data/trades.csv.gz is denied",
            write(ROOT / "data" / "trades.csv.gz"),
            Expect.DENY,
        ),
        case("write app.duckdb is denied", write(ROOT / "app.duckdb"), Expect.DENY),
        case(
            "write x.parquet outside the project is denied",
            write(outside / "x.parquet"),
            Expect.DENY,
        ),
        case(
            "write secrets/server.pem is denied",
            write(ROOT / "secrets" / "server.pem"),
            Expect.DENY,
            "key",
        ),
        case("write cert.pfx is denied", write(ROOT / "cert.pfx"), Expect.DENY),
        case("write .ssh/id_ed25519 is denied", write(ROOT / ".ssh" / "id_ed25519"), Expect.DENY),
        case(
            "write .ssh/id_ed25519.pub is allowed",
            write(ROOT / ".ssh" / "id_ed25519.pub"),
            Expect.ALLOW,
        ),
        case("write .git/config is denied", write(ROOT / ".git" / "config"), Expect.DENY, ".git"),
        case(
            "write fixtures/goldens/es/run.json asks",
            write(ROOT / "fixtures" / "goldens" / "es" / "run.json"),
            Expect.ASK,
            "engine-golden",
        ),
        case(
            "write an insta snapshot asks",
            write(
                ROOT / "engine" / "crates" / "fefat-engine" / "tests" / "snapshots" / "fills.snap"
            ),
            Expect.ASK,
        ),
        case(
            "write fixtures/goldens/CHANGELOG.md is allowed",
            write(ROOT / "fixtures" / "goldens" / "CHANGELOG.md"),
            Expect.ALLOW,
        ),
        case("write docs/notes.md is allowed", write(ROOT / "docs" / "notes.md"), Expect.ALLOW),
        case(
            "write notes.md outside the project is allowed",
            write(outside / "notes.md"),
            Expect.ALLOW,
        ),
        case(
            "NotebookEdit of notebooks/x.ipynb is allowed",
            tool_call(
                "NotebookEdit",
                {"notebook_path": str(ROOT / "notebooks" / "x.ipynb"), "new_source": "1"},
            ),
            Expect.ALLOW,
        ),
        case("input that is not JSON asks", "not json", Expect.ASK),
        case("empty input asks", "", Expect.ASK),
        case(
            "an Edit without a file_path is left to the permission rules",
            tool_call("Edit", {"old_string": "a"}),
            Expect.ALLOW,
        ),
    ]
    if ON_WINDOWS:
        backslashes = str(ROOT).replace("/", "\\")
        lowered = backslashes.lower()
        cases += [
            case(
                "write <project>\\data\\x.parquet with backslashes is denied",
                write(f"{backslashes}\\data\\x.parquet"),
                Expect.DENY,
            ),
            case(
                "write a golden under a lower-cased project path asks",
                write(f"{lowered}\\fixtures\\goldens\\run.json"),
                Expect.ASK,
            ),
            case(
                "write fixtures\\synthetic\\x.parquet under a lower-cased project path is allowed",
                write(f"{lowered}\\fixtures\\synthetic\\x.parquet"),
                Expect.ALLOW,
            ),
        ]
    return cases


def shell_guard_cases(repositories: Repositories) -> list[Case]:
    step = repositories.on_step_branch
    on_main = repositories.on_main

    def case(
        name: str,
        command: str,
        expect: Expect,
        *,
        tool: str = "Bash",
        directory: Path = step,
        reason: str = "",
    ) -> Case:
        stdin = powershell(command, directory) if tool == "PowerShell" else bash(command, directory)
        return Case(name, Hook.SHELL_GUARD, stdin, expect, directory, reason)

    return [
        case("git push --force is denied", "git push --force", Expect.DENY, reason="Force pushes"),
        case(
            "git push --force is denied in PowerShell",
            "git push --force",
            Expect.DENY,
            tool="PowerShell",
        ),
        case(
            "git push -f to a step branch is denied", "git push -f origin step/0.5-x", Expect.DENY
        ),
        case(
            "git push --force-with-lease is denied",
            "git push --force-with-lease origin step/0.5-x",
            Expect.DENY,
        ),
        case("a +refspec push is denied", "git push origin +step/0.5-x", Expect.DENY),
        case(
            "git push -uf (a short-option cluster) is denied",
            "git push -uf origin step/0.5-x",
            Expect.DENY,
        ),
        case(
            "git push origin main is denied",
            "git push origin main",
            Expect.DENY,
            reason="pull requests",
        ),
        case("git push origin HEAD:main is denied", "git push origin HEAD:main", Expect.DENY),
        case(
            "a push to refs/heads/main is denied",
            "git push origin step/0.5-x:refs/heads/main",
            Expect.DENY,
        ),
        case("deleting main with :main is denied", "git push origin :main", Expect.DENY),
        case(
            "cd web && git push origin main is denied",
            "cd web && git push origin main",
            Expect.DENY,
        ),
        case(
            "git -C <folder> push origin main is denied in PowerShell",
            'git -C "C:\\x" push origin main',
            Expect.DENY,
            tool="PowerShell",
        ),
        case("bash -c 'git push --force' is denied", "bash -c 'git push --force'", Expect.DENY),
        case(
            'powershell -Command "git push -f" is denied',
            'powershell -NoProfile -Command "git push -f"',
            Expect.DENY,
            tool="PowerShell",
        ),
        case("a push inside $( ) is denied", "echo $(git push --force)", Expect.DENY),
        case(
            "git push -u origin step/0.5-x is allowed",
            "git push -u origin step/0.5-x",
            Expect.ALLOW,
        ),
        case(
            "git push -u origin HEAD on a step branch is allowed",
            "git push -u origin HEAD",
            Expect.ALLOW,
        ),
        case("git push on a step branch is allowed", "git push", Expect.ALLOW),
        case("git push --tags is allowed", "git push --tags", Expect.ALLOW),
        case("git push --all is denied", "git push --all origin", Expect.DENY),
        case("git push --mirror is denied", "git push --mirror origin", Expect.DENY),
        case(
            "git push origin : (all matching branches) is denied", "git push origin :", Expect.DENY
        ),
        case(
            "deleting a step branch on GitHub asks",
            "git push origin --delete step/0.3-old",
            Expect.ASK,
        ),
        case("deleting main on GitHub is denied", "git push origin --delete main", Expect.DENY),
        case("git push on main is denied", "git push", Expect.DENY, directory=on_main),
        case(
            "git push origin HEAD on main is denied",
            "git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "a push after cd into an unknown folder asks", "cd $SOMEWHERE && git push", Expect.ASK
        ),
        case(
            "git commit --no-verify is denied",
            "git commit --no-verify -m x",
            Expect.DENY,
            reason="--no-verify",
        ),
        case("git commit -n is denied", "git commit -n -m x", Expect.DENY),
        case("git commit -anm is denied", "git commit -anm x", Expect.DENY),
        case(
            "git commit -uno is allowed (-u takes the value no)",
            "git commit -uno -m x",
            Expect.ALLOW,
        ),
        case(
            "a commit message that mentions --no-verify is allowed",
            'git commit -m "no --no-verify here"',
            Expect.ALLOW,
        ),
        case("a commit on main asks", "git commit -m x", Expect.ASK, directory=on_main),
        case(
            "a heredoc commit message that mentions git push --force is allowed",
            "git commit -F - <<'EOF'\nNever run git push --force or --no-verify.\nEOF",
            Expect.ALLOW,
        ),
        case(
            "a heredoc fed to bash is read as commands",
            "bash <<'EOF'\ngit push --force\nEOF",
            Expect.DENY,
        ),
        case(
            "a PowerShell here-string commit message is allowed",
            "@'\nNever run git push --force.\n'@ | git commit -F -",
            Expect.ALLOW,
            tool="PowerShell",
        ),
        case(
            "git config core.hooksPath x is denied",
            "git config core.hooksPath x",
            Expect.DENY,
            reason="core.hooksPath",
        ),
        case(
            "git config --unset core.hooksPath is denied",
            "git config --unset core.hooksPath",
            Expect.DENY,
        ),
        case(
            "git config set core.hooksPath x is denied",
            "git config set core.hooksPath x",
            Expect.DENY,
        ),
        case(
            "git -c core.hooksPath=... commit is denied",
            "git -c core.hooksPath=/dev/null commit -m x",
            Expect.DENY,
        ),
        case(
            "writing .git/config directly is denied",
            "echo '[core] hooksPath = x' >> .git/config",
            Expect.DENY,
        ),
        case(
            "GIT_CONFIG_PARAMETERS with hooksPath is denied",
            "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='x'\" git commit -m x",
            Expect.DENY,
        ),
        case(
            "git config core.hooksPath (a read) is allowed",
            "git config core.hooksPath",
            Expect.ALLOW,
        ),
        case(
            "git config --get core.hooksPath is allowed",
            "git config --get core.hooksPath",
            Expect.ALLOW,
        ),
        case(
            "rewriting .githooks/pre-commit asks",
            "echo 'exit 0' > .githooks/pre-commit",
            Expect.ASK,
        ),
        case(
            "git add -f data/test.parquet is allowed", "git add -f data/test.parquet", Expect.ALLOW
        ),
        case("git status is allowed", "git status", Expect.ALLOW),
        case("just test is allowed", "just test", Expect.ALLOW),
        case("echo hi is allowed", "echo hi", Expect.ALLOW),
        case(
            "grep for 'git push --force' is allowed",
            "grep -rn 'git push --force' docs",
            Expect.ALLOW,
        ),
        case(
            "just regenerate-goldens asks",
            "just regenerate-goldens",
            Expect.ASK,
            reason="engine-golden",
        ),
        case("cargo insta accept asks", "cargo insta accept", Expect.ASK),
        case("cargo insta test --accept asks", "cargo insta test --accept", Expect.ASK),
        case("INSTA_UPDATE=always cargo test asks", "INSTA_UPDATE=always cargo test", Expect.ASK),
        case(
            "$env:INSTA_UPDATE in PowerShell asks",
            "$env:INSTA_UPDATE='always'; cargo test",
            Expect.ASK,
            tool="PowerShell",
        ),
        case("vitest -u asks", "pnpm --dir web test -- -u", Expect.ASK),
        case("pytest --snapshot-update asks", "uv run pytest --snapshot-update", Expect.ASK),
        case("copying over a golden asks", "cp out.json fixtures/goldens/run.json", Expect.ASK),
        case("cargo insta test is allowed", "cargo insta test", Expect.ALLOW),
        case(
            "a Databento download asks",
            "uv run python scripts/fetch.py --databento ES",
            Expect.ASK,
            reason="cost",
        ),
        case("importing databento asks", 'uv run python -c "import databento"', Expect.ASK),
        case("gh pr merge asks", "gh pr merge 12 --squash --delete-branch", Expect.ASK),
        case(
            "gh api -X DELETE asks",
            "gh api -X DELETE repos/kenny-g-97/fefat/git/refs/heads/x",
            Expect.ASK,
        ),
        case("gh pr view is allowed", "gh pr view 12", Expect.ALLOW),
        case(
            "an encoded PowerShell command asks",
            "powershell -EncodedCommand ZwBpAHQAIABzAHQAYQB0AHUAcwA=",
            Expect.ASK,
            tool="PowerShell",
        ),
        Case("input that is not JSON asks", Hook.SHELL_GUARD, "not json", Expect.ASK, step),
        Case("empty input asks", Hook.SHELL_GUARD, "", Expect.ASK, step),
        Case(
            "a Bash call without a command is left to the permission rules",
            Hook.SHELL_GUARD,
            tool_call("Bash", {"description": "x"}, step),
            Expect.ALLOW,
            step,
        ),
    ]


def formatter_cases() -> list[Case]:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    unknown = SCRATCH / "notes.unknownext"
    unknown.write_text("keep   as is\n", encoding="utf-8")
    python_file = SCRATCH / "spacing.py"
    python_file.write_text("x=1\n", encoding="utf-8")
    rust_file = SCRATCH / "spacing.rs"
    rust_file.write_text("fn main(){}\n", encoding="utf-8")
    python_check = (file_reads(python_file, "x = 1\n"),) if RUFF.exists() else ()
    python_note = "" if RUFF.exists() else " (ruff not installed: exit code only)"
    rust_check = (file_reads(rust_file, "fn main() {}\n"),) if shutil.which("rustfmt") else ()
    rust_note = "" if shutil.which("rustfmt") else " (rustfmt not installed: exit code only)"
    web_check = () if PRETTIER.exists() else (file_unchanged(WEB_SOURCE, WEB_SOURCE.read_bytes()),)

    def case(name: str, stdin: str, checks: tuple[Check, ...] = ()) -> Case:
        return Case(name, Hook.FORMATTER, stdin, Expect.CLEAN_EXIT, checks=checks)

    return [
        case(
            "a file with an unknown extension is left alone",
            after_write(unknown),
            (file_reads(unknown, "keep   as is\n"),),
        ),
        case("a missing file is skipped", after_write(SCRATCH / "missing" / "gone.py")),
        case(
            "a design skill under .claude/skills/ is never reformatted",
            after_write(DESIGN_SKILL_SCRIPT),
            (file_unchanged(DESIGN_SKILL_SCRIPT, DESIGN_SKILL_SCRIPT.read_bytes()),),
        ),
        case(
            f"a Python file is formatted by ruff{python_note}",
            after_write(python_file),
            python_check,
        ),
        case(f"a Rust file is formatted by rustfmt{rust_note}", after_write(rust_file), rust_check),
        case(
            "a web file waits for the formatter the Phase 4 kickoff chooses",
            after_write(WEB_SOURCE),
            web_check,
        ),
        case("input that is not JSON exits cleanly", "not json"),
    ]


def session_cases(repositories: Repositories, branch: str) -> list[Case]:
    def case(name: str, stdin: str, directory: Path, checks: tuple[Check, ...]) -> Case:
        return Case(name, Hook.SESSION_BRIEF, stdin, Expect.CLEAN_EXIT, directory, checks=checks)

    return [
        case(
            "startup prints the branch and where the masterplan stands",
            session_start("startup", ROOT),
            ROOT,
            (output_contains(f"branch {branch}"), output_contains_one_of(["Step ", "Next: "])),
        ),
        case(
            "without the step reader it falls back to what git can tell",
            session_start("resume", repositories.on_main),
            repositories.on_main,
            (output_contains("branch main"), output_contains("Step summary unavailable")),
        ),
        case(
            "input that is not JSON still prints a brief",
            "not json",
            ROOT,
            (output_contains("FEFAT session"),),
        ),
    ]


def reviewer_cases() -> list[Case]:
    allowed = [
        "git diff origin/main...HEAD",
        "git log --oneline -5 | head -3",
        "git -C engine diff --stat",
        "cargo test --manifest-path engine/Cargo.toml -p fefat-engine",
        "uv run pytest -k truncation",
        "uv run --no-project python scripts/masterplan_step.py brief 0.4",
        "just test",
        "cargo fmt --manifest-path engine/Cargo.toml --all --check",
        "rg -n hooksPath docs",
        "git branch --list 'step/*'",
    ]
    denied = [
        "git stash",
        "git checkout -- .",
        "echo x > notes.txt",
        "uv run ruff format .",
        "cargo fmt",
        "git branch -D old",
        "find . -name '*.tmp' -delete",
        "uv run ruff check --fix .",
        "bash -c 'git diff'",
    ]
    cases = [
        Case(
            f"a reviewer may run: {command}", Hook.REVIEWER_SHELL, bash(command, ROOT), Expect.ALLOW
        )
        for command in allowed
    ]
    cases += [
        Case(
            f"a reviewer may not run: {command}",
            Hook.REVIEWER_SHELL,
            bash(command, ROOT),
            Expect.DENY,
        )
        for command in denied
    ]
    cases.append(
        Case(
            "a reviewer may not run: Remove-Item notes.txt (PowerShell)",
            Hook.REVIEWER_SHELL,
            powershell("Remove-Item notes.txt", ROOT),
            Expect.DENY,
            reason_contains="read-only",
        )
    )
    return cases


def all_cases(repositories: Repositories, branch: str) -> list[Case]:
    return [
        *file_guard_cases(),
        *shell_guard_cases(repositories),
        *formatter_cases(),
        *session_cases(repositories, branch),
        *reviewer_cases(),
    ]


def run_hook(case: Case, node: str) -> Outcome:
    environment = {**os.environ, "CLAUDE_PROJECT_DIR": str(case.directory)}
    completed = subprocess.run(
        [node, str(HOOKS / case.hook.value)],
        input=case.stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=case.directory,
        env=environment,
        timeout=HOOK_TIMEOUT_SECONDS,
        check=False,
    )
    decision, reason = read_decision(case.hook, completed.stdout)
    return Outcome(completed.returncode, completed.stdout, completed.stderr, decision, reason)


def read_decision(hook: Hook, stdout: str) -> tuple[str | None, str]:
    if not hook.decides_tool_calls or stdout.strip() == "":
        return None, ""
    try:
        reply = json.loads(stdout)
    except json.JSONDecodeError:
        return "output that is not JSON", stdout.strip()
    if not isinstance(reply, dict) or not isinstance(reply.get("hookSpecificOutput"), dict):
        return "JSON without hookSpecificOutput", stdout.strip()
    specific = reply["hookSpecificOutput"]
    return str(specific.get("permissionDecision")), str(specific.get("permissionDecisionReason"))


def observed(outcome: Outcome) -> str:
    if outcome.exit_code == 2:
        return Expect.DENY.value
    if outcome.exit_code != 0:
        return f"exit code {outcome.exit_code}"
    if outcome.decision is None:
        return Expect.ALLOW.value
    if outcome.decision == "allow":
        return "an explicit allow (guards must leave allowed calls to the permission rules)"
    return outcome.decision


def failure_of(case: Case, outcome: Outcome) -> str | None:
    if case.expect is Expect.CLEAN_EXIT and outcome.exit_code != 0:
        return f"expected exit code 0, got {outcome.exit_code}"
    if case.expect is not Expect.CLEAN_EXIT and observed(outcome) != case.expect.value:
        return f"expected {case.expect.value}, got {observed(outcome)}"
    if case.reason_contains.lower() not in outcome.reason.lower():
        return f"expected the reason to mention {case.reason_contains!r}, got {outcome.reason!r}"
    for check in case.checks:
        failure = check(outcome)
        if failure is not None:
            return failure
    return None


def report(results: list[Result], verbose: bool) -> int:
    width = max(len(result.case.name) for result in results)
    for result in results:
        status = "PASS" if result.failure is None else "FAIL"
        print(
            f"{status}  {result.case.hook.label:<14}  {result.case.name:<{width}}  {result.case.expect.value}"
        )
        if result.failure is not None:
            print(f"      {result.failure}")
        if verbose or result.failure is not None:
            printed = f"{result.outcome.stdout.strip()}\n{result.outcome.stderr.strip()}".strip()
            for line in printed.splitlines():
                print(f"      | {line}")
    failed = [result for result in results if result.failure is not None]
    print()
    if failed:
        print(f"{len(failed)} of {len(results)} hook cases FAILED.")
        return 1
    print(f"All {len(results)} hook cases passed.")
    return 0


@contextmanager
def throwaway_repositories(git: str) -> Iterator[Repositories]:
    with tempfile.TemporaryDirectory(
        prefix="fefat-hook-tests-", ignore_cleanup_errors=True
    ) as folder:
        base = Path(folder)
        empty_config = base / "empty.gitconfig"
        empty_config.write_text("", encoding="utf-8")
        environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty_config),
        }
        yield Repositories(
            on_main=new_repository(git, base / "on-main", "main", environment),
            on_step_branch=new_repository(git, base / "on-step-branch", STEP_BRANCH, environment),
        )


def new_repository(git: str, folder: Path, branch: str, environment: dict[str, str]) -> Path:
    folder.mkdir()
    identity = ["-c", "user.name=hook tests", "-c", "user.email=hook-tests@example.invalid"]
    for arguments in (
        ["init", "-q", "-b", branch],
        [*identity, "commit", "-q", "--allow-empty", "-m", "start"],
    ):
        subprocess.run(
            [git, *arguments], cwd=folder, env=environment, check=True, capture_output=True
        )
    return folder


def current_branch(git: str) -> str:
    completed = subprocess.run(
        [git, "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def remove_scratch() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    try:
        SCRATCH.parent.rmdir()
    except OSError:
        return


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke tests for the Claude Code hooks.")
    parser.add_argument(
        "-k", dest="keyword", default="", help="run the cases whose name contains this text"
    )
    parser.add_argument("--verbose", action="store_true", help="print what each hook printed")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    node = shutil.which("node")
    git = shutil.which("git")
    if node is None or git is None:
        print(f"Expected node and git on PATH, got node={node!r} and git={git!r}.", file=sys.stderr)
        return 1
    try:
        with throwaway_repositories(git) as repositories:
            cases = [
                case
                for case in all_cases(repositories, current_branch(git))
                if arguments.keyword.lower() in case.name.lower()
            ]
            if not cases:
                print(
                    f"Expected at least one case whose name contains {arguments.keyword!r}, got none."
                )
                return 1
            with ThreadPoolExecutor(max_workers=PARALLEL_HOOKS) as pool:
                outcomes = list(pool.map(lambda case: run_hook(case, node), cases))
            results = [
                Result(case, outcome, failure_of(case, outcome))
                for case, outcome in zip(cases, outcomes, strict=True)
            ]
    finally:
        remove_scratch()
    return report(results, arguments.verbose)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
