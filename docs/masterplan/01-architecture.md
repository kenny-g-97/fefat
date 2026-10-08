# 01 — Architecture

This document is the map of the system. `02-engine-and-data.md`, `03-prop-simulator.md`, and `04-agent.md` go deeper into their areas. Decisions and their reasons are logged in `DECISIONS.md`.

## 1. System overview

```text
 ┌───────────────────────────── your PC (Windows now; macOS later) ─────────────────────────────┐
 │                                                                                              │
 │  browser / phone (PWA over Tailscale)                                                        │
 │        │  HTTPS, JSON + SSE                                                                   │
 │        ▼                                                                                     │
 │  fefat_app  ── FastAPI server, one process (`fefat up`)                                      │
 │     ├── db          SQLite (app state: versions, runs, sessions, jobs)                        │
 │     ├── jobs        local process pool, events table → resumable streams                     │
 │     ├── exec_runner subprocess that runs user code (features, strategies, transforms)        │
 │     ├── agent       Claude Messages API tool loop, proposals, skills                          │
 │     └── push        web push (VAPID) for job completion                                      │
 │        │                                                                                     │
 │        ▼                                                                                     │
 │  fefat  ── Python SDK (also used directly from notebooks)                                    │
 │     ├── data        import, calendars, bars, rolls, catalog        → Parquet on disk          │
 │     ├── features    feature runtime, cache, leak detector, ta      → Polars                   │
 │     ├── strategy    SignalStrategy, Execution template, event strategies                     │
 │     ├── backtest    run config, artifacts, metrics, run.explain()                            │
 │     ├── prop        rule sets, policies, replay, Monte Carlo                                 │
 │     ├── analytics   feature analytics (forward returns, IC, correlations, event studies)     │
 │     ├── research    sweeps, walk-forward, robustness, safeguards                            │
 │     └── ref         slow, readable Python reference engine (the specification)              │
 │        │                                                                                     │
 │        ▼                                                                                     │
 │  fefat_engine ── Rust extension (PyO3): mmap data cache, engine loop, prop account, metrics  │
 │                                                                                              │
 │  %LOCALAPPDATA%\FEFAT\  config.toml · fefat.sqlite · data/ · cache/ · workspaces/default/   │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Three principles hold everything together:

1. **The SDK is the product.** Anything the app can do, a notebook can do with `import fefat as ff`. The server is a thin, typed layer over the SDK.
2. **Immutable, pinned, reproducible.** Features and strategies are immutable versions; runs pin everything they depend on; artifacts are files; the same inputs give identical outputs.
3. **Desktop-ready from day one.** One process, SQLite, files, no Docker, no external service, portable paths. Packaging (Phase 14) wraps; it does not restructure.

## 2. Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Engine core | Rust (stable), `pyo3` + `maturin`, `abi3-py312` wheel | Crates in `engine/crates/`; Python module `fefat_engine` |
| SDK and app | Python 3.12 (uv-managed), Polars, PyArrow, DuckDB, Pydantic 2 | Packages `fefat` (SDK) and `fefat_app` (server) in a uv workspace |
| App state | SQLite (WAL), SQLAlchemy 2, Alembic (batch mode) | One file: `fefat.sqlite` |
| Server | FastAPI + Uvicorn | `fefat up` starts it; OpenAPI exported to `web/openapi.json` |
| Web | Vite 8, React 19, TypeScript, Tailwind 4, shadcn/ui, TanStack Router + Query, react-hook-form + zod, `openapi-typescript` + `openapi-fetch`, `vite-plugin-pwa` | `web/` with pnpm |
| Charts | TradingView Lightweight Charts 5 (price, markers, indicator panes), ECharts 6 (analytics) | Keep `attributionLogo` on (Apache-2.0 attribution) |
| Editor | CodeMirror 6 with `@codemirror/merge` (unified on phones, side-by-side on desktop) | Monaco does not support phones |
| Phone access | Tailscale (personal plan) with its HTTPS certificate; service worker; web push via `pywebpush` | iOS needs 16.4+, home-screen install, and a tap to request permission |
| Agent | `anthropic` Python SDK; tool loop; `claude-opus-5-5` default | See `04-agent.md` |
| Jobs | `concurrent.futures` process pool inside the server; subprocess runner for user code | See §6 |
| Tests | `pytest` + `hypothesis`; `cargo nextest` + `proptest` + `insta`; `vitest` + Playwright | See `05-build-process.md` |
| Task runner | `just` | Recipes call `uv`, `cargo`, `pnpm`; identical on Windows, CI, and macOS |
| CI | GitHub Actions: `windows-latest` and `ubuntu-latest` (macOS added in P14) | Wheels built on both |
| Desktop shell (P14) | Tauri 2, backend as a sidecar | Signed installers, auto-update |

## 3. Repository layout

```text
fefat/
  CLAUDE.md                     working agreements for Claude Code
  .claude/                      settings, rules/, skills/, agents/, hooks/
  .githooks/                    pre-commit guard (same checks as CI)
  justfile                      setup · check · test · e2e · dev · doctor
  pyproject.toml                uv workspace root
  engine/                       Cargo workspace
    Cargo.toml
    rust-toolchain.toml
    crates/fefat-core           types, errors, calendar, fixed-point money
    crates/fefat-data           Arrow IPC cache builder/reader (the only `unsafe`: mmap)
    crates/fefat-engine         orders, ExitPlan, fill rules, loop, TemplateStrategy, AccountModel
    crates/fefat-prop           account state machine, replay, policies, Monte Carlo
    crates/fefat-metrics        performance metrics
    crates/fefat-py             PyO3 bindings → Python module `fefat_engine` (maturin)
    crates/fefat-cli            spec in, artifacts out; drives golden tests and benchmarks
  python/
    fefat/                      the SDK: data/ features/ ta/ analytics/ strategy/ backtest/ prop/ research/ ref/ config.py
    fefat_app/                  server/ db/ jobs/ exec_runner.py agent/ push/ secrets.py cli.py
    tests/
  web/                          Vite React app (pnpm)
  fixtures/synthetic/           generated test data (the only data files allowed in git)
  fixtures/scenarios/           fill-rule scenario tables (YAML)
  notebooks/                    demos and your checks
  scripts/                      doctor.py, fixture generators, release helpers (Python)
  docs/
    masterplan/                 this plan
    adr/                        architecture decision records
    spec/                       fill-semantics.md and other normative specs
```

## 4. Runtime layout (the app-data folder)

`FEFAT_HOME` defaults to `%LOCALAPPDATA%\FEFAT` on Windows and `~/Library/Application Support/FEFAT` on macOS (`platformdirs`). `FEFAT_DATA_DIR` defaults to `<FEFAT_HOME>/data` and may point at a bigger drive.

```text
FEFAT_HOME/
  config.toml                 port, bind address, Tailscale exposure, data dir, model defaults
  fefat.sqlite                app state
  logs/
  data/                       canonical market data (Parquet) + raw/ (immutable vendor files + manifest) + reports/ (quality reports)
  cache/                      engine Arrow IPC cache, feature cache (both rebuildable)
  workspaces/default/
    features/<name>/v<n>.json file-based feature versions from Phase 3 (imported into the database in 4.1, kept as backup)
    artifacts/runs/<run_id>/  orders, fills, trades, equity, signals, log, run.json
    artifacts/studies/<id>/
    artifacts/prop/<id>/
    uploads/<upload_id>/
    skills/                   user-added agent skills (optional)
```

Everything under `cache/` can be deleted and rebuilt. Everything else is backed up by `fefat backup` (P13).

## 5. Data model (SQLite)

All ids are UUIDv7 strings. Every row carries `created_at`; versioned rows are never updated after creation.

| Area | Tables (key columns) |
| --- | --- |
| Settings | `settings(key, value_json)`, `workspaces(id, name, path)` |
| Data | `datasets(id, kind, provider, schema, root, instrument, range_start, range_end, license_scope)`, `dataset_snapshots(id, dataset_id, manifest_json, content_hash)`, `instruments(id, root, symbol, kind, tick_size, point_value, currency, calendar, valid_from, valid_to)`, `fee_tables(id, name, effective_from, json)` |
| Code | `features(id, workspace_id, name, latest_version_id)`, `feature_versions(id, feature_id, version_no, parent_id, code, code_sha256, params_schema_json, inputs_json, warmup, validation_json, author_kind, proposal_id)`, `strategies(id, workspace_id, name, kind, latest_version_id)`, `strategy_versions(id, strategy_id, version_no, parent_id, code, code_sha256, builder_spec_json, params_schema_json, author_kind, proposal_id, changelog)`, `strategy_version_features(strategy_version_id, feature_version_id)` |
| Runs | `runs(id, strategy_version_id, params_json, config_json, snapshot_ids_json, engine_version, fill_model_version, seed, run_hash, origin, status, job_id, study_id, trial_no, metrics_json, artifact_dir, fidelity_json, warnings_json)` (`origin` is `manual`, `study`, `walk_forward`, `reproduce`, or `agent`), `studies(id, kind, spec_json, state, totals_json, summary_json, artifact_dir)` |
| Prop | `prop_rule_sets(id, firm, plan, name)`, `prop_rule_set_versions(id, rule_set_id, version_no, as_of, sources_json, rules_json, status)`, `prop_policies(id, name)`, `prop_policy_versions(id, policy_id, version_no, policy_json)`, `prop_simulations(id, source_run_ids_json, rule_set_version_id, policy_version_id, config_json, sim_hash, metrics_json, artifact_dir)` |
| Agent | `agent_sessions(id, context_json, model, status)`, `agent_turns(id, session_id, status, usage_json, cost_usd)`, `agent_messages(id, session_id, turn_id, role, content_json)`, `agent_transcript(id, session_id, seq, block_json)` (append-only API transcript), `agent_tool_calls(id, turn_id, name, input_json, output_json, duration_ms)`, `proposals(id, session_id, kind, target_id, base_version_id, content, diff, validation_json, status, decided_at, comment, result_version_id)`, `usage_ledger(id, turn_id, model, input_tokens, output_tokens, cache_read_tokens, cost_usd)` |
| Uploads | `uploads(id, filename, size, sha256, status, path)`, `ingestion_recipes(id, upload_id, code, version_no)` |
| Jobs | `jobs(id, kind, payload_json, status, progress, attempt, max_attempts, worker_pid, lease_expires_at, cancel_requested_at, result_json, error, started_at, finished_at)`, `events(id INTEGER PRIMARY KEY, stream_id, type, data_json, created_at)` |
| Push | `push_subscriptions(id, endpoint, keys_json)` |

The schema is created by Alembic migrations from Phase 4. Earlier phases keep SDK state in files (manifests, run folders) and need no database.

## 6. Jobs and execution

- **Jobs** are rows in `jobs`. Kinds in the first release: `backtest`, `feature_preview`, `feature_validate`, `analytics`, `study`, `prop_sim`, `import`, `catalog_sync`, `reproduce`, `agent_turn`, `ingest`, plus `demo` and `python_snippet` for tests and tooling; later phases add kinds the same way. State machine: `queued → running → succeeded | failed | cancelled | timed_out`; transitions are compare-and-set updates.
- **Runner.** The server owns a process pool sized from `config.toml` (default: physical cores minus two). Each job runs `run_job(job_id)` in a worker process; progress is written to `events` (stream `job:<id>`) and `jobs.progress`.
- **Streams.** `GET /v1/streams/{stream_id}` is Server-Sent Events backed by the `events` table: the event id is the row id, the client reconnects with `Last-Event-ID`, heartbeats every 15 s. Agent turns use the same mechanism (stream `turn:<id>`).
- **Executor.** User code (features, strategies, ingestion transforms) runs through `fefat_app.exec_runner`: a subprocess with a scrubbed environment, a wall-clock timeout, a memory limit (Job Objects on Windows, `RLIMIT_AS` elsewhere), and a result file validated against a Pydantic model before anything is registered. This is crash containment and resource control, not a security boundary — a local app runs the user's own code.
- **Cancellation.** The API sets `cancel_requested_at`; workers check it between chunks and trials; after a grace period the runner kills the subprocess.
- **Idempotency.** `run_hash = sha256(strategy version hash, params, config, snapshot hashes, engine version, fill-model version, seed)` is the app-level identity of a run; the engine's own run key (`02-engine-and-data.md` §4, over the spec and the signal frame) is one of its inputs. Submitting an identical run returns the existing run.
- **Sweeps** (P11) are a parent `study` job that expands trials, skips hashes already done, and dispatches chunks of trials; signal-strategy chunks run inside one `fefat_engine.run_batch` call that parallelises with Rayon over the shared memory-mapped data.

## 7. API outline

Base path `/v1`, JSON, cursor pagination, `application/problem+json` errors, `Idempotency-Key` on creating POSTs (safe retries from phones).

| Area | Endpoints |
| --- | --- |
| Session | `POST /auth/login`, `POST /auth/logout`, `GET /me`, `GET/PUT /settings` |
| Data | `GET /instruments`, `GET /datasets`, `GET /datasets/{id}/quality`, `GET /market/bars?instrument&timeframe&from&to`, `POST /imports` |
| Features | `GET/POST /features`, `GET /features/{id}/versions`, `POST /features/{id}/versions`, `POST /features/preview`, `POST /features/validate`, `GET /features/{id}/analytics` |
| Strategies | `GET/POST /strategies`, `GET /strategies/{id}/versions`, `POST /strategies/{id}/versions`, `POST /strategies/build` (spec → code), `GET /strategies/{id}/diff?from&to` |
| Runs | `POST /runs` (202 or the cached run), `GET /runs`, `GET /runs/{id}`, `/runs/{id}/trades`, `/equity?max_points`, `/chart?from&to`, `/stats`, `/distribution`, `POST /runs/{id}/query` (DuckDB SQL, row cap), `POST /runs/compare`, `POST /runs/{id}/explain/{trade_id}` |
| Studies | `POST /studies`, `POST /studies/{id}/estimate`, `GET /studies/{id}/trials`, `POST /studies/{id}/cancel` |
| Prop | `GET/POST /prop/rule-sets`, `/prop/rule-sets/{id}/versions`, `GET/POST /prop/policies`, `POST /prop/simulations`, `GET /prop/simulations/{id}` |
| Uploads | `POST /uploads` (multipart), `GET /uploads/{id}/inspect`, `POST /uploads/{id}/recipes`, `POST /uploads/from-url` |
| Agent | `GET/POST /agent/sessions`, `POST /agent/sessions/{id}/turns`, `POST /agent/turns/{id}/stop`, `GET /agent/sessions/{id}/messages`, `GET /proposals`, `POST /proposals/{id}/decision` |
| Jobs | `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `GET /streams/{stream_id}` (SSE) |
| Push | `POST /push/subscriptions`, `DELETE /push/subscriptions/{id}` |
| Health | `GET /healthz`, `GET /version` |

The web app's TypeScript types are generated from `web/openapi.json` by `openapi-typescript`; CI regenerates and fails on a diff.

## 8. Local server security

- Binds to `127.0.0.1` by default. Exposure on the Tailscale interface is opt-in in `config.toml`; the server never binds to `0.0.0.0`.
- Login by password (set on first run) creates a session cookie (`HttpOnly`, `Secure` when served over HTTPS, `SameSite=Strict`). A CSRF token guards state-changing requests. A bearer token is accepted for notebooks and scripts.
- Rate limit on login; passwords hashed with Argon2.
- Content Security Policy: `default-src 'self'; img-src 'self' data: blob:` (no remote images in chat).
- File access is confined to `FEFAT_HOME` and `FEFAT_DATA_DIR`; the API never takes raw filesystem paths from clients except for the import dialog, which is validated against allowed roots.
- Secrets (Anthropic API key, Databento API key, VAPID private key) live in the OS credential store via `keyring`, never in `config.toml`.

## 9. Environments

| Environment | What runs | Data |
| --- | --- | --- |
| `dev` | `just dev`: server with auto-reload + Vite dev server with proxy | Synthetic fixtures by default; real data under `FEFAT_DATA_DIR` when you choose |
| `test` | `just test`: Rust, Python, and web unit/integration tests; `just e2e`: Playwright against a seeded server | Synthetic only |
| `local` | `fefat up`: production build of the UI served by the server; Tailscale exposure optional | Your real data |
| `release` (P14) | CI builds wheels and installers, signed | — |

CI runs `just check` and `just test` on `windows-latest` and `ubuntu-latest` for every pull request, builds the `fefat_engine` wheel on both, and asserts identical golden-run hashes on both systems.

## 10. Seams that keep options open

| Seam | Interface | Today | Later |
| --- | --- | --- | --- |
| Executor | `Executor.run(ExecSpec) -> ExecResult` | subprocess | containers, if ever needed |
| Dispatcher | `submit(job_id)`, `cancel(job_id)` | local process pool | remote workers, cloud sync |
| Blob store | `BlobStore.put/get/list` over workspace paths | local files | optional cloud sync |
| Agent runtime | `AgentRuntime.run_turn(session, message, tools, emit)` | Messages API loop | Agent SDK or Managed Agents |
| Credential store | `secrets.get/set(name)` | Windows credential store | macOS keychain, Linux secret service |
| Licensing | `licence.check()` returns `ok` | always `ok` | licence keys (backlog) |

## 11. Conventions

- Time is nanoseconds since the Unix epoch, UTC, as `int64`; local-time rules (sessions, flat-by times) are converted to UTC instants per trade date before a run.
- Money and prices are integers in the engine (prices in Databento's 1e-9 units; money in micro-units of the account currency); floats appear only at the SDK boundary.
- Hashes are BLAKE3 (engine) and SHA-256 (app), hex, lower case.
- IDs: UUIDv7. Version numbers: integers starting at 1 per feature/strategy.
- Line endings LF everywhere (`.gitattributes`); paths through `pathlib`; project scripts are Python run through `uv run python` (bare `python` is a Store stub on this PC) plus `just` recipes; Claude Code hooks are Node scripts; the only shell file is the one-line git pre-commit launcher.
- Python: ruff + pyright strict for `fefat_app`, basic for `fefat`; Rust: clippy with `unwrap_used`, `panic`, `indexing_slicing` denied in core crates; TypeScript: strict.
