# Progress

The single status table for the masterplan. Claude Code's `/step` runner updates the step's row when it opens the PR; you update it if you merge by hand. Statuses: `todo`, `in progress`, `pr open`, `done`, `skipped` (with a note), `amended` (see the phase file).

Phase kickoffs and exits are tracked in the second table.

## Preparation

- 2026-10-08 — The private repository [kenny-g-97/fefat](https://github.com/kenny-g-97/fefat) was cloned into this folder, and a preparation commit on `main` added the masterplan, line-ending and ignore rules, editor settings, a bootstrap `CLAUDE.md`, and a short README. Steps 0.2–0.5 were amended to match (see their Amendment sections). Next: step 0.1.

## Plan revisions

- 2026-10-08 — FEFAT provides market data for a curated set of products, and traders can also import their own (D-24); a prop simulation takes prop rules, a prop strategy, and an existing backtest file, and never re-runs the strategy (D-25), so every run stores trade paths (D-26). New steps 1.9, 1.10, 2.13, 5.12, 14.6, and 14.7; steps 7.3 and 7.5 rewritten, and the other prop steps updated; the later steps in Phases 1, 2, 5, and 14 renumbered, before any step had started. 128 → 134 steps.
- 2026-10-09 — The design skills installed under `.claude/skills/` (`designing-architecture`, `software-design-principles`, `backtest-expert`) and the `frontend-design` plugin were applied to the plan before step 0.2 (D-27, D-28, D-29; `08-code-design.md`): a modular monolith with ports and adapters and its dependency rule, src-layout paths and the renames `fefat.market`, `fefat.indicators`, `fefat.reference`, `fefat_app.http`, `services/`, `database/`, `executor.py`, `credentials.py`, web `areas/`; the `MarketDataReader` trait in `fefat-core` (steps 2.4–2.6); the robustness summary in 2.11; the design brief at the Phase 4 kickoff and `web/DESIGN.md` in 4.3; and the skill-loading rule for every step. No step IDs changed; only unstarted steps were edited.
- 2026-10-09 — GitHub's free plan has no branch protection or rulesets for private repositories, and you chose to stay on it (D-30): steps 0.3 and 0.6 amended, and the merge routine written into `05-build-process.md` §8.
- 2026-10-10 — The `apple-design` skill became the lens of a new read-only `design-reviewer` subagent, which reviews every step that changes `web/` from step 4.3 on and the main pages at the exits of UI phases (D-34). No step changed; the Phase 4 kickoff adds the reviewer to the meta lines of the UI steps.
- 2026-10-11 — The Phase 0 exit moved the SDK to Polars 2.0.0 before Phase 1 writes on it (D-36), registered the reviewers' read-only guard in the settings (an Amendment under step 0.4), gave the phase exit the upgrade step of `05-build-process.md` §7, and wrote the phase's retro into `CLAUDE.md`, the `step` skill, and 05 §2 (steps started in plain words, plan mode for every step). No unstarted step changed.
- 2026-10-12 — FEFAT ships no market data: traders connect their own data sources, and FEFAT provides the product catalog, a guide to well-known sources, the connectors and presets, and sync (D-37, ADR-0018, superseding the data delivery of D-24). Steps 1.9, 5.1, 5.3, 5.4, 5.6, 14.6, 14.7, 14.8, and 14.9 amended (1.9, 14.6, and 14.7 renamed) and 1.4, 1.6, 1.10, 1.11, 4.1, 5.13, and 14.5 reworded, before any Phase 1 step started; `00`, `01`, `02` §1.8, `05` §8, `07`, `08`, both READMEs, and the milestones updated. No step ID changed.
- 2026-10-12 — Phase 1 kickoff (D-38, pull request #10): no connector and no sync in Phase 1, since the data layer takes only the files you feed it: step 1.4 skipped, 1.6 reduced to a file importer (no download, no key), 1.9 reduced to the catalog, the source guide, and `fefat data status`, and the credential store deferred to the first step that needs a key; the catalog is MES, MNQ, MCL, and MGC, the products on this PC (`docs/data-inventory.md`); the presets are Databento CSV, IBKR, NinjaTrader, and TradingView first; the other Phase 1 steps were reconciled with the Phase 0 code, the fixtures, and the exit reviews (an Amendment under each step); the source research is `appendix/research-data-sources.md`. No step ID changed.

## Steps

| Step | Title | Phase | Status | PR | Date | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 0.1 | Install the toolchain and write the doctor script | P0 | done | main | 2026-10-09 | Installs verified 2026-10-08; `scripts/doctor.py` and the `justfile` committed straight to `main`; 07 §1 commands amended |
| 0.2 | Scaffold the repository | P0 | done | main | 2026-10-09 | Amended 2026-10-08 and 2026-10-09; uv workspace (src layout), Cargo workspace (7 crates), Vite app (oxlint); `just setup`, `check`, `test` green on Windows |
| 0.3 | Configure the GitHub repository for pull requests | P0 | done | #1 | 2026-10-09 | Amended 2026-10-08 and 2026-10-09 (free plan, D-30); squash-only merging, branches deleted after merge; PR template and pre-commit placeholder committed to `main`; this test PR merged with the routine in 05 §8 |
| 0.4 | Configure Claude Code for this repository | P0 | done | #2 | 2026-10-09 | Amended 2026-10-08 and 2026-10-09; CLAUDE.md, five rules, five skills, three read-only reviewers, five hooks with 173 smoke tests, language-server plugins; seven differences from 06 §8 recorded there |
| 0.5 | Data policy, synthetic fixtures, commit guard | P0 | done | #3 | 2026-10-09 | Amended 2026-10-08 and 2026-10-09; synthetic fixtures (three ES sessions across the DST change, a BTC day, 1-second and 1-minute bars, 6.9 MB) with a hashed manifest; commit guard in the pre-commit hook and `just check`; `just strip-notebooks`; `fefat.config`; the ponytail review joins the code reviewers (D-32) |
| 0.6 | CI on Windows and Linux | P0 | done | #4 | 2026-10-09 | Amended 2026-10-09: no required check on the free plan; one check per system (Windows, Ubuntu) runs `just setup`, `check`, and `test`, then builds, installs, and imports a debug `fefat_engine` wheel; cargo runs in `engine/` so the toolchain pin applies; locked setup; `PYTHONUTF8`; pyo3, maturin, and commit-pinned actions (D-33) |
| 0.7 | Seed the decision records, progress, and backlog | P0 | done | #5 | 2026-10-10 | 17 decision records and a template in `docs/adr/` (D-02, and the exact mode of D-13, superseded); the PROGRESS table already listed every step; README layout and the `core.hooksPath` line; the backlog's code items for 0.7 moved to the Phase 0 exit |
| 0.8 | Hello-world slice: Rust to Python to a notebook | P0 | done | #7 | 2026-10-10 | `max_drawdown` in `fefat-core` with proptest; `fefat_engine` takes a list or an int64 Arrow array, read in place (buffer-address tests for PyArrow, chunked arrays, and Polars); `fefat.engine_info` and `fefat.stats`; `just build-engine`, which `just setup` and `just test` run; the hello notebook; Polars held below 2; D-35 |
| 1.1 | Canonical schemas, units, partitions, manifests, snapshot hashes | P1 | done | #11 | 2026-10-12 | Polars schemas, no pyarrow in the SDK (D-39); ADR-0019 (D-40); `fefat.market` split into schema, layout, snapshot, raw_manifest, and store; reads keep a request's bars, and runs read through snapshots that hash the request and its files; fixtures regenerated with `trade_date` and `dataset.json`; follow-ups for 1.3, 1.5 to 1.8, and Phase 4 in the backlog |
| 1.2 | Instruments, contract identity, fee tables | P1 | done | #12 | 2026-10-13 | `fefat.market.instruments`, `contracts`, and `fees`, exposed as `ff.instruments` and `ff.fees`; a contract's identity comes from definitions, else the imported files' symbology, else the static table, and records which; `prop-topstep` replaces empty prop placeholders, `retail-default` is priced as NinjaTrader's free plan, and the tables start in 2026; follow-ups for 1.3, 1.6, 1.10, 2.9, 2.10, 7.1, and 7.2 in the backlog |
| 1.3 | Session calendar and trade date | P1 | done | #13 | 2026-10-13 | `fefat.market.calendar`, `builtin_calendars`, and `calendar_check`; CME's holiday rules in code with sourced overrides instead of exchange-calendars, and Polars for time zones (D-41); the real-data run of `validate_calendar` moves to the end of 1.6; the fixtures close at the local close and are labelled `ESH2026` and `BTCUSDT-PERP`; halt windows go to 1.5; follow-ups for 1.5, 1.6, 1.8, 1.10, 14.7, and the Phase 2 kickoff in the backlog |
| 1.4 | Crypto importer | P1 | skipped | | 2026-10-12 | No connector in Phase 1 (D-38): the Binance archive layout becomes an import preset when crypto files arrive |
| 1.5 | Bar builder | P1 | todo | | | |
| 1.6 | Databento file importer | P1 | done | #14 | 2026-10-14 | DBN files only, CSV and Parquet exports left for 1.10; `databento-dbn` 0.72.0 (D-42); `fefat.market.importers` and the `fefat` command; contracts named by their records, since Databento's symbology runs past expiry; your files imported (MNQ 34, MES 34, MCL 84, MGC 106 contracts); the real bars fixed the calendars: a 16:15 close before 2015-09-21, the July 3 rule, three Thanksgiving rows; `calendar_definition` split from `calendar` |
| 1.7 | Rolls and forward-anchored continuous series | P1 | todo | | | |
| 1.8 | Data-quality report and SDK data API | P1 | todo | | | |
| 1.9 | Product catalog, source guide, and data status | P1 | todo | | | Renamed at the Phase 1 kickoff (D-38): no connect, no sync |
| 1.10 | Import your own market data | P1 | todo | | | |
| 1.11 | Notebook demo and phase exit prep | P1 | todo | | | |
| 2.1 | Fill specification and scenario format | P2 | todo | | | |
| 2.2 | Python reference engine and the first notebook backtest | P2 | todo | | | |
| 2.3 | Strategy spec and signal-frame contract | P2 | todo | | | |
| 2.4 | Rust core types and determinism harness | P2 | todo | | | |
| 2.5 | Memory-mapped data cache | P2 | todo | | | |
| 2.6 | Rust engine on ticks with differential tests | P2 | todo | | | |
| 2.7 | Bar-fidelity fills and hierarchical skipping | P2 | todo | | | |
| 2.8 | Full exit plan, filters, sizing | P2 | todo | | | |
| 2.9 | Costs, funding, positions across rolls | P2 | todo | | | |
| 2.10 | Python bindings, `ff.backtest`, run artifacts, run hash | P2 | todo | | | |
| 2.11 | Metrics and `run.explain` | P2 | todo | | | |
| 2.12 | Mixed fidelity and `fidelity_check` | P2 | todo | | | |
| 2.13 | Trade paths: every run is ready for prop simulation | P2 | todo | | | |
| 2.14 | Cross-check against NautilusTrader | P2 | todo | | | |
| 2.15 | Benchmarks and tutorial | P2 | todo | | | |
| 3.1 | Feature contract and versions | P3 | todo | | | |
| 3.2 | Runtime, dependencies, multi-timeframe and cross-instrument inputs | P3 | todo | | | |
| 3.3 | Cache | P3 | todo | | | |
| 3.4 | Leak detector | P3 | todo | | | |
| 3.5 | Indicators, batch 1 | P3 | todo | | | |
| 3.6 | Indicators, batch 2 and session-aware features | P3 | todo | | | |
| 3.7 | Combinators and features inside signal strategies | P3 | todo | | | |
| 3.8 | Feature analytics and notebook demo | P3 | todo | | | |
| 4.1 | App-state database, workspace folders, settings | P4 | todo | | | |
| 4.2 | Local server, login, typed client generation | P4 | todo | | | |
| 4.3 | Web shell, login, phone navigation, UI test harness | P4 | todo | | | |
| 4.4 | Jobs: local process pool, resumable progress streams, cancel | P4 | todo | | | |
| 4.5 | Executor: subprocess isolation and limits for user code | P4 | todo | | | |
| 4.6 | Phone access over Tailscale, installable app, smoke test from the phone | P4 | todo | | | |
| 5.1 | Schema and data catalog from the data folder | P5 | todo | | | |
| 5.2 | Strategy versions API | P5 | todo | | | |
| 5.3 | Backtest job | P5 | todo | | | |
| 5.4 | Data catalog page and chart viewer | P5 | todo | | | |
| 5.5 | Strategy page | P5 | todo | | | |
| 5.6 | Run launch and run list | P5 | todo | | | |
| 5.7 | Results: metrics, equity, distributions | P5 | todo | | | |
| 5.8 | Trade table | P5 | todo | | | |
| 5.9 | Trade review chart | P5 | todo | | | |
| 5.10 | Run comparison, version diff, reproduce-run check | P5 | todo | | | |
| 5.11 | Notifications on completion | P5 | todo | | | |
| 5.12 | Import wizard for your own market data | P5 | todo | | | |
| 5.13 | Phone pass, end-to-end suite, demo | P5 | todo | | | |
| 6.1 | Feature library pages | P6 | todo | | | |
| 6.2 | Editor and preview run | P6 | todo | | | |
| 6.3 | Preview chart and statistics panel | P6 | todo | | | |
| 6.4 | Leak results in the app | P6 | todo | | | |
| 6.5 | Feature analytics page | P6 | todo | | | |
| 6.6 | Combination builder | P6 | todo | | | |
| 6.7 | Rule builder | P6 | todo | | | |
| 6.8 | Execution-template form and code generation | P6 | todo | | | |
| 6.9 | Builder-to-backtest end to end | P6 | todo | | | |
| 7.1 | Rule schema, preset format, refresh skill | P7 | todo | | | |
| 7.2 | Account state machine, reference implementation, first three presets | P7 | todo | | | |
| 7.3 | Backtest-file replay: drawdowns, daily loss, flat-by, limits | P7 | todo | | | |
| 7.4 | Payouts, consistency, scaling, lifecycle, fees | P7 | todo | | | |
| 7.5 | Imported trade logs and path enrichment | P7 | todo | | | |
| 7.6 | Prop strategy layer and cash ledger | P7 | todo | | | |
| 7.7 | Monte Carlo | P7 | todo | | | |
| 7.8 | SDK polish, notebook, plan ranking | P7 | todo | | | |
| 7.9 | Rule-set and prop-strategy pages | P7 | todo | | | |
| 7.10 | Backtest files, simulation launch, results pages | P7 | todo | | | |
| 7.11 | More presets, end to end | P7 | todo | | | |
| 8.1 | Runtime spike: tool loop, streaming, append-only transcript, caching, compaction | P8 | todo | | | |
| 8.2 | Sessions, API key storage, usage ledger, budgets, settings page | P8 | todo | | | |
| 8.3 | Tool registry and read tools | P8 | todo | | | |
| 8.4 | Chat with resumable streaming | P8 | todo | | | |
| 8.5 | Proposal model and audit log | P8 | todo | | | |
| 8.6 | Write tools and proposal review UI | P8 | todo | | | |
| 8.7 | Execution tools with cost confirmation | P8 | todo | | | |
| 8.8 | Skills pack | P8 | todo | | | |
| 8.9 | Evaluation suite | P8 | todo | | | |
| 8.10 | Consent-bypass and injection tests | P8 | todo | | | |
| 8.11 | End to end | P8 | todo | | | |
| 9.1 | The `on_bar` bridge | P9 | todo | | | |
| 9.2 | Order API and parity tests | P9 | todo | | | |
| 9.3 | Reference engine support | P9 | todo | | | |
| 9.4 | Sandboxed execution and process-pool sweeps | P9 | todo | | | |
| 9.5 | Code editor page for event strategies | P9 | todo | | | |
| 9.6 | Agent support and performance tests | P9 | todo | | | |
| 10.1 | Uploads and the dataset model | P10 | todo | | | |
| 10.2 | Ingestion recipes | P10 | todo | | | |
| 10.3 | Publication-time joins and datasets as feature inputs | P10 | todo | | | |
| 10.4 | Import from URL | P10 | todo | | | |
| 10.5 | Agent ingestion flow | P10 | todo | | | |
| 10.6 | Pages | P10 | todo | | | |
| 10.7 | Hostile-file tests | P10 | todo | | | |
| 11.1 | Batch runs and sweep artifacts | P11 | todo | | | |
| 11.2 | Studies with time and CPU caps | P11 | todo | | | |
| 11.3 | Optimization and heatmaps | P11 | todo | | | |
| 11.4 | Overfitting safeguards | P11 | todo | | | |
| 11.5 | Walk-forward | P11 | todo | | | |
| 11.6 | Monte Carlo robustness | P11 | todo | | | |
| 11.7 | Agent tools for studies | P11 | todo | | | |
| 11.8 | End to end | P11 | todo | | | |
| 12.1 | Install and update audit | P12 | todo | | | |
| 12.2 | Notifications for every job kind, with preferences | P12 | todo | | | |
| 12.3 | Touch audit of charts and forms | P12 | todo | | | |
| 12.4 | Speed on the phone | P12 | todo | | | |
| 12.5 | Offline and reconnect behaviour | P12 | todo | | | |
| 13.1 | Security review of the local server | P13 | todo | | | |
| 13.2 | Robustness and resource limits | P13 | todo | | | |
| 13.3 | Diagnostics and logs | P13 | todo | | | |
| 13.4 | Backups, export, restore drill | P13 | todo | | | |
| 13.5 | Performance pass | P13 | todo | | | |
| 13.6 | Reproducibility audit | P13 | todo | | | |
| 13.7 | Runbook and product-readiness checklist | P13 | todo | | | |
| 14.1 | Packaging decision record | P14 | todo | | | |
| 14.2 | Backend as a sidecar | P14 | todo | | | |
| 14.3 | Tauri shell: window, tray, auto-start | P14 | todo | | | |
| 14.4 | Installers for Windows and macOS, code signing | P14 | todo | | | |
| 14.5 | Auto-update and release workflow | P14 | todo | | | |
| 14.6 | Data sources in the packaged app and the no-shipped-data check | P14 | todo | | | |
| 14.7 | Signed catalog updates from a static host | P14 | todo | | | |
| 14.8 | First-run experience | P14 | todo | | | |
| 14.9 | Clean-machine install tests | P14 | todo | | | |

## Phase kickoffs and exits

| Phase | Kickoff PR | Kickoff date | Exit PR | Exit date | Tag |
| --- | --- | --- | --- | --- | --- |
| P0 | (no kickoff) | | #8 | 2026-10-11 | phase-0 |
| P1 | #10 | 2026-10-12 | | | |
| P2 | | | | | |
| P3 | | | | | |
| P4 | | | | | |
| P5 | | | | | |
| P6 | | | | | |
| P7 | | | | | |
| P8 | | | | | |
| P9 | | | | | |
| P10 | | | | | |
| P11 | | | | | |
| P12 | | | | | |
| P13 | | | | | |
| P14 | | | | | |

## Milestones

| Milestone | Step | Reached |
| --- | --- | --- |
| Your Databento files and your own exports imported from the command line | 1.10 | |
| First backtest in a notebook (reference engine) | 2.2 | |
| Every run ready for prop simulation (trade paths) | 2.13 | |
| Trustworthy tick-level backtests from a notebook | 2.15 | |
| Feature system complete in notebooks | 3.8 | |
| App on the phone over Tailscale | 4.6 | |
| Web MVP | 5.13 | |
| Feature lab and builder | 6.9 | |
| Prop simulator on saved backtests and imported trade logs | 7.11 | |
| In-app agent | 8.11 | |
| Event strategies | 9.6 | |
| Alternative data | 10.7 | |
| Research tools | 11.8 | |
| Phone polish | 12.5 | |
| Hardening | 13.7 | |
| Signed catalog updates from a static host | 14.7 | |
| Desktop installers tested on clean machines | 14.9 | |
