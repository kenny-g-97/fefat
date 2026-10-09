---
name: verify
description: Run the checks that match the files changed on this branch (Rust, Python, web, masterplan docs, Claude Code hooks) and report pass or fail per check with trimmed output. With --full, the complete suite (just check and just test) before a pull request.
when_to_use: Before each commit of code, before opening a pull request (with --full), after fixing a failing check, and when a Done-means item needs check output as evidence. Steps that change web/ also follow ui-recipe.md from step 4.3 on.
argument-hint: "[--full]"
---

# verify — run the checks for what changed

Arguments: `$ARGUMENTS`

## Which checks

With `--full`, run `just check` (which includes the masterplan checker) and then `just test`, and go to the report.

Otherwise collect the changed files, from `git status --porcelain` (staged, unstaged, and untracked) and `git diff --name-only origin/main...HEAD`, and run every row whose paths match, in this order:

| Changed | Run |
| --- | --- |
| `engine/**` | `cargo fmt --manifest-path engine/Cargo.toml --all --check`; `cargo clippy --manifest-path engine/Cargo.toml --workspace --all-targets --all-features -- -D warnings`; `cargo test --manifest-path engine/Cargo.toml --workspace` |
| `python/**`, `scripts/**`, `pyproject.toml`, `uv.lock` | `uv run ruff check .`; `uv run ruff format --check .`; `uv run pyright`; `uv run lint-imports`; `uv run pytest` |
| `web/**` | `pnpm --dir web lint`; `pnpm --dir web typecheck`; `pnpm --dir web test` |
| `.claude/hooks/**`, `.claude/settings.json`, `scripts/test_hooks.py` | `node --check` on each changed `.mjs` file; `uv run python scripts/test_hooks.py` |
| `docs/masterplan/**` | `uv run python docs/masterplan/tools/check_masterplan.py` |
| `justfile`, `.githooks/**`, or more than two of the areas above | `just check` and `just test` |

When nothing matches (for example, only Markdown outside the masterplan changed), say so: there is nothing to run.

## Report

A table with each check and its result. For a failure, add the last 30 lines of its output. End with one line: "All checks passed" or "N checks failed". A failure stops the commit or the pull request until it is fixed. Never skip a check, weaken a test, or commit with `--no-verify` to get past one.

## UI steps

From step 4.3 on, a step that changes `web/` also follows [ui-recipe.md](ui-recipe.md) before its pull request.
