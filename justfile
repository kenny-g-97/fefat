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

# Point git at the commit gate (a clone copies no git settings), install every dependency (the uv workspace, the Cargo workspace, the web app), and build the engine
setup:
    git config core.hooksPath .githooks
    uv sync --locked --all-packages
    just setup-engine
    just build-engine
    pnpm --dir web install --frozen-lockfile

# Fetch the Cargo workspace's crates
[working-directory("engine")]
setup-engine:
    cargo fetch --locked

# Compile the engine (release) and install fefat_engine into the workspace environment, where `import fefat` finds it; build fefat-cli, which the differential tests run
[working-directory("engine")]
build-engine:
    uv run maturin develop --release --uv --manifest-path crates/fefat-py/Cargo.toml
    cargo build --release -p fefat-cli

# Run the data guard; lint, format-check, and type-check Python, Rust, and TypeScript; check the masterplan's shape
check:
    uv run --no-project python scripts/guard_data.py
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright
    uv run lint-imports
    just check-engine
    pnpm --dir web lint
    pnpm --dir web run format --check
    pnpm --dir web typecheck
    uv run --no-project python scripts/check_web_imports.py
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

# Write the StrategySpec JSON schema from the Rust types into the SDK, where a cargo test checks it is current
[working-directory("engine")]
gen-schema:
    cargo run -p fefat-cli -- schema ../python/fefat/src/fefat/strategy/strategy_spec.schema.json

# Write the API's OpenAPI document to web/openapi.json and the web app's types from it to web/src/api/schema.d.ts (step 4.2); a pytest and CI fail while the committed files differ
gen-api:
    uv run python -m fefat_app.http.openapi_document web/openapi.json
    pnpm --dir web exec openapi-typescript openapi.json --output src/api/schema.d.ts

# Start the local server on 127.0.0.1 at the port of FEFAT_HOME/config.toml (step 4.2): the API, its docs at /docs after login, and web/dist when built; it asks for a password on its first run
up:
    uv run fefat up

# Rewrite the goldens under fixtures/goldens/ from the engine's output: only with the builder's approval, after the version bump, and with a changelog entry (the engine-golden skill)
[working-directory("engine")]
regenerate-goldens: build-engine
    cargo run -p fefat-cli -- determinism 20260308 --write ../fixtures/goldens/determinism/MANIFEST.json
    uv run python ../scripts/golden_backtest.py --write ../fixtures/goldens/backtest/MANIFEST.json

# Cross-check the engine against NautilusTrader, and NinjaTrader 8's exported trades when present, on MES in August 2026 (step 2.14): slow, needs the real store, runs the other engine in python/tests/external's own environment, and writes docs/validation/nautilus-comparison.md
xcheck:
    uv run python scripts/xcheck.py

# Run the cross-check's own tests and type check in python/tests/external's environment (step 2.14), which `just test` leaves out since it installs NautilusTrader's 113 MB wheel; CI runs it when that project changes
xcheck-tests:
    uv run --directory python/tests/external pytest
    uv run --directory python/tests/external pyright

# Check the tick engine on the store's IBKR sessions of MNQZ2026 (step 2.16): the bars rebuilt from the prints, the reference engine against the Rust engine, every tick-versus-minute difference classed, and the hashes; needs your data, says so without it, and writes docs/validation/ibkr-tick-check.md
tick-check:
    uv run python scripts/tick_check.py

# Benchmark the engine on the generated year of step 2.7, built under FEFAT_HOME when missing (step 2.15): a run with trade paths, one without, a batch of 1,000; --baseline <file> warns above a 30 % regression
bench *ARGS:
    uv run python scripts/bench.py {{ARGS}}

# Mutation-test fefat-engine with cargo-mutants for the phase exits (step 2.15): each mutant its tests miss is listed in engine/mutants.out/; -f <file> tests one file, --list counts the mutants
[working-directory("engine")]
mutants *ARGS:
    cargo mutants --package fefat-engine {{ARGS}}

# Clear every notebook's outputs (they can hold licensed data); then `git add` the notebooks again
strip-notebooks:
    uv run python scripts/strip_notebooks.py

# Start the local server and the web dev server (arrives with Phase 4, step 4.3)
dev:
    uv run python -c "print('just dev arrives with the local app in Phase 4 (step 4.3); nothing to start yet')"
