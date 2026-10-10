# FEFAT task runner: the same recipes on Windows, CI, and macOS.
# Windows runs recipe lines in cmd.exe (Git's sh is not on PowerShell's PATH;
# a failing command fails the recipe with its real exit code), everything else
# runs them in sh. Keep recipe lines plain commands: no &&, pipes, or env
# prefixes. Python always runs through uv; bare `python` is a Store stub here.
# Cargo runs in engine/ (the *-engine recipes): rustup applies
# engine/rust-toolchain.toml only inside that folder.

set windows-shell := ["cmd.exe", "/c"]

# Python writes UTF-8 wherever its output goes: import-linter's box-drawing
# characters fail in cp1252 when Windows output goes to NUL.
export PYTHONUTF8 := "1"

# List the recipes
default:
    @just --list --unsorted

# Report the tools FEFAT needs, each as OK, OLD, or MISSING
doctor:
    uv run --no-project python scripts/doctor.py

# Install every dependency (the uv workspace, the Cargo workspace, the web app) and build the engine
setup:
    uv sync --locked --all-packages
    just setup-engine
    just build-engine
    pnpm --dir web install --frozen-lockfile

# Fetch the Cargo workspace's crates
[working-directory("engine")]
setup-engine:
    cargo fetch --locked

# Compile the engine (release) and install fefat_engine into the workspace environment, where `import fefat` finds it
[working-directory("engine")]
build-engine:
    uv run maturin develop --release --uv --manifest-path crates/fefat-py/Cargo.toml

# Run the data guard; lint, format-check, and type-check Python, Rust, and TypeScript; check the masterplan's shape
check:
    uv run --no-project python scripts/guard_data.py
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright
    uv run lint-imports
    just check-engine
    pnpm --dir web lint
    pnpm --dir web typecheck
    uv run python docs/masterplan/tools/check_masterplan.py

# Format-check and lint the Cargo workspace
[working-directory("engine")]
check-engine:
    cargo fmt --all --check
    cargo clippy --workspace --all-targets --all-features -- -D warnings

# Build the engine, then run every test suite: pytest, the Claude Code hook smoke tests, cargo test, vitest
test:
    just build-engine
    uv run pytest
    uv run python scripts/test_hooks.py
    just test-engine
    pnpm --dir web test

# Run the Cargo workspace's tests
[working-directory("engine")]
test-engine:
    cargo test --workspace

# Clear every notebook's outputs (they can hold licensed data); then `git add` the notebooks again
strip-notebooks:
    uv run python scripts/strip_notebooks.py

# Start the local server and the web dev server (arrives with Phase 4, step 4.3)
dev:
    uv run python -c "print('just dev arrives with the local app in Phase 4 (step 4.3); nothing to start yet')"
