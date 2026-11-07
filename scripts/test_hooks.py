"""Smoke tests for the Claude Code hooks in .claude/hooks/.

Each case sends one JSON payload, shaped like the ones Claude Code sends, to a
hook script run by `node`, and checks the hook's answer: allow (no decision,
so the permission rules in .claude/settings.json apply as usual), deny, ask,
or a clean exit for the hooks that never block. Run it through uv (bare
`python` is a Microsoft Store stub on this PC):

    uv run python scripts/test_hooks.py             # every case
    uv run python scripts/test_hooks.py -k push     # the cases whose name contains "push"
    uv run python scripts/test_hooks.py --verbose   # also print what each hook printed
    uv run python scripts/test_hooks.py --hooks <folder>   # test a changed copy first

`just test` runs it, and it exits 1 when a case fails. It needs node and git
on PATH, and ruff and rustfmt for the formatter cases (`just setup` installs
both). Test a changed copy of the hooks with --hooks before putting it in
.claude/hooks/: the live guards check every command of the session, so a
broken one blocks the session's own work. It makes two throwaway git
repositories (one on main, one on a step
branch) in a temporary folder, and the formatter cases write their files
under .tmp/, which git ignores. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
WEB_SCRATCH = ROOT / "web" / ".tmp" / f"hook-tests-{os.getpid()}"
"""Under web/, where the formatter picks oxfmt; `.tmp/` is ignored at any depth."""
DESIGN_SKILL_SCRIPT = (
    ROOT / ".claude" / "skills" / "backtest-expert" / "scripts" / "evaluate_backtest.py"
)
GENERATED_API_TYPES = ROOT / "web" / "src" / "api" / "schema.d.ts"
AGENTS = ROOT / ".claude" / "agents"


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


def write_text(path: Path | str, content: str) -> str:
    return tool_call("Write", {"file_path": str(path), "content": content})


def edit_text(path: Path | str, new_string: str) -> str:
    return tool_call("Edit", {"file_path": str(path), "old_string": "a", "new_string": new_string})


def bash(command: str, directory: Path) -> str:
    return tool_call("Bash", {"command": command, "description": "hook test"}, directory)


def powershell(command: str, directory: Path) -> str:
    return tool_call("PowerShell", {"command": command, "description": "hook test"}, directory)


def agent_name(path: Path) -> str:
    """The frontmatter name, which Claude Code sends hooks as agent_type."""
    found = re.search(r"^name: *(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE)
    if found is None:
        raise ValueError(f"Expected a name: line in {path.name}, got none.")
    return found.group(1)


def in_subagent(stdin: str, agent_type: str) -> str:
    return json.dumps(
        {**json.loads(stdin), "agent_id": "agent_hook_tests", "agent_type": agent_type}
    )


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


def output_lacks(text: str) -> Check:
    def check(outcome: Outcome) -> str | None:
        return None if text not in outcome.stdout else f"expected no {text!r} in the output"

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
        case("write .envrc is denied", write(ROOT / ".envrc"), Expect.DENY, ".env"),
        case("write config/prod.env is denied", write(ROOT / "config" / "prod.env"), Expect.DENY),
        case(
            "write GIT~1/config (a Windows short name) asks",
            write(ROOT / "GIT~1" / "config"),
            Expect.ASK,
            "short name",
        ),
        case(
            "write .git./config (a trailing dot) asks",
            write(f"{ROOT.as_posix()}/.git./config"),
            Expect.ASK,
        ),
        case(
            "a short name of a file in .claude asks",
            write(ROOT / ".claude" / "SETTIN~1.JSO"),
            Expect.ASK,
        ),
        case(
            "the NTFS stream form of .git asks",
            write(f"{ROOT.as_posix()}/.git::$INDEX_ALLOCATION/config"),
            Expect.ASK,
        ),
        case(
            "a .git folder reached through a short-named parent is denied",
            write(f"{ROOT.parent.parent.as_posix()}/DOCUME~1/{ROOT.name}/.git/config"),
            Expect.DENY,
        ),
        case(
            "a short name of another folder is left to the permission rules",
            write(outside / "PROGRA~1" / "notes.txt"),
            Expect.ALLOW,
        ),
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
            "write data/bars.csv is denied",
            write(ROOT / "data" / "bars.csv"),
            Expect.DENY,
            ".csv",
        ),
        case(
            "write fixtures/synthetic/exports/bars.csv is allowed",
            write(ROOT / "fixtures" / "synthetic" / "exports" / "bars.csv"),
            Expect.ALLOW,
        ),
        case("write backups/store.7z is denied", write(ROOT / "backups" / "store.7z"), Expect.DENY),
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
        case(
            "edit an existing fill scenario asks",
            edit(ROOT / "fixtures" / "scenarios" / "S-fill-012.yaml"),
            Expect.ASK,
            "the specification first",
        ),
        case(
            "write over an existing fill scenario asks",
            write(ROOT / "fixtures" / "scenarios" / "S-fill-001.yaml"),
            Expect.ASK,
        ),
        case(
            "write a new fill scenario is allowed",
            write(ROOT / "fixtures" / "scenarios" / "S-fill-999.yaml"),
            Expect.ALLOW,
        ),
        case(
            "write the fill scenarios' README is allowed",
            write(ROOT / "fixtures" / "scenarios" / "README.md"),
            Expect.ALLOW,
        ),
        case(
            "edit the fill specification asks",
            edit(ROOT / "docs" / "spec" / "fill-semantics.md"),
            Expect.ASK,
            "engine-golden",
        ),
        case(
            "write a new specification beside the fill specification is allowed",
            write(ROOT / "docs" / "spec" / "cost-model.md"),
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
        case(
            "setting INSTA_UPDATE in engine/.cargo/config.toml asks",
            write_text(
                ROOT / "engine" / ".cargo" / "config.toml", '[env]\nINSTA_UPDATE = "always"\n'
            ),
            Expect.ASK,
            "engine-golden",
        ),
        case(
            "adding --snapshot-update to pyproject.toml asks",
            edit_text(ROOT / "pyproject.toml", 'addopts = "--snapshot-update"'),
            Expect.ASK,
        ),
        case(
            "an ordinary pyproject.toml edit is allowed",
            edit_text(ROOT / "pyproject.toml", "line-length = 100"),
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
                "edit an existing fill scenario under a lower-cased project path asks",
                edit(f"{lowered}\\fixtures\\scenarios\\S-fill-012.yaml"),
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
            "git push -u origin step/0.5-x asks, like every push",
            "git push -u origin step/0.5-x",
            Expect.ASK,
            reason="approval",
        ),
        case(
            "git push -u origin HEAD on a step branch asks", "git push -u origin HEAD", Expect.ASK
        ),
        case("git push on a step branch asks", "git push", Expect.ASK),
        case("git push --tags asks", "git push --tags", Expect.ASK),
        case("uv run git push asks", "uv run git push origin HEAD", Expect.ASK, reason="approval"),
        case("git -C <folder> push asks", "git -C engine push origin step/0.5-x", Expect.ASK),
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
        case("git switch main && git push is denied", "git switch main && git push", Expect.DENY),
        case(
            "git switch main && git commit asks", "git switch main && git commit -am x", Expect.ASK
        ),
        case(
            "a push after switching to a new step branch asks",
            "git switch -c step/0.6-ci origin/main && git push -u origin HEAD",
            Expect.ASK,
        ),
        case(
            "uv run bash -c with a force push is denied",
            "uv run bash -c 'git push --force origin main'",
            Expect.DENY,
        ),
        case(
            "bash -o pipefail -c with a force push is denied",
            "bash -o pipefail -c 'git push --force'",
            Expect.DENY,
        ),
        case(
            "find -exec sh -c with a force push is denied",
            "find . -exec sh -c 'git push -f' \\;",
            Expect.DENY,
        ),
        case(
            "$( ) inside an unquoted heredoc is read",
            "cat <<EOF\n$(git push --force)\nEOF",
            Expect.DENY,
        ),
        case(
            "$( ) inside a quoted heredoc is text",
            "cat <<'EOF'\n$(git push --force)\nEOF",
            Expect.ALLOW,
        ),
        case(
            "a <<EOF inside quotes starts no heredoc",
            'echo "a <<EOF"\ngit push --force',
            Expect.DENY,
        ),
        case(
            "a heredoc that writes a .sh file is not run",
            "cat > docs/run.sh <<'EOF'\n# never: git push origin main\ngit push origin main\nEOF",
            Expect.ALLOW,
        ),
        case(
            "a heredoc piped into bash is read",
            "cat <<'EOF' | bash\ngit push --force\nEOF",
            Expect.DENY,
        ),
        case(
            "a comment that mentions git push --force is ignored",
            "echo hi # git push --force",
            Expect.ALLOW,
        ),
        case(
            "a commit message in $(cat <<'EOF') is text",
            "git commit -m \"$(cat <<'EOF'\nNever git push --force.\nEOF\n)\"",
            Expect.ALLOW,
        ),
        case(
            'a PowerShell @" here-string runs its $( )',
            '@"\n$(git push -f)\n"@ | Out-Null',
            Expect.DENY,
            tool="PowerShell",
        ),
        case(
            "writing .claude/settings.json from the shell asks",
            "echo '{}' > .claude/settings.json",
            Expect.ASK,
            reason="guardrails",
        ),
        case(
            "writing the apple-design skill from the shell asks",
            "echo x > .claude/skills/apple-design/SKILL.md",
            Expect.ASK,
            reason="guardrails",
        ),
        case(
            "writing the unslop skill from the shell asks",
            "echo x > .claude/skills/unslop/SKILL.md",
            Expect.ASK,
            reason="guardrails",
        ),
        case(
            "copying over a hook asks", "cp new.mjs .claude/hooks/guard-file-paths.mjs", Expect.ASK
        ),
        case(
            "a generator writing into fixtures/goldens asks",
            "cargo run -p fefat-cli -- golden es --out fixtures/goldens/es",
            Expect.ASK,
            reason="engine-golden",
        ),
        case("reading a golden is allowed", "cat fixtures/goldens/es/run.json", Expect.ALLOW),
        case(
            "sed -i on a fill scenario asks",
            "sed -i 's/4990.25/4990.50/' fixtures/scenarios/S-fill-012.yaml",
            Expect.ASK,
            reason="specification first",
        ),
        case(
            "appending to the fill specification asks",
            "echo x >> docs/spec/fill-semantics.md",
            Expect.ASK,
            reason="specification first",
        ),
        case(
            "copying over a fill scenario asks",
            "cp new.yaml fixtures/scenarios/S-fill-012.yaml",
            Expect.ASK,
        ),
        case(
            "copying into the fill scenarios' folder asks",
            "cp S-fill-012.yaml fixtures/scenarios/",
            Expect.ASK,
        ),
        case(
            "Set-Content on a fill scenario asks in PowerShell",
            "Set-Content fixtures\\scenarios\\S-fill-012.yaml x",
            Expect.ASK,
            tool="PowerShell",
        ),
        case(
            "a script handed a fill scenario's path asks",
            "uv run python edit.py fixtures/scenarios/S-fill-012.yaml",
            Expect.ASK,
        ),
        case(
            "find -delete in the fill scenarios' folder asks",
            "find fixtures/scenarios -name '*.yaml' -delete",
            Expect.ASK,
        ),
        case(
            "git rm of a fill scenario asks",
            "git rm fixtures/scenarios/S-fill-012.yaml",
            Expect.ASK,
        ),
        case(
            "git checkout -- of a fill scenario asks",
            "git checkout -- fixtures/scenarios/S-fill-012.yaml",
            Expect.ASK,
            reason="specification first",
        ),
        case(
            "reading a fill scenario is allowed",
            "cat fixtures/scenarios/S-fill-012.yaml",
            Expect.ALLOW,
        ),
        case(
            "searching the fill scenarios and the specification is allowed",
            "rg -n F-STP-03 fixtures/scenarios docs/spec/fill-semantics.md",
            Expect.ALLOW,
        ),
        case(
            "writing the fill scenarios' README is allowed",
            "echo x >> fixtures/scenarios/README.md",
            Expect.ALLOW,
        ),
        case(
            "running the fill scenario runner is allowed",
            "uv run python -m fefat.reference.scenario_runner --log S-fill-012",
            Expect.ALLOW,
        ),
        case(
            "staging a new fill scenario is allowed",
            "git add fixtures/scenarios/S-fill-042.yaml",
            Expect.ALLOW,
        ),
        case(
            "cargo insta test --unreferenced=delete asks",
            "cargo insta test --unreferenced=delete",
            Expect.ASK,
        ),
        case("setx INSTA_UPDATE asks", "setx INSTA_UPDATE always", Expect.ASK, tool="PowerShell"),
        case("eval with a force push is denied", 'eval "git push --force"', Expect.DENY),
        case(
            "a command held in a variable asks",
            'x="git push -f"; $x',
            Expect.ASK,
            reason="held in a variable",
        ),
        case(
            "a PowerShell script block with a force push is denied",
            "if ($true) {git push -f origin x}",
            Expect.DENY,
            tool="PowerShell",
        ),
        case(
            "Start-Process git with a force push is denied",
            'Start-Process git -ArgumentList "push -f"',
            Expect.DENY,
            tool="PowerShell",
        ),
        case(
            "a push to a branch computed at run time asks why",
            "git push origin $(git branch --show-current)",
            Expect.ASK,
            directory=on_main,
            reason="cannot tell which branch",
        ),
        case("a clobber redirect into .git/config is denied", "echo x >| .git/config", Expect.DENY),
        case("ln -sf into .git/config is denied", "ln -sf x .git/config", Expect.DENY),
        case(
            "install into .claude/settings.json asks", "install x .claude/settings.json", Expect.ASK
        ),
        case(
            "gh --repo before pr merge still asks",
            "gh --repo kenny-g-97/fefat pr merge 12",
            Expect.ASK,
            reason="builder's routine",
        ),
        case(
            "an encoded PowerShell command asks",
            "powershell -EncodedCommand ZwBpAHQAIABzAHQAYQB0AHUAcwA=",
            Expect.ASK,
            tool="PowerShell",
        ),
        case(
            "a cd inside a subshell does not hide a commit on main",
            "(cd ..) && git commit -m x",
            Expect.ASK,
            directory=on_main,
        ),
        case(
            "a cd inside a subshell does not hide a push to main",
            "(cd ..) && git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "a cd inside $( ) does not hide a push to main",
            "echo $(cd ..) && git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "a PowerShell (cd ..) moves the location for the commands after it",
            "(cd ..); git commit -m x",
            Expect.ALLOW,
            tool="PowerShell",
            directory=on_main,
        ),
        case("git config --edit is denied", "git config --edit", Expect.DENY, reason=".git/config"),
        case("git config -e is denied", "git config -e", Expect.DENY),
        case(
            "writing .git//config is denied",
            "echo '[core] hooksPath = x' >> .git//config",
            Expect.DENY,
        ),
        case("writing .git/./config is denied", "echo x > .git/./config", Expect.DENY),
        case(
            "a git subcommand held in a variable asks",
            "sub=push; git $sub --force origin main",
            Expect.ASK,
            reason="held in a variable",
        ),
        case(
            "git checkout . restores files, so a push after it is still on main",
            "git checkout .; git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "git checkout <tree-ish> <path> restores files, so a push after it is still on main",
            "git checkout HEAD README.md && git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "git checkout <branch> still counts as a switch",
            "git checkout step/0.5-x && git push origin HEAD",
            Expect.ASK,
            directory=on_main,
        ),
        case("a push to heads/main is denied", "git push origin HEAD:heads/main", Expect.DENY),
        case("pushing heads/main is denied", "git push origin heads/main", Expect.DENY),
        case("git push --mirr (an abbreviation) is denied", "git push --mirr origin", Expect.DENY),
        case("git push --al (an abbreviation) is denied", "git push --al origin", Expect.DENY),
        case(
            "git -c with an alias that skips the gate asks",
            'git -c alias.ci="commit --no-verify" ci -m x',
            Expect.ASK,
            reason="aliases",
        ),
        case(
            "git -c with an alias that force-pushes asks",
            'git -c alias.fp="push --force" fp origin step/0.5-x',
            Expect.ASK,
            reason="aliases",
        ),
        case(
            "git -c include.path asks",
            "git -c include.path=C:/tmp/x.cfg commit -m x",
            Expect.ASK,
            reason="aliases",
        ),
        case(
            "git -c remote.origin.push asks why",
            "git -c remote.origin.push=HEAD:main push",
            Expect.ASK,
            reason="aliases",
        ),
        case(
            "git --config-env=core.hooksPath is denied",
            "git --config-env=core.hooksPath=HP commit -m x",
            Expect.DENY,
        ),
        case(
            "GIT_CONFIG_COUNT with core.hooksPath is denied",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=x git commit -m x",
            Expect.DENY,
        ),
        case(
            "PowerShell's start alias with a force push is denied",
            "start git 'push --force'",
            Expect.DENY,
            tool="PowerShell",
        ),
        case(
            "writing GIT~1/config (a Windows short name) asks",
            "echo x >> GIT~1/config",
            Expect.ASK,
            reason="short name",
        ),
        case(
            "writing CLAUDE~1/settings.json asks",
            "echo '{}' > CLAUDE~1/settings.json",
            Expect.ASK,
        ),
        case(
            "writing .git.\\config (a trailing dot) asks in PowerShell",
            "Add-Content .git.\\config x",
            Expect.ASK,
            tool="PowerShell",
        ),
        case("git rm of the commit gate asks", "git rm .githooks/pre-commit", Expect.ASK),
        case("git rm of the hooks asks", "git rm -r .claude/hooks", Expect.ASK),
        case(
            "git grep for --no-verify is allowed",
            "git grep -n -e --no-verify",
            Expect.ALLOW,
        ),
        case(
            "an unknown git option with a value does not hide --no-verify",
            "git --shallow-file log commit --no-verify -m x",
            Expect.DENY,
        ),
        case(
            "searching for the word start is allowed",
            "rg -n start fixtures/goldens/es fixtures/goldens/btc",
            Expect.ALLOW,
        ),
        case("rm -rf .claude/ asks", "rm -rf .claude/", Expect.ASK, reason="guardrails"),
        case(
            "Remove-Item .claude\\ asks in PowerShell",
            "Remove-Item -Recurse -Force .claude\\",
            Expect.ASK,
            tool="PowerShell",
        ),
        case(
            "sed -i on a short name of .git asks",
            "sed -i 's/githooks/x/' GIT~1/config",
            Expect.ASK,
            reason="short name",
        ),
        case(
            "a cd inside backticks does not hide a commit on main",
            "echo `cd ..` && git commit -m x",
            Expect.ASK,
            directory=on_main,
        ),
        case(
            "a cd inside backticks does not hide a push to main",
            "echo `cd ..` && git push origin HEAD",
            Expect.DENY,
            directory=on_main,
        ),
        case(
            "removing the .claude folder through a .. asks",
            "rm -rf .claude/hooks/..",
            Expect.ASK,
            reason="guardrails",
        ),
        case(
            "text that ends in a dot is not a Windows path",
            'Set-Content notes.md "Done."',
            Expect.ALLOW,
            tool="PowerShell",
        ),
        case(
            "a sed expression that ends in a dot is not a Windows path",
            "sed -i 's/foo/bar./' README.md",
            Expect.ALLOW,
        ),
        case(
            "find -fprint into fixtures/goldens asks",
            "find . -name '*.json' -fprint fixtures/goldens/es/run.json",
            Expect.ASK,
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
    WEB_SCRATCH.mkdir(parents=True, exist_ok=True)
    web_file = WEB_SCRATCH / "spacing.ts"
    web_file.write_text("const x=1\n", encoding="utf-8")

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
            "a Python file is formatted by ruff",
            after_write(python_file),
            (file_reads(python_file, "x = 1\n"),),
        ),
        case(
            "a Rust file is formatted by rustfmt",
            after_write(rust_file),
            (file_reads(rust_file, "fn main() {}\n"), output_contains("read them again")),
        ),
        case(
            "a web file is formatted by oxfmt",
            after_write(web_file),
            (file_reads(web_file, "const x = 1;\n"), output_contains("read them again")),
        ),
        case(
            "the generated API types are left as openapi-typescript writes them",
            after_write(GENERATED_API_TYPES),
            (
                file_unchanged(GENERATED_API_TYPES, GENERATED_API_TYPES.read_bytes()),
                output_lacks("could not format"),
            ),
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
            (
                output_contains(f"branch {branch}"),
                output_contains_one_of(["Step ", "Next: ", "Continue with /phase-"]),
            ),
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
    allowed += ["git --no-pager log -3", "sort -r notes.txt", "git grep -n hooksPath"]
    allowed += ["rg -n start scripts/"]
    allowed += [
        "just e2e",
        "pnpm --dir web exec playwright test e2e/login.spec.ts --project desktop",
    ]
    denied = [
        "git -c core.pager=less log",
        "GIT_EXTERNAL_DIFF=./x.sh git diff",
        "env FOO=1 git status",
        "git --exec-path=/tmp status",
        "rg --pre ./x.sh pattern",
        "sort -oout.txt notes.txt",
        "git grep -Ovim foo",
        "uv run ruff check --fix-only .",
        "pnpm --dir web lint --fix",
        "uv run pytest --junitxml=out.xml",
        "uv run pyright --createstub requests",
        "git stash",
        "git checkout -- .",
        "echo x > notes.txt",
        "uv run ruff format .",
        "cargo fmt",
        "git branch -D old",
        "find . -name '*.tmp' -delete",
        "uv run ruff check --fix .",
        "bash -c 'git diff'",
        "uv run ruff check -oprobe.txt",
        "pnpm --dir web test --outputFile.json=probe.json",
        "pnpm --dir web test --coverage",
        "pnpm --dir web test --reporter=html",
        "cargo test --config \"target.x86_64-pc-windows-msvc.runner='x'\"",
        "cargo clippy -Zunstable-options",
        "cargo test -- --logfile probe.txt",
        "git grep --open=rm -e foo",
        "uv run ruff check --config 'fix = true' .",
        "uv run pytest --log-file=CLAUDE.md",
        "uv run pytest --debug=CLAUDE.md",
        "uv run pytest -o log_file=probe.txt",
        "node --check --import ./x.mjs y.mjs",
        "sort --ou=out.txt notes.txt",
        "just check strip-notebooks",
        "just test strip-notebooks",
        "git grep -nOrm -e foo",
        "uv run pytest -qolog_file=CLAUDE.md",
        "uv run ruff check -qoCLAUDE.md",
        "just e2e strip-notebooks",
        "pnpm --dir web exec playwright test --update-snapshots",
        "pnpm --dir web exec playwright test -xu",
        "pnpm --dir web exec playwright test --output=src",
        "pnpm --dir web exec playwright test --reporter=./x.mjs",
        "pnpm --dir web exec playwright test -c other.config.ts",
        "pnpm --dir web exec playwright codegen",
    ]

    def reviewer_bash(command: str) -> str:
        return in_subagent(bash(command, ROOT), "step-reviewer")

    cases = [
        Case(
            f"a reviewer may run: {command}",
            Hook.REVIEWER_SHELL,
            reviewer_bash(command),
            Expect.ALLOW,
        )
        for command in allowed
    ]
    cases += [
        Case(
            f"a reviewer may not run: {command}",
            Hook.REVIEWER_SHELL,
            reviewer_bash(command),
            Expect.DENY,
        )
        for command in denied
    ]
    cases.append(
        Case(
            "a reviewer may not run: Remove-Item notes.txt (PowerShell)",
            Hook.REVIEWER_SHELL,
            in_subagent(powershell("Remove-Item notes.txt", ROOT), "step-reviewer"),
            Expect.DENY,
            reason_contains="read-only",
        )
    )
    cases += [
        Case(
            f"{reviewer} may not write the probe file",
            Hook.REVIEWER_SHELL,
            in_subagent(bash("printf probe > reviewer-probe.txt", ROOT), reviewer),
            Expect.DENY,
            reason_contains="read-only",
        )
        for reviewer in sorted(agent_name(path) for path in AGENTS.glob("*.md"))
    ]
    cases += [
        Case(
            "a reviewer whose name carries a prefix is still a reviewer",
            Hook.REVIEWER_SHELL,
            in_subagent(bash("printf probe > reviewer-probe.txt", ROOT), "project:step-reviewer"),
            Expect.DENY,
        ),
        Case(
            "the main session's writes are left to the other guards",
            Hook.REVIEWER_SHELL,
            bash("echo x > notes.txt", ROOT),
            Expect.ALLOW,
        ),
        Case(
            "another subagent's writes are left to the other guards",
            Hook.REVIEWER_SHELL,
            in_subagent(bash("echo x > notes.txt", ROOT), "general-purpose"),
            Expect.ALLOW,
        ),
    ]
    return cases


def all_cases(repositories: Repositories, branch: str) -> list[Case]:
    return [
        *file_guard_cases(),
        *shell_guard_cases(repositories),
        *formatter_cases(),
        *session_cases(repositories, branch),
        *reviewer_cases(),
    ]


def run_hook(case: Case, node: str, hooks: Path) -> Outcome:
    environment = {**os.environ, "CLAUDE_PROJECT_DIR": str(case.directory)}
    completed = subprocess.run(
        [node, str(hooks / case.hook.value)],
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
    for scratch in (SCRATCH, WEB_SCRATCH):
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            scratch.parent.rmdir()
        except OSError:
            continue


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke tests for the Claude Code hooks.")
    parser.add_argument(
        "-k", dest="keyword", default="", help="run the cases whose name contains this text"
    )
    parser.add_argument("--verbose", action="store_true", help="print what each hook printed")
    parser.add_argument(
        "--hooks",
        type=Path,
        default=HOOKS,
        help="the hooks folder to test (default: .claude/hooks)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    node = shutil.which("node")
    git = shutil.which("git")
    if node is None or git is None:
        print(f"Expected node and git on PATH, got node={node!r} and git={git!r}.", file=sys.stderr)
        return 1
    hooks = arguments.hooks.resolve()
    if not (hooks / Hook.SHELL_GUARD.value).exists():
        print(
            f"Expected the hook scripts in {hooks}, got no {Hook.SHELL_GUARD.value}.",
            file=sys.stderr,
        )
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
                outcomes = list(pool.map(lambda case: run_hook(case, node, hooks), cases))
            results = [
                Result(case, outcome, failure_of(case, outcome))
                for case, outcome in zip(cases, outcomes, strict=True)
            ]
    finally:
        remove_scratch()
    return report(results, arguments.verbose)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
