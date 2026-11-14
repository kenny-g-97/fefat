# 01 — Architecture

This document is the map of the system. `02-engine-and-data.md`, `03-prop-simulator.md`, and `04-agent.md` go deeper into their areas. Decisions and their reasons are logged in `DECISIONS.md`.

## 1. System overview

```text
 ┌───────────────────────────── your PC (Windows now; macOS later) ─────────────────────────────┐
 │                                                                                              │
 │  browser on this PC                                                                          │
 │        │  HTTP, JSON + SSE                                                                   │
 │        ▼                                                                                     │
 │  fefat_app  ── FastAPI server, one process (`fefat up`)                                      │
 │     ├── http        FastAPI routers and schemas: the typed layer over the SDK                │
 │     ├── services    application services, one module per area (runs, strategies, prop, …)    │
 │     ├── ports.py    the seams as Protocols; container.py builds the adapters once            │
 │     ├── database    SQLite (app state: versions, runs, sessions, jobs)                       │
 │     ├── jobs        local process pool, events table → resumable streams                     │
 │     ├── executor    subprocess that runs user code (features, strategies, transforms)        │
 │     └── agent       Claude Messages API tool loop, proposals, skills                         │
 │        │                                                                                     │
 │        ▼                                                                                     │
 │  fefat  ── Python SDK (also used directly from notebooks)                                    │
 │     ├── market      catalog + sources, sync, your imports, calendars, bars, rolls → Parquet  │
 │     ├── features    feature runtime, cache, leak detector → Polars                           │
 │     ├── indicators  indicator library (ATR, RSI, VWAP, …), golden-tested against TA-Lib      │
 │     ├── strategy    SignalStrategy, Execution template, event strategies                     │
 │     ├── backtest    run config, artifacts (incl. trade paths), metrics, run.explain()        │
 │     ├── prop        rule sets, prop strategies, backtest-file replay, Monte Carlo            │
 │     ├── analytics   feature analytics (forward returns, IC, correlations, event studies)     │
 │     ├── research    sweeps, walk-forward, robustness, safeguards                             │
 │     └── reference   slow, readable Python reference engine (the specification)               │
 │        │                                                                                     │
 │        ▼                                                                                     │
 │  fefat_engine ── Rust extension (PyO3): mmap data cache, engine loop, prop replay, metrics   │
 │                                                                                              │
 │  %LOCALAPPDATA%\FEFAT\  config.toml · fefat.sqlite · data/ · cache/ · workspaces/default/    │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Three principles hold everything together:

1. **The SDK is the product.** Anything the app can do, a notebook can do with `import fefat as ff`. The server is a thin, typed layer over the SDK.
2. **Immutable, pinned, reproducible.** Features and strategies are immutable versions; runs pin everything they depend on; artifacts are files; the same inputs give identical outputs.
3. **Desktop-ready from day one.** One process, SQLite, files, no Docker, no external service needed to compute, portable paths. Packaging (Phase 14) wraps; it does not restructure.

## 2. Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Engine core | Rust (stable), `pyo3` + `maturin`, `abi3-py312` wheel | Crates in `engine/crates/`; Python module `fefat_engine` |
| SDK and app | Python 3.12 (uv-managed), Polars, PyArrow, DuckDB, Pydantic 2 | Packages `fefat` (SDK) and `fefat_app` (server) in a uv workspace; DuckDB 2.0 reads a run's artifacts from step 5.8 (D-93) |
| App state | SQLite (WAL), SQLAlchemy 2.1, Alembic 1.20 (batch mode) | One file, `fefat.sqlite`: the app's own state and an index of the workspace's files, which stay the record (D-84) |
| Server | FastAPI 0.162 + Uvicorn 0.54; argon2-cffi for the password, keyring for secrets | `fefat up` starts it on 127.0.0.1, port 8765 by default; OpenAPI exported to `web/openapi.json` |
| Web | Vite 8, React 19, TypeScript 6 (7 held), Tailwind 4, shadcn/ui, TanStack Router + Query, react-hook-form + zod 4, `openapi-typescript` 7 + `openapi-fetch`, oxlint and oxfmt | `web/` with pnpm, organised by product area (§3); the visual design comes from `web/DESIGN.md`, which applies the `contemporary-typeui` skill with the `frontend-design` and `unslop` skills (`08-code-design.md` §5, D-88); versions pinned at the Phase 4 kickoff (D-83); TanStack Table 9.3 and Virtual 3.14 from step 5.8, pinned at the Phase 5 kickoff (D-93) |
| Charts | TradingView Lightweight Charts 5 (price, markers, indicator panes), ECharts 6 (analytics) | Keep `attributionLogo` on (Apache-2.0 attribution): the logo is the link to TradingView its licence asks for, and its notice stands in the settings' About from step 5.4 (D-97); 5.2.1 and 6.1.0 pinned at the Phase 5 kickoff, both wrapped in `web/src/charts/`, ECharts loaded lazily (D-93) |
| Editor | CodeMirror 6 with `@codemirror/merge` | Lighter than Monaco, and it works on phones for the backlog's phone item; 6.0.2 and 6.12.3 pinned at the Phase 5 kickoff, loaded lazily (D-93) |
| Agent | `anthropic` Python SDK; tool loop; `claude-opus-5-5` default | See `04-agent.md` |
| Jobs | `concurrent.futures` process pool inside the server; subprocess runner for user code | See §6 |
| Tests | `pytest` + `hypothesis`; `cargo nextest` + `proptest` + `insta`; `vitest` 5 + Playwright 1.65 | See `05-build-process.md` |
| Task runner | `just` | Recipes call `uv`, `cargo`, `pnpm`; identical on Windows, CI, and macOS |
| CI | GitHub Actions: `windows-latest` and `ubuntu-latest` (macOS added in P14) | Wheels built on both |
| Desktop shell (P14) | Tauri 2, backend as a sidecar | Signed installers, auto-update |

## 3. Repository layout

```text
fefat/
  CLAUDE.md                     working agreements for Claude Code
  .claude/                      settings, rules/, skills/ (step, verify, …, and the three design skills), agents/, hooks/
  .githooks/                    pre-commit and pre-push guards (same checks as CI)
  justfile                      setup · check · test · e2e · dev · doctor
  pyproject.toml                uv workspace root: dev tools, ruff, pyright, pytest, import-linter contracts
  .python-version               3.12
  engine/                       Cargo workspace
    Cargo.toml
    rust-toolchain.toml
    crates/fefat-core           newtypes, orders, fills, errors, calendar, the MarketDataReader trait (no I/O)
    crates/fefat-engine         ExitPlan, fill rules, loop, TemplateStrategy, AccountModel: pure computation over fefat-core
    crates/fefat-prop           account state machine, backtest-file replay, prop strategies, Monte Carlo
    crates/fefat-metrics        performance metrics and the robustness summary
    crates/fefat-data           Arrow IPC cache builder and mmap reader implementing MarketDataReader (the only `unsafe`)
    crates/fefat-run            a run's config, signal rows, assembly, and artifact tables, shared by the two below (step 2.10)
    crates/fefat-py             PyO3 bindings → Python module `fefat_engine` (maturin); wires fefat-data into the engine
    crates/fefat-cli            spec in, artifacts out; drives golden tests and benchmarks
  python/
    fefat/                      the SDK package (uv workspace member, src layout)
      src/fefat/                market/ features/ indicators/ analytics/ strategy/ backtest/ prop/ research/ reference/ config.py
    fefat_app/                  the server package (uv workspace member, src layout)
      src/fefat_app/            http/ services/ ports.py container.py database/ jobs/ execution.py executor/ agent/ credentials.py cli.py
    tests/                      pytest for both packages (unit, contract, differential)
  web/                          Vite React app (pnpm)
    DESIGN.md                   the design system: tokens, type, layout, principles (step 4.3, from the Contemporary skill)
    src/app/                    shell, router, providers
    src/areas/<area>/           home, lab, strategies, runs, prop, agent, data, settings: routes, components, hooks per area
    src/ui/                     design-system primitives and tokens (themed shadcn/ui)
    src/charts/                 chart wrappers (Lightweight Charts, ECharts)
    src/api/                    generated OpenAPI client and query hooks
  fixtures/synthetic/           generated test data (the only data files allowed in git)
  fixtures/scenarios/           fill-rule scenario tables (YAML)
  notebooks/                    demos and your checks
  scripts/                      doctor.py, fixture generators, release helpers (Python)
  docs/
    masterplan/                 this plan
    adr/                        architecture decision records
    spec/                       fill-semantics.md and other normative specs
```

Dependencies point inward: `web → fefat_app.http → fefat_app.services → fefat → fefat_engine`. `fefat` never imports `fefat_app`; the adapters (`database/`, `jobs/`, `executor/`, `agent/`, `credentials.py`) implement the ports in `ports.py` and are built once in `container.py`; in Rust, only `fefat-data`, `fefat-py`, and `fefat-cli` touch the outside world. The rule, its reasons, the names, and how `just check` enforces it are in `08-code-design.md` §1–§3.

## 4. Runtime layout (the app-data folder)

`FEFAT_HOME` defaults to `%LOCALAPPDATA%\FEFAT` on Windows and `~/Library/Application Support/FEFAT` on macOS (`platformdirs`). `FEFAT_DATA_DIR` defaults to `<FEFAT_HOME>/data` and may point at a bigger drive.

```text
FEFAT_HOME/
  config.toml                 port, bind address, process-pool size, import roots (D-83)
  fefat.sqlite                app state
  logs/                       server.log, the local server's log with each request's id (step 4.2)
  data/                       canonical market data (Parquet; synced and imported) + raw/ (immutable vendor files + manifest; raw/user/ for your imports) + reports/ (quality reports) + instruments/ (products your imports added, step 1.10)
  profiles/                   your saved import profiles (YAML, step 1.10)
  cache/                      engine Arrow IPC cache, feature cache, session tables, the executor's executions/ (all rebuildable)
  workspaces/default/
    features/<name>/v<n>.json feature versions, the record the database indexes (D-84), with validations/<hash>.json
    strategies/<name>/v<n>.json strategy versions, the record the database indexes, and a strategy's abandoned mark (steps 5.2 and 5.5, D-93)
    artifacts/runs/<run key>/ orders, fills, costs, trades, trade_paths, equity, equity_daily, signals, log, run.json
    artifacts/runs/requests/  <request key>.json: the request lookup of step 3.7
    artifacts/studies/<id>/
    artifacts/prop/<id>/      prop simulation results
    trade_logs/<id>/          trade logs imported from other platforms (backtest files)
    uploads/<upload_id>/      a file the import wizard received, with its upload.json, the record (step 5.12, D-93)
    skills/                   user-added agent skills (optional)
```

Everything under `cache/` can be deleted and rebuilt. Everything else is backed up by `fefat backup` (P13).

## 5. Data model (SQLite)

All ids are UUIDv7 strings. Every row carries `created_at`; versioned rows are never updated after creation. Workspace files are the record of feature versions, the leak detector's reports, import profiles, and runs, and these tables index them beside the app's own state (D-84); each step creates the tables it first writes, in a migration of its own (D-83).

| Area | Tables (key columns) |
| --- | --- |
| Settings | `settings(key, value_json)`, `workspaces(id, name, path)`, `sessions(id, token_hash, created_at, expires_at, last_seen_at)`, `api_tokens(id, name, token_hash, created_at, last_used_at, revoked_at)` |
| Data | `datasets(id, kind, provider, schema, root, instrument, range_start, range_end, origin, licence_scope, catalog_version)` (`origin` is `sync` or `import`; `provider` names the connector or preset), `dataset_snapshots(id, dataset_id, manifest_json, content_hash)`, `instruments(id, root, symbol, kind, tick_size, point_value, currency, calendar, valid_from, valid_to, source)`, `fee_tables(id, name, effective_from, json)`, `catalog_products(id, catalog_version, spec_json, recommended_sources_json, status, last_sync_at)`, `data_sources(id, provider, status, connected_at)` (keys live in the credential store), `import_profiles(id, kind, name, mapping_json, sha256)` (`kind` is `market_data` or `trade_log`) |
| Code | `features(id, workspace_id, name, latest_version_id)`, `feature_versions(id, feature_id, version_no, parent_id, code, code_sha256, params_schema_json, inputs_json, outputs_json, warmup, warmup_sessions, combination_json, author_kind, proposal_id)`, `feature_validations(id, feature_version_id, report_sha256, instrument, timeframe, provider, window_start, window_end, parameters_json, report_json, passed)`, `strategies(id, workspace_id, name, kind, latest_version_id)`, `strategy_versions(id, strategy_id, version_no, parent_id, code, code_sha256, builder_spec_json, params_schema_json, author_kind, proposal_id, changelog)`, `strategy_version_features(strategy_version_id, feature_version_id)` |
| Runs | `runs(id, strategy_version_id, params_json, config_json, snapshot_ids_json, engine_version, fill_model_version, seed, run_key, origin, status, job_id, study_id, trial_no, metrics_json, artifact_dir, fidelity_json, warnings_json)` (`origin` is `manual`, `study`, `walk_forward`, `reproduce`, or `agent`), `studies(id, kind, spec_json, state, totals_json, summary_json, artifact_dir)` |
| Prop | `prop_rule_sets(id, firm, plan, name)`, `prop_rule_set_versions(id, rule_set_id, version_no, as_of, sources_json, rules_json, status)`, `prop_strategies(id, name)`, `prop_strategy_versions(id, prop_strategy_id, version_no, spec_json)`, `backtest_files(id, kind, run_id, import_profile_id, path_fidelity_json, instruments_json, range_start, range_end, trade_count, artifact_dir)` (`kind` is `run` or `imported`; `path_fidelity_json` is the mix of fidelities across trades), `prop_simulations(id, backtest_file_id, rule_set_version_ids_json, prop_strategy_version_id, config_json, sim_hash, metrics_json, artifact_dir)` |
| Agent | `agent_sessions(id, context_json, model, status)`, `agent_turns(id, session_id, status, usage_json, cost_usd)`, `agent_messages(id, session_id, turn_id, role, content_json)`, `agent_transcript(id, session_id, seq, block_json)` (append-only API transcript), `agent_tool_calls(id, turn_id, name, input_json, output_json, duration_ms)`, `proposals(id, session_id, kind, target_id, base_version_id, content, diff, validation_json, status, decided_at, comment, result_version_id)`, `usage_ledger(id, turn_id, model, input_tokens, output_tokens, cache_read_tokens, cost_usd)` |
| Uploads | `uploads(id, filename, size, sha256, status, path)`, `ingestion_recipes(id, upload_id, code, version_no)` |
| Jobs | `jobs(id, kind, payload_json, status, progress, attempt, max_attempts, worker_pid, lease_expires_at, cancel_requested_at, result_json, error, started_at, finished_at)`, `events(id INTEGER PRIMARY KEY, stream_id, type, data_json, created_at)` |

The schema is created by Alembic migrations from Phase 4. Earlier phases keep SDK state in files (manifests, run folders) and need no database.

Step 4.1 made `settings`, `workspaces`, `features`, `feature_versions`, `feature_validations`, `import_profiles`, `jobs`, and `events`, with these differences from the table above (D-85): `features` keeps no `latest_version_id`, a feature's latest version being its highest number; `feature_versions` names its hash `content_hash`, D-71's hash of the code, the features it reads, and the parameter schema; `feature_validations` keeps the report's `feature_name` and `feature_hash`, its link to a version empty where no version of that hash was saved when it was indexed; `import_profiles` keeps the kind, the name, and the file's `sha256`; `events.id` takes SQLite's `AUTOINCREMENT`, so that an event's id is never used again after a delete; and `parent_id`, `author_kind`, `proposal_id`, `report_json`, and `mapping_json` arrive with the steps that first write them (D-83). Triggers refuse an update or a delete of a row of the three tables that index a file; `fefat db import-workspace --rebuild` alone lifts them, in one transaction that empties those tables and the features they name, indexes the files again, and lays the triggers again from their own text (D-92). Step 4.4's migration `0003` gives `jobs` a `message`, the last progress message, so that the list of jobs shows it without reading their streams, and indexes `events` by `stream_id` and `id`, a stream's read (D-90).

At the Phase 5 kickoff (D-93): step 5.1 reads the datasets, the catalog, the source guide, and the instruments from the store through the SDK, so the Data row's tables but `import_profiles` arrive with the step that first writes state of its own into them, such as a connector's sync; strategies and their versions are files the database indexes, as feature versions are (D-84): step 5.2 creates `strategies`, `strategy_versions`, and `strategy_version_features` (migration `0004`), step 5.3 `runs` (`0005`), and step 5.5 the abandoned mark's columns of `strategies` (`0006`); and an upload's folder is its own record, `uploads` waiting for the recipes of Phase 10.

As step 5.2 built the strategies' tables (D-95): `strategies(id, workspace_id, name, kind)`, its latest version its highest number, as a feature's is (D-85); `strategy_versions(id, strategy_id, version_no, content_hash, code, hypothesis, instrument, timeframe, params_schema_json, changelog)`, `content_hash` in place of `code_sha256`, the hash of the code, the pinned feature versions, and the parameter schema, beside the hypothesis and the instrument and the timeframe its strategy names, while `parent_id`, `builder_spec_json`, `author_kind`, and `proposal_id` arrive with the steps that first write them; and `strategy_version_features(strategy_version_id, feature_version_id)`, a row for each feature version a version pins. Triggers refuse an update or a delete of a version's row and of a pin's, which a rebuild of the index lifts as it lifts the features'; and `index_workspace` takes its folders, the library's versions indexed by `index_library` alone before each save of the app and once it has saved a version.

As step 5.3 built the runs (D-96): `runs(id, origin, strategy_version_id, parameters_json, window_start, window_end, settings_json, request_key, job_id, run_key, metrics_json, fidelity_eras_json, warnings_json)`, a row a backtest asked for through the API with its job until its folder is saved, then the index of that folder, whose record its columns hold, and a row for each saved folder no submission made, which `index_workspace` reads before it takes the write lock; a row holds its job or its run key (a named `CHECK`), the key unique and `request_key` indexed; its status is derived, `succeeded` once its key is set, its job's before, so the table keeps none; it keeps no folder, `runs/<run key>`, no versions or snapshots, which `run.json` holds, and `study_id` and `trial_no` arrive with the studies of Phase 11; triggers refuse an update or a delete of a row once its key is set, which a rebuild lifts, emptying `runs` first and forgetting the submissions that never saved.

As step 5.4 changed it (D-97): migration `0006` keeps token names apart among live tokens alone, `api_tokens`' unique constraint on `name` giving way to a unique index on `name` where `revoked_at` is null, so that a revoked token's name can be given again, and step 5.5's columns of `strategies` become migration `0007`; and the charts' style is the `settings` row `chart_style`, as the theme is one, with no migration.

## 6. Jobs and execution

- **Jobs** are rows in `jobs`. Kinds in the first release: `backtest`, `feature_preview`, `feature_validate`, `analytics`, `study`, `prop_sim`, `source_sync`, `import`, `trade_import`, `catalog_sync`, `reproduce`, `agent_turn`, `ingest`, plus `demo` and `python_snippet` for tests and tooling; later phases add kinds the same way. State machine: `queued → running → succeeded | failed | cancelled | timed_out`; transitions are compare-and-set updates, and a running job whose worker stopped answering goes back to `queued` while it has attempts left, failing after its last (step 4.4, D-90). At the Phase 5 kickoff (D-93): `catalog_sync` runs a product's quality report, the connectors' `source_sync` waiting with them, and `explain` joins the kinds for step 5.9's trade explanations; the trader's code runs in the executor through a spec kind of its own, a strategy's validation (step 5.2), `backtest` (5.3, which `reproduce` reuses), and an import's preview and the import (5.12).
- **Runner.** The server owns a process pool sized from `config.toml` (default: physical cores minus two, which psutil counts, D-90). Each job runs `run_job(job_id)` in a worker process; progress is written to `events` (stream `job:<id>`) and `jobs.progress`. As step 4.4 built it: the pool's processes are spawned, the only start method Windows has; a worker renews its job's lease every 3 s, and a reaper in the server ends a worker whose 15-second lease ran out and queues its job again; a worker's end breaks CPython's pool and ends its other workers, whose jobs the reaper queues again (`BACKLOG.md`). Since the Phase 4 exit (D-92), where the database refuses the reaper's change past its busy timeout, as a worker hung inside its own write makes it, the reaper ends the worker first, and the sweeps for a lease after a gap longer than a lease, as when the PC slept, leave the running jobs to their workers.
- **Streams.** `GET /v1/streams/{stream_id}` is Server-Sent Events backed by the `events` table: the event id is the row id, the client reconnects with `Last-Event-ID`, heartbeats every 15 s. Agent turns use the same mechanism (stream `turn:<id>`). As step 4.4 built it: without `Last-Event-ID` a stream starts at its first event, it ends only when the client goes, and the server reads the table every half second, the workers writing from their own processes. Since the Phase 4 exit the web app follows streams from the shown tab alone, since Chromium keeps six connections to a host for all the tabs of a browser, and closes a job's stream at the job's end (D-92).
- **Executor.** User code (features, strategies, ingestion transforms) runs through `fefat_app.executor`: a subprocess with a scrubbed environment, a wall-clock timeout, a memory limit (Job Objects on Windows, `RLIMIT_AS` elsewhere), and a result file validated against a Pydantic model before anything is registered. This is crash containment and resource control, not a security boundary — a local app runs the user's own code. As step 4.5 built it (D-91): the runner is `python -P -m fefat_app.executor` from `sys.executable`, for one execution's folder under `cache/executions/` or, warm, for each folder sent on its stdin, and it ends at the end of its stdin, with its session, so that neither it nor a process it started outlives its executor; on Windows it starts suspended and joins a Job Object whose processes may commit the limit together, and which ends them all when closed, elsewhere it runs in a session of its own and caps the address space of each of its processes; the timeout counts from the execution's start; the executor asks the caller whenever a second passes without a report whether the execution runs on, so that a job asked to stop has its worker stop the runner within a second, without the reaper; the environment keeps the system's variables, the Python path, and FEFAT's two folders as the server's environment names them, with keyring's null backend; `result.json` and a preview's `series.parquet` are capped in size and validated, and a validation's error quotes no value; the kinds are `feature_preview`, statistics and a series of at most a thousand points an output that keeps its highs and lows, and `python_snippet`, the tail of what it printed; the server's executor runs the previews in one warm runner, started again after a failure, a timeout, or another memory limit, while a snippet, and every execution a job of the pool runs, starts a runner of its own; and a job whose execution runs out of time ends `timed_out`. What it does not protect against: files the trader may read or write, the data folder included, read-only by convention; the Windows credential store read through the system's own interfaces; the network; memory beyond the limit on Linux taken by several processes the code started, and any memory on macOS; and a process that leaves its job or session on purpose (`fefat_app.executor`). Since the Phase 4 exit `fefat up` removes what executions left in `cache/executions` more than a day ago, and a runner's `PYTHONPATH` keeps no empty or relative entry, which Python reads against the working folder (D-92). As step 5.2 added them (D-95): the kinds `strategy_validation`, `strategy_save`, and `feature_save` build a strategy's code, save a strategy version, and save a feature version through the SDK, each in a runner of its own within a minute and 4 GiB, and answer the SDK's refusal with the line of the code it is at, rather than failing. As step 5.3 added them (D-96): `run_lookup` builds a saved version's strategy with its parameters (`StrategyVersion.strategy`) and answers the run its request found saved or the run to make, the settings applied, within a minute and 4 GiB, and `backtest` runs `ff.backtest.run`, reports its four stages, and answers its run key, within 6 hours and 8 GiB, its job indexing the folder into the run's row (`fefat_app.jobs.backtests`).
- **Cancellation.** The API sets `cancel_requested_at`; workers check it between chunks and trials; after a grace period the runner kills the subprocess. As step 4.4 built it: a queued job is cancelled at once, and the reaper ends a running job's worker 10 s after the request. Since the Phase 4 exit a requeue refuses a job asked to stop, which the reaper then cancels, and a cancel that meets a requeue between its tries tries again (D-92).
- **Idempotency.** A run's identity is the engine's run key (`02-engine-and-data.md` §4), which covers the spec, the run's config, the signal frame, the snapshots of the data it read, and the versions: it names the run's folder (D-62) and is unique in `runs.run_key` beside the row's UUIDv7 id (D-83), and the request lookup of step 3.7 finds an identical request's run without loading bars or evaluating signals. Submitting an identical run returns the existing run. As step 5.3 built it (D-96): `POST /runs` looks the run up in the executor; a run its request found saved is answered at once, and otherwise the row of the same request waiting on an active job not asked to stop, or a new row with its queued job, made in one transaction; a strategy whose expressions call Python keys no request and queues a job each time, and a job whose run proves saved under another row's key removes its own row and names that one in its result.
- **Sweeps** (P11) are a parent `study` job that expands trials, skips hashes already done, and dispatches chunks of trials; signal-strategy chunks run inside one `fefat_engine.run_batch` call that parallelises with Rayon over the shared memory-mapped data.

## 7. API outline

Base path `/v1`, JSON, cursor pagination, `application/problem+json` errors, `Idempotency-Key` on creating POSTs (safe retries).

| Area | Endpoints |
| --- | --- |
| Session | `POST /auth/login`, `POST /auth/logout`, `POST /auth/password`, `GET /me`, `GET/PUT /settings`, `GET/POST /api-tokens`, `DELETE /api-tokens/{name}` |
| Data | `GET /instruments`, `GET /datasets`, `GET /datasets/{id}/quality`, `GET /market/bars?instrument&timeframe&from&to&continuous&provider&origin&prices`, `GET /market/bars/span?instrument&timeframe&continuous&provider&origin`, `GET /catalog`, `POST /catalog/sync` (the quality report as a job until the connectors, D-93), `GET /sources`, `POST /sources` (connect one; the key goes to the credential store; with the connectors, D-93), `GET/POST /import-profiles`, `POST /imports/preview`, `POST /imports` |
| Features | `GET/POST /features`, `GET /features/{id}/versions`, `POST /features/{id}/versions`, `POST /features/preview`, `POST /features/validate`, `GET /features/{id}/analytics` |
| Strategies | `GET/POST /strategies`, `GET /strategies/templates`, `POST /strategies/validate`, `GET /strategies/{id}/versions`, `POST /strategies/{id}/versions`, `POST /strategies/build` (spec → code), `GET /strategies/{id}/diff?from&to` |
| Runs | `POST /runs` (202 or the cached run), `GET /runs`, `GET /runs/{id}`, `/runs/{id}/trades`, `/equity?max_points`, `/chart?from&to`, `/stats`, `/distribution`, `POST /runs/{id}/query` (DuckDB SQL, row cap), `POST /runs/compare`, `POST /runs/{id}/explain/{trade_id}` (202, an `explain` job, D-93) |
| Studies | `POST /studies`, `POST /studies/{id}/estimate`, `GET /studies/{id}/trials`, `POST /studies/{id}/cancel` |
| Prop | `GET/POST /prop/rule-sets`, `/prop/rule-sets/{id}/versions`, `GET/POST /prop/strategies`, `/prop/strategies/{id}/versions`, `GET /prop/backtest-files`, `POST /prop/backtest-files/preview`, `POST /prop/backtest-files` (import a trade log), `POST /prop/simulations` (backtest file + rule sets + prop strategy), `GET /prop/simulations/{id}` |
| Uploads | `POST /uploads` (multipart), `GET /uploads/{id}/inspect`, `POST /uploads/{id}/recipes`, `POST /uploads/from-url` |
| Agent | `GET/POST /agent/sessions`, `POST /agent/sessions/{id}/turns`, `POST /agent/turns/{id}/stop`, `GET /agent/sessions/{id}/messages`, `GET /proposals`, `POST /proposals/{id}/decision` |
| Jobs | `GET /jobs` (the hundred newest, then the running jobs older than them, D-92), `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `GET /streams/{stream_id}` (SSE), `POST /jobs/demo` (step 4.4: each kind has a creating route of its own, as `POST /runs`, D-90) |
| Health | `GET /healthz`, `GET /version` |

The web app's TypeScript types are generated from `web/openapi.json` by `openapi-typescript`; CI regenerates and fails on a diff.

As step 5.1 built the Data row (D-94): its routes read the SDK through `fefat_app.services.catalog` over a `Store` the container builds once, and keep nothing in the database; a dataset's id is `provider:schema:root`; `GET /market/bars` takes its window in trade dates and answers `load`'s bars a page of at most 20,000 at a time, their opens in whole seconds and their prices as floats in the instrument's units, with `next_from`, the instant the next page opens at, which comes back as `from`; and `POST /catalog/sync` answers 202 with the `catalog_sync` job, or 404 where the store holds nothing to report.

As step 5.2 built the Strategies and Features rows (D-95): a strategy's or a feature's id is its index row's UUIDv7, which a rebuild of the index renews; `GET /strategies` and `GET /features` list each with its versions from the index, and a version is read from its file with the lint's findings in its code; `POST /strategies` takes a name, the code, a hypothesis, and a changelog, `POST /strategies/{id}/versions` the last three, and both save in the executor, answering 201 for a version they wrote, the second 200 for the same code saved before with the same words, 400 with the code's `line` for a refusal, and 409 for a name a saved strategy has or files the index cannot follow; `POST /strategies/validate` answers 200 with `valid`, the parameters' schema, and the lint's findings, or `refused` and the line; `GET /strategies/{id}/diff?from&to` answers `code_diff`, the unified diff of the code, the builder spec's waiting for step 6.8; `GET /strategies/templates` gives the three templates with their code; and the features' routes mirror these, `POST /features` taking the feature's name with its code, while `preview`, `validate`, and `analytics` arrive with Phase 6.

As step 5.3 built the Runs row (D-96): `POST /runs` takes `strategy_version_id`, the version's index row, its `parameters`, `start` and `end`, and `settings`, the SDK's `RunConfig`, and answers 200 with the run its request found saved and 202 with a run whose `backtest` job waits or runs, whose stages its job's stream gives, 400 with the code's `line` where the code gives no strategy, 404 for an unknown version, 409 for files the index cannot follow, and 422 for a window that ends before it starts; a run carries its settings as `AppliedRunConfig`, money as decimal text; `GET /runs` gives the hundred newest without their metrics, filters and paging waiting for step 5.6, `GET /runs/{id}` a run with its metrics, fidelity eras, and warnings once saved, and `POST /runs/{id}/cancel` cancels its job.

As step 5.4 built the Data row further (D-97): `GET /market/bars/span` takes a series' `instrument`, `timeframe`, `continuous`, `provider`, and `origin`, and answers its provider and the first and the last trade date its data holds, a contract's own for a contract, and a spliced series' within the sessions its roll calendar decides, which the chart cuts into windows that it asks of that provider; `GET /market/bars` takes `prices`, `adjusted` or `raw`, the second the spliced series at the prices each session's front contract traded at and refused for a back-adjusted import, carries `warnings`, what `load` warns of, and ends a page after 20 sessions of prints or sub-minute bars and after 260 sessions of any data, beside its 20,000 bars, a contract's window ending at its own last trade date; `GET /datasets/{id}/quality` gives `months`, the coverage by month, once a report exists; and `GET/PUT /settings` carry `chart_style`.

## 8. Local server security

- Binds to `127.0.0.1` only; the server never binds to another address. Exposure to the phone is deferred (D-54).
- Login by password (set on first run) creates a session cookie (`HttpOnly`, `Secure` when served over HTTPS, `SameSite=Strict`). A CSRF token guards state-changing requests. A bearer token is accepted for notebooks and scripts.
- Rate limit on login; passwords hashed with Argon2.
- Content Security Policy: `default-src 'self'; img-src 'self' data: blob:` (no remote images in chat). From step 5.4 it adds `style-src 'self' 'unsafe-inline'`, since Radix's modal overlays and CodeMirror write style elements, scripts staying `'self'` alone; a nonce for each page, the stricter path, waits in `BACKLOG.md` (D-93).
- As step 4.2 built it (D-86): a session lasts 30 days, and its CSRF token is the SHA-256 of its token under a fixed prefix, kept nowhere; a request with a bearer token is decided by that token alone and needs no CSRF token; the login counts five attempts a minute before Argon2 runs; a host other than `127.0.0.1` or `localhost` is refused, so that a DNS name rebound to the loopback reaches nothing, and uvicorn trusts no forwarded header; `/docs` and `/openapi.json` sit behind the login, `/docs` answering a small page with a password box, which stays beside the web app's login of step 4.3 since it needs no built web app (D-87), never the browser's own prompt, which password managers answer by themselves, and the docs page loads one release of Swagger UI under a policy of its own, from the package itself since the Phase 4 exit, where it came from jsdelivr (D-92); a request body over 1 MiB is refused before it is read; errors are problem+json that never echo the values sent, but for Starlette's plain 413 for a body declared too large; and every response carries its request's id, which the server's log under `logs/` records.
- As step 4.3 added it: a change of the password takes the current one, counted with the login's five attempts a minute, ends every session, and opens a new one for the browser that asked; the password and the API tokens are managed by a login session alone, never by an API token, so that no token mints another; a token is revoked by its name, and a revoked token's name stays taken; the theme is a row of the `settings` table, which `PUT /settings` changes beside the secrets, each optional.
- As step 5.2 added it (D-95): a password that replaces another revokes every live API token, in the transaction that ends the sessions, whether the settings page, `fefat password set`, or a script changes it, while a first password revokes none.
- As step 5.4 built it (D-97): the policy adds `style-src 'self' 'unsafe-inline'`, which Lightweight Charts needs for the style element of its logo, scripts staying `'self'` alone, as a spec proves in the browser; and token names stay apart among live tokens alone, so that a revoked token's name can be given again. From your third check of the step: the browser's local storage, used for the first time, holds one entry, the size in pixels the trader dragged the chart's frame to (`fefat_chart_frame_size`), read back through a zod schema; no secret, token, or market data goes there, where every script of the page can read.
- File access is confined to `FEFAT_HOME` and `FEFAT_DATA_DIR`; the API never takes raw filesystem paths from clients except for imports of large files, which are validated against the import roots allowed in `config.toml`.
- Catalog updates from FEFAT's static host (Phase 14) are verified against a signed manifest and file hashes before they are installed; that host never serves market data.
- Secrets (Anthropic API key, data vendor keys such as Databento's) live in the OS credential store via `keyring`, never in `config.toml`.

## 9. Environments

| Environment | What runs | Data |
| --- | --- | --- |
| `dev` | `just dev`: server with auto-reload + Vite dev server with proxy | Synthetic fixtures by default; real data under `FEFAT_DATA_DIR` when you choose |
| `test` | `just test`: Rust, Python, and web unit/integration tests; `just e2e`: Playwright against a seeded server | Synthetic only |
| `local` | `fefat up`: production build of the UI served by the server | Your real data |
| `release` (P14) | CI builds wheels and installers, signed | — |

CI runs `just check` and `just test` on `windows-latest` and `ubuntu-latest` for every pull request, builds the `fefat_engine` wheel on both, and asserts identical golden-run hashes on both systems.

As step 5.1 built `just dev` (D-94): without `FEFAT_HOME`, it serves `fefat-dev` in the temporary folder, made afresh at each start as the UI harness's home is, with the synthetic fixtures, or the data folder `FEFAT_DATA_DIR` names, and prints its password; with `FEFAT_HOME`, that home; and it starts the server again whenever the SDK's or the app's source changes, since `fefat up` hands uvicorn an app object, which uvicorn cannot reload.

As step 5.4 seeded it (D-97): the harness's home, and `just dev`'s throwaway one, hold a generated year of MES one-minute bars, 2025-04-01 to 2026-03-31, beside the fixtures, so that the data pages have a catalog product to check the quality of and the chart a year to scroll back through.

## 10. Seams that keep options open

| Seam | Interface | Today | Later |
| --- | --- | --- | --- |
| Executor | `Executor.run(ExecutionSpec, report, check) -> ExecutionResult`, the reports of progress given to `report` as they come and `check` asked whenever a second passes without one, and `close()` (D-91) | subprocess, with a warm runner for the previews | containers, if ever needed |
| Dispatcher | `start()`, `submit(job_id)`, `close()`, a job cancelled through its records (D-90) | local process pool | remote workers, cloud sync |
| Blob store | `BlobStore.put/get/list` over workspace paths | local files | optional cloud sync |
| Agent runtime | `AgentRuntime.run_turn(session, message, tools, emit)` | Messages API loop | Agent SDK or Managed Agents |
| Data source | `Provider.describe()`, `fetch(symbol, schema, range)` in `fefat.market.sources` | Databento with your own key, the public crypto archives, file presets | more vendors, one provider each; never a FEFAT-hosted data service (D-37) |
| Credential store | `secrets.get/set(name)` | Windows credential store | macOS keychain, Linux secret service |
| Licensing | `licence.check(feature, scope)` | always `ok` | app licence keys (backlog); never a gate on data, which the trader's own accounts cover (D-37) |

Each seam except the data source (`Provider`, SDK code in `fefat.market.sources`) is a `Protocol` in `python/fefat_app/src/fefat_app/ports.py` (the Rust seams, `MarketDataReader` and `AccountModel`, are traits in `fefat-core`); the adapters are chosen in `container.py` from `config.toml`, so swapping one is a configuration change plus one new module (`08-code-design.md` §1).

## 11. Conventions

- Time is nanoseconds since the Unix epoch, UTC, as `int64`; local-time rules (sessions, flat-by times) are converted to UTC instants per trade date before a run.
- Money and prices are integers in the engine (prices in Databento's 1e-9 units; money in micro-units of the account currency); floats appear only at the SDK boundary.
- Hashes are BLAKE3 (engine) and SHA-256 (app), hex, lower case.
- IDs: UUIDv7. Version numbers: integers starting at 1 per feature/strategy.
- Line endings LF everywhere (`.gitattributes`); paths through `pathlib`; project scripts are Python run through `uv run python` (bare `python` is a Store stub on this PC) plus `just` recipes; Claude Code hooks are Node scripts; the only shell files are the one-line git pre-commit and pre-push launchers (D-48).
- Python: ruff + pyright strict for `fefat_app`, basic for `fefat`; Rust: clippy with `unwrap_used`, `panic`, `indexing_slicing` denied in core crates; TypeScript: strict.
- Code design: `08-code-design.md` — the dependency rule (`web → fefat_app.http → services → fefat → fefat_engine`), intention-revealing names (never `data`, `utils`, `helpers`, `manager`, …), fail-fast errors, an enum for every state, injected ports, immutable values, small units; one design system in `web/DESIGN.md`, the `contemporary-typeui` skill applied with the `frontend-design` and `unslop` skills (D-88).
