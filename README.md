# fefat

Feature and strategy building for algorithmic trading.

FEFAT ("feature engineering for algorithmic trading") is a local-first research platform for futures and crypto traders. It runs on your own PC and is used from the browser and the phone: a feature lab and strategy workspace with a Claude agent, a backtester with its own Rust engine and strict strategy versioning, and a prop-firm account simulator.

## Status

Planning is complete and the build has not started. It follows the masterplan in [docs/masterplan](docs/masterplan/README.md): one step per Claude Code session and one pull request per step, starting with step 0.1 in [Phase 0](docs/masterplan/phases/P00-foundations.md). Progress is tracked in [PROGRESS.md](docs/masterplan/PROGRESS.md).

The original idea is in [raw_app_idea.txt](raw_app_idea.txt).

## Data policy

Licensed market data never enters this repository. Real data lives outside it, under `FEFAT_DATA_DIR`; only generated test fixtures are committed.
