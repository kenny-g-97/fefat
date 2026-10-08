# FEFAT task runner: the same recipes on Windows, CI, and macOS.
# Windows runs recipe lines in cmd.exe (Git's sh is not on PowerShell's PATH;
# a failing command fails the recipe with its real exit code), everything else
# runs them in sh. Keep recipe lines plain commands: no &&, pipes, or env
# prefixes. Python always runs through uv; bare `python` is a Store stub here.

set windows-shell := ["cmd.exe", "/c"]

# List the recipes
default:
    @just --list --unsorted

# Report the tools FEFAT needs, each as OK, OLD, or MISSING
doctor:
    uv run --no-project python scripts/doctor.py

# Install every dependency: the uv workspace, the Cargo workspace, the web app
setup:
    uv sync --all-packages
    cargo fetch --manifest-path engine/Cargo.toml
    pnpm --dir web install --frozen-lockfile

# Lint, format-check, and type-check Python, Rust, and TypeScript
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright
    uv run lint-imports
    cargo fmt --manifest-path engine/Cargo.toml --all --check
    cargo clippy --manifest-path engine/Cargo.toml --workspace --all-targets --all-features -- -D warnings
    pnpm --dir web lint
    pnpm --dir web typecheck

# Run every test suite: pytest, cargo test, vitest
test:
    uv run pytest
    cargo test --manifest-path engine/Cargo.toml --workspace
    pnpm --dir web test

# Start the local server and the web dev server (arrives with Phase 4, step 4.3)
dev:
    uv run python -c "print('just dev arrives with the local app in Phase 4 (step 4.3); nothing to start yet')"
