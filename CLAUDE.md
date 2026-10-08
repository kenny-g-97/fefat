# FEFAT — working agreements (bootstrap)

This is the bootstrap version. Masterplan step 0.4 replaces it with the full file and keeps the facts below.

## What this repository is

FEFAT ("feature engineering for algorithmic trading") is a local-first research platform for futures and crypto traders: feature lab, Rust backtesting engine with strict versioning, prop-firm simulator, in-app Claude agent, phone access. The build follows the masterplan in `docs/masterplan/` — start at `docs/masterplan/README.md`; the build process is in `docs/masterplan/05-build-process.md`.

## How work happens

- One masterplan step per session. Each step's prompt is in `docs/masterplan/phases/P*.md`; status is in `docs/masterplan/PROGRESS.md`.
- Steps 0.1–0.3 may commit to `main`. From step 0.4 on, every step works on a branch `step/N.M-<slug>` and ends with a pull request; never commit to `main` after that.
- Stay inside the current step. Note anything else in `docs/masterplan/BACKLOG.md` instead of doing it.
- If a step's assumption no longer holds, stop and propose an amendment rather than deviating silently.

## This machine

- Native Windows 11 (no WSL for this project). PowerShell and Git Bash are both available.
- Bare `python` and `python3` are Microsoft Store stubs here: always run Python through `uv run python` (or `python3.12`).
- Line endings are LF everywhere (`.gitattributes`, `.editorconfig`); use `pathlib` for paths.
- The builder knows Python and notebooks well and is new to web, mobile, and DevOps: explain those parts plainly and prefer checks they can run or click over code they must read.

## Never

- Commit, attach, or paste licensed market data. Real data lives outside the repository under `FEFAT_DATA_DIR`; only generated fixtures under `fixtures/synthetic/` are committed.
- Commit secrets (`.env*`, API keys, certificates). Keys go in the operating system's credential store.
- Weaken, skip, or delete a test to make it pass, or change a scenario's expected value to match the code.
