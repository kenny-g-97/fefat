# fefat

[![CI](https://github.com/kenny-g-97/fefat/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kenny-g-97/fefat/actions/workflows/ci.yml)

Feature and strategy building for algorithmic trading.

FEFAT ("feature engineering for algorithmic trading") is a local-first research platform for futures and crypto traders. It runs on your own PC and is used from the browser and the phone: a feature lab and strategy workspace with a Claude agent, a backtester with its own Rust engine and strict strategy versioning, and a prop-firm simulator that tests saved backtests against prop rules and a prop strategy. FEFAT provides market data for a curated set of products, and traders can import their own data for anything else.

## Status

The build is in Phase 0 (foundations). It follows the masterplan in [docs/masterplan](docs/masterplan/README.md): one step per Claude Code session and one pull request per step, starting from [Phase 0](docs/masterplan/phases/P00-foundations.md). Progress is tracked in [PROGRESS.md](docs/masterplan/PROGRESS.md), and the decisions behind the design are recorded in [docs/adr](docs/adr/), one record per decision marked ADR in the [decision log](docs/masterplan/DECISIONS.md).

The original idea is in [raw_app_idea.txt](raw_app_idea.txt).

## Getting started

Install the tools listed in [docs/masterplan/07-tools-and-costs.md](docs/masterplan/07-tools-and-costs.md) §1 (git, GitHub CLI, Node 24, pnpm, uv, Rust via rustup, `just`, and the Microsoft C++ Build Tools), then from the repository root:

```text
just doctor   # each tool reported as OK, OLD, or MISSING
just setup    # uv workspace, Cargo workspace, web app dependencies
just check    # data guard; lint, format and type checks for Python, Rust, TypeScript; masterplan shape
just test     # pytest, the Claude Code hook smoke tests, cargo test, vitest
```

Once per clone, also run `git config core.hooksPath .githooks`. A clone copies no git settings, so without it the pre-commit guard, which refuses market data, secrets, and notebook outputs, never runs.

On this project, Python always runs through `uv run python` (a bare `python` is a Microsoft Store stub on Windows).

Changes reach `main` through pull requests, squash-merged with the routine in [docs/masterplan/05-build-process.md](docs/masterplan/05-build-process.md#merging-a-pull-request) §8.

## Repository layout

- `engine/`: the Rust engine, a Cargo workspace of seven crates; Python imports it as `fefat_engine`.
- `python/fefat/`: the SDK (`import fefat as ff`).
- `python/fefat_app/`: the local server.
- `python/tests/`: the tests of both Python packages.
- `web/`: the web app (Vite, React, TypeScript).
- `fixtures/synthetic/`: generated market data for the tests, the only data files in git.
- `scripts/`: the project scripts, in Python.
- `docs/masterplan/`: the build plan, with its progress table, backlog, and decision log.
- `docs/adr/`: the architecture decision records.
- `.claude/`, `.githooks/`, `.github/`: Claude Code's configuration, the pre-commit hook, and the CI workflow with the pull request template.

The full tree, including the folders later steps add, and the rule that dependencies point inward are in [docs/masterplan/01-architecture.md](docs/masterplan/01-architecture.md#3-repository-layout) §3.

## Data policy

Licensed market data never enters this repository. Real data lives outside it, under `FEFAT_DATA_DIR`; only generated test fixtures are committed.
