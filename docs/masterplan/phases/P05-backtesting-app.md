# Phase 5 — Backtesting in the app

**Goal.** The web MVP: the data catalog with sources, sync, and an import wizard for your own data, strategies with immutable versions, backtests as jobs, results you can read, a trade review chart with markers and indicator panes, run comparison, and version diffs. Connectors and sync stay deferred (D-38, D-93): your data comes in through the import wizard, and a product's Update runs its quality report.

**You get.** Connect a data source, keep your products current, and import your own files from the app, create a strategy from a template, run it, inspect every trade on the chart, compare runs. Connecting a source waits with the connectors (D-93), so a product stays current through the files you import.

**Depends on.** Phase 4.

**Kickoff (2026-11-10, pull request #64, D-93).** The steps were written in October, before Phases 1 to 4 wrote the code they build on, and assumed connectors, sync, and a phone (D-38, D-54). The SDK gives every dataset, catalog product, source, and instrument from the store and its YAML files (`ff.market.datasets()`, `fefat.market.status.product_status`, the source guide, `fefat.market.saved_instruments.instrument_table`), each reading its folders from the environment; the guide holds no connection state, and every dataset is an import. A strategy is a `SignalStrategy` built in code, with no saved form, version, parameter model, or hash. A run is a folder named by its run key, nine Parquet files and `run.json`, found again only by `Run.open` or the request lookup of step 3.7; nothing lists, compares, or reproduces runs or downsamples their equity, neither `ff.backtest.run` nor an import reports its progress, and `Run.explain` returns lines of text and fills. The app holds Phase 4's tables alone (migrations `0001` to `0003`), `index_workspace` indexing feature versions, the leak detector's reports, and import profiles; `JobKind` already names `backtest`, `catalog_sync`, `import`, and `reproduce`, while `works_of` runs `demo`, `feature_preview`, and `python_snippet`, the executor's kinds being the last two; every route keeps the 1 MiB body limit, and no multipart parser is installed; and the content security policy refuses the style elements that Radix's modal overlays and CodeMirror write (D-87). The web app's Data, Strategies, and Runs areas are placeholders, with no `src/charts/`, no code splitting (one bundle of 590 KB), and no formatter of figures; the harness runs both Playwright projects at 1280 by 800, `dev-proxy` on the login and jobs specs alone, and seeds the synthetic fixtures and a password, no strategy or run. Versions checked on 2026-11-10, each installed by the step in brackets with a decision line of its own (D-27): in `web/`, pinned exactly, `lightweight-charts` 5.2.1 (5.4); `codemirror` 6.0.2 with `@codemirror/state` 6.7.6, `@codemirror/view` 6.43.15, `@codemirror/language` 6.13.1, `@codemirror/lang-python` 6.2.1, and `@codemirror/lint` 6.9.7 (5.5); `echarts` 6.1.0 (5.7); `@tanstack/react-table` 9.3.1 and `@tanstack/react-virtual` 3.14.26 (5.8); and `@codemirror/merge` 6.12.3 (5.10); in the app, below their next major, `duckdb` 2.0.0 (5.8) and `python-multipart` 0.0.33 (5.12). Your answers (D-93): connectors and sync stay deferred, so data comes in through the import wizard, which also takes a Databento batch folder, and Update runs the quality report; the demo is the engine guide's breakout, with two templates written beside it, and none of your own strategies, since the repository is public until the phase's exit (D-80); the KPI cards are step 5.7's eight; and the policy allows inline styles from step 5.4, scripts staying locked. Conventions for every step of the phase:

- Workspace files stay the record, and the database indexes them (D-84): strategy versions are files that `ff.strategy` writes under `workspaces/default/strategies/<name>/v<n>.json`, runs are indexed from their folders, and `fefat db import-workspace` reads both, `index_workspace` taking its `FefatPaths` as a parameter.
- Each step creates the tables it first writes, in a migration of its own (D-83): 5.2 `strategies`, `strategy_versions`, and `strategy_version_features` (`0004`), 5.3 `runs` (`0005`), and 5.5 the abandoned mark's columns (`0006`). Steps 5.1 and 5.12 create none, since the SDK gives the datasets, the catalog, the guide, and the instruments from the store, and an upload's folder and a new instrument's file are their own records, so `datasets`, `dataset_snapshots`, `instruments`, `catalog_products`, `data_sources`, and `uploads` wait for a step that writes state of its own into them.
- A computation a notebook would want too, listing runs, downsampling equity, distributions, comparing, and reproducing, is a function of `fefat.backtest`, which the app's services call (D-27).
- No connector (D-38): every dataset is an import, a product's Update runs the quality report, and Connect and `POST /v1/sources` wait with the connectors (`BACKLOG.md`).
- A job kind gets a creating route of its own and its work in `works_of` (D-90), and code of yours runs in the executor through a spec kind of its own (D-91).
- From step 5.4 the policy allows inline styles, scripts staying `'self'` alone, so Radix's dialog, select, and menu and CodeMirror are used as they ship (D-93).
- The API sends no int64: instants as ISO 8601 in UTC, or whole seconds where a chart's axis wants them, since nanoseconds since the epoch pass the 2^53 that JavaScript's numbers hold exactly, and prices and money in the instrument's units, converted through `fefat.market.engine_units`, so that the web app never knows the engine's scales.
- Charts live in `web/src/charts/`, coloured from `web/DESIGN.md`'s tokens; ECharts and CodeMirror load lazily, the app's first code splitting; every figure comes from the API, shown by one shared formatter with tabular figures.
- "Playwright passes on both projects" reads as the desktop project at 1280 by 800, with the dev-proxy project keeping its own specs; no step has a phone layout (D-54); screenshots are copied to `docs/validation/screenshots/<step>/`.
- The harness's seed (`scripts/e2e_server.py`) grows with the steps: step 5.3 adds the demo strategy and its first run, which later specs call `demo-run-01`.

**Skills.** `software-design-principles` for every step; `designing-architecture` for each new seam: the catalog service (5.1), the strategy library and its index (5.2), the backtest job, the runs' index, and the executor's backtest kind (5.3), and uploads with the import job (5.12); `backtest-expert` for 5.3 and 5.7 to 5.10; `frontend-design:frontend-design`, `unslop`, and `contemporary-typeui` with `web/DESIGN.md` for the steps that build screens, 5.4 to 5.10, 5.12, and 5.13, each ending with unslop's audit and the Contemporary skill's checklist (D-77, D-88).

**Open decisions for the kickoff** (settled 2026-11-10, D-93)**.** Which of your real strategies to seed as the demo (a simple one you understand well); the metrics you want on the KPI cards first.

## Kickoff

```text
/phase-kickoff 5 — Read docs/masterplan/phases/P05-backtesting-app.md, docs/masterplan/01-architecture.md §5–§7, and docs/masterplan/02-engine-and-data.md §7. Ask me the open decisions. Reconcile the steps with the Phase 4 server, jobs, and executor; pin Lightweight Charts 5 and ECharts 6 versions; open the kickoff PR. Pull in the D-29 backlog items that target this phase (the robustness summary on the results page, the hypothesis field, the stress profile, the record of abandoned ideas), and load the `frontend-design`, `unslop`, and `contemporary-typeui` skills with `web/DESIGN.md` for the page steps.
```

## Steps

### 5.1 Schema and data catalog from the data folder

Depends on: 4.6 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The database knows about your data and your strategies, and the catalog is filled from the data folder automatically.

#### Prerequisites

- Phase 4 complete.

#### Prompt

```text
Masterplan step 5.1 — Schema and data catalog from the data folder.

Read docs/masterplan/01-architecture.md §5 and §7 (Data). Add a `catalog sync` job that scans FEFAT_DATA_DIR through the SDK store, upserts `datasets` (with their origin, sync or import, their provider, licence scope, and catalog version), `dataset_snapshots`, `instruments`, `catalog_products`, and `data_sources`, and records quality status from the Phase 1 reports; run it at server start and on demand. Implement `GET /v1/instruments`, `GET /v1/datasets`, `GET /v1/datasets/{id}/quality`, `GET /v1/catalog` (each catalog product with its status, coverage, last update, and source), `GET /v1/sources` (the source guide from 1.9 with each source's terms and connection state), and `GET /v1/market/bars` (instrument, timeframe, from, to, continuous flag, optional origin or provider where several datasets cover the instrument, the catalog's recommended source by default; returns columnar JSON, capped at 20,000 bars per request, with `nextFrom` for paging). Make the strategies and versions tables ready for 5.2 if 4.1 left gaps.

Tests: sync is idempotent; bars endpoint pages correctly and refuses unknown instruments; quality status flows through.

Not in this step: pages.
```

#### Done means

1. After `fefat up`, `GET /v1/datasets` lists your real datasets with ranges and fidelity coverage.
2. `GET /v1/market/bars` returns a day of 5-minute ES bars in under 300 ms warm (timed test on synthetic data).
3. Sync twice produces no duplicate rows (test).

#### Your checks

- Call `http://localhost:8765/v1/datasets` in the browser after login: your products appear with the right date ranges.

#### If it fails

- Slow sync on a large data folder: hash partitions lazily from the Phase 1 manifests rather than re-reading files.

#### Amendment

2026-10-12 (D-37): datasets carry an origin (sync or import) and a provider instead of `source: platform | user`; `platform_products` became `catalog_products` with `data_sources` beside it; `/v1/platform-data` became `/v1/catalog` and `/v1/sources`.

2026-11-10 (Phase 5 kickoff, D-93): `Depends on: 4.6` reads as Phase 4 complete, its exit included, 4.6 being skipped (D-54). The step creates no table: the SDK gives every row its endpoints need from the store, `ff.market.datasets()` each dataset with its provider, schema, fidelity, contracts, first and last trade date, quality, origin, licence scope, and last import, `fefat.market.status.product_status` each catalog product with its coverage and recommended source, the source guide each source, and `instrument_table` the instruments, the saved ones included, and D-83 keeps a table for the step that first writes state of its own into it. So `GET /v1/datasets`, `GET /v1/datasets/{id}/quality` (a dataset's id naming its provider, schema, and root), `GET /v1/catalog`, `GET /v1/sources` (the guide as it is, with no connection state until the connectors, D-38), and `GET /v1/instruments` read the SDK through a catalog service, over a `Store` the container builds once (D-27); `load`, `datasets`, and `product_status` gain a form that takes the store and the folders, under the one a notebook calls, which reads them from the environment (from `BACKLOG.md`). The catalog sync is the quality report run as the `catalog_sync` job, which `JobKind` already names, started by `POST /v1/catalog/sync` (202) for one product or all, as `fefat data quality` runs it, and never at the server's start; step 5.4's Update and step 5.12's import start it. A report reads `stale` when it is older than the partitions it covers, and not only when it was checked to an earlier trade date, so that a backfill of older months shows (from `BACKLOG.md`). Done means 3 reads: a sync run twice gives the same reports and lists each dataset once (test). `GET /v1/market/bars` reads `load`: its instrument a root or a contract's symbol, since `load` takes a contract as its symbol, `continuous`, and `provider`, the catalog's recommended source by default (D-49), `origin` taking `import` alone until the connectors; each bar carries its trade date, which step 5.4 shades sessions by, and the API sends no int64 (the phase's header). `just dev` restarts the server when a file under `python/` changes, and starts on a home seeded as the harness's is unless you name a `FEFAT_HOME`, as `01-architecture.md` §9 has it (from `BACKLOG.md`). The strategy tables are step 5.2's (D-83). Not in this step also: connectors and their tables.

2026-11-10 (step 5.1, D-94): as the step built it. `GET /v1/market/bars` takes its window in trade dates, `from` and `to`, as `load` takes its start and end; a page holds at most 20,000 bars, `load`'s bars of its own trade dates cut to those the datasets that build its timeframe hold, from a named contract's own first trade date, and `next_from`, the instant the next page opens at in ISO 8601 UTC, comes back as `from`, null on the last page, spelled in snake_case as every field of the API is. A bar carries its open in whole seconds, its trade date, its prices as floats in the instrument's units, its volume, and its contract. A dataset's id is `provider:schema:root`; an unknown instrument or dataset, and a sync of what the store lacks, answer 404, another refusal of the SDK 400 in its words, and an empty window 200 with empty columns. A dataset's quality gives the verdict of its root's report with the findings of every schema the verdict covers, the first 200 and their count; coverage by month waits in `BACKLOG.md`. A clean report reads stale once a partition of its dataset was written after the report. `load`'s store form is `fefat.market.series_source.series_source_in`, while `datasets` and `product_status` keep the forms that take the store since step 1.9, `dataset_status` and `product_status`. `just dev` serves `fefat-dev` in the temporary folder at port 8765, seeded as the harness's home, unless `FEFAT_HOME` is named, a named `FEFAT_DATA_DIR` staying its data, and starts its server again when the SDK's or the app's source changes. From the reviews: a sync that a queued or running one covers gives that job; an instant outside the session tables answers 400; with `continuous=false`, a contract that stopped trading before a page's first session has no rows on that page, though one `load` of the window gives it empty rows there; and a page caps the bars it sends, not the data it reads, which waits in `BACKLOG.md`.

### 5.2 Strategy versions API

Depends on: 5.1 · Plan mode: required · Reviews: step-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

Strategies and their immutable versions live in the app, with history and diffs, and the SDK and the app agree on what a version is.

#### Prerequisites

- Step 5.1 merged.

#### Prompt

```text
Masterplan step 5.2 — Strategy versions API.

Read docs/masterplan/01-architecture.md §5 (Code) and §7 (Strategies). Implement `GET/POST /v1/strategies`, `GET /v1/strategies/{id}/versions`, `POST /v1/strategies/{id}/versions` (code, optional builder spec, changelog; validates the code by importing it in the executor, extracts the parameter schema and pinned feature versions, computes the content hash; rejects edits to existing versions), `GET /v1/strategies/{id}/versions/{n}`, and `GET /v1/strategies/{id}/diff?from&to` (unified diff of code and a structured diff of the builder spec). Mirror the same for features (`/v1/features...`) so Phase 6 can build on it. Keep the SDK able to read and write versions through the same repository layer (`fefat_app.database.repositories`) so notebooks and the app never diverge.

Seed a "templates" set: two or three signal strategies from docs/engine-guide.md as starting points, served by `GET /v1/strategies/templates` (declare this literal route before the `/{id}` route, or FastAPI will treat "templates" as an id; test it).

Tests: insert-only enforcement through the API; diff correctness; validation rejects a strategy that references a missing feature version; the templates route resolves.

Not in this step: pages, the builder.
```

#### Done means

1. Creating two versions and diffing them works through the API (tests) and from a notebook through the repo layer.
2. A version with a syntax error is rejected with the error line.
3. Templates are listed by `GET /v1/strategies/templates`.

#### Your checks

- In the browser, open `/v1/strategies/templates` (or use the `/docs` page): the templates appear with their code.

#### If it fails

- Validation must run in the executor (subprocess), never by importing user code into the server process.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): workspace files stay the record (D-84), so there is no `fefat_app.database.repositories` for the SDK to share: `ff.strategy` saves, lists, and loads versions as `workspaces/default/strategies/<name>/v<n>.json`, created whole by `create_atomically` and never replaced, as the feature library keeps its versions, and the app saves through it, then indexes what was written in `strategies`, `strategy_versions`, and `strategy_version_features` (migration `0004`, triggers refusing an update or a delete of a version's row, as ADR-0020 has it); `fefat db import-workspace` indexes them too. A version holds the strategy's name, its number, its kind (`signal`), its code, its hypothesis, one sentence stating the edge, required (D-29, from `BACKLOG.md`), its parameter schema, the feature versions it pins (name, version, and hash, as a run pins them, D-79), its changelog, its creation time, and from Phase 6 its builder spec; its content hash covers the code, the parameter schema, and the pinned versions. The code is a module that gives a `SignalStrategy`, whose expressions may call Python, so that the code is the only complete record, as a feature's is (D-71); its parameters are a strict Pydantic model, as a feature's are, whose JSON schema is the version's, and step 5.3 counts them in the robustness summary (from `BACKLOG.md`). Validation runs the code in the executor through a spec kind of its own (D-91), within `POST /v1/strategies/{id}/versions` and alone as `POST /v1/strategies/validate`, which step 5.5's Validate calls, and returns the error with its line; at a save, the leak detector's lint reads the version's expressions for negative shifts, backward fills, and the like, as it reads a feature's code (from `BACKLOG.md`, whose line keeps a study's own columns for step 6.5). Done means 1's repository layer reads as `ff.strategy`. The templates of `GET /v1/strategies/templates` are your choice: the engine guide's breakout of "A strategy in one cell", and two written beside it in the guide, a mean reversion reading `ff.indicators.rsi` in a slot, so that the harness needs no saved feature, and an entry window with a flat-by time; each declares a parameter or two, so that step 5.5's form meets every type it renders. The word is the route's: the guide's execution template is `ff.Execution`. The feature routes read the index of step 4.1 and save through `ff.features.save`, their validation in the executor too. A password change revokes every API token, which outlived it (from `BACKLOG.md`, the Phase 4 exit's security review), and the settings page says so from step 5.4. Dependencies: none.

2026-11-11 (step 5.2, D-95): as the step built it. A version's code is a module whose function `strategy` gives the `SignalStrategy`, its parameters the function's own, each annotated and given its default, of which `ff.strategy.from_source` builds the strict model; validation builds the strategy with its defaults and its signal frame on bars that hold no rows, and a refusal names the line of the code, a syntax error's, the innermost of the code's lines that raised, or the line that defines `strategy`. A version also keeps the instrument and the timeframe its strategy names with its defaults; its pins are the feature versions its slots read with them, saved in the library at the save, its hash covering their hashes; and the same code saved again with the same hypothesis and changelog returns its version, while other words are refused, since a version never changes. A strategy's name is a lower-case identifier of at most 64 characters that Windows keeps for no device. The lint warns and never refuses, its rules on calls moved to `fefat.features.reading_ahead` as `BACKLOG.md` asked. The executor's kinds are `strategy_validation`, `strategy_save`, and `feature_save`, the runner saving through `ff.strategy.save` and `ff.features.save`, and the app indexes the library's versions alone before each save and once a version is saved (`index_library`), so that a leak detector's report the SDK refuses holds up no save. The routes' ids are the index rows' UUIDv7; a save answers 201 for a version it wrote and a version's save 200 for the same code saved before, 400 with the code's `line` for a refusal, and 409 for a name in use or files the index cannot follow; `POST /v1/strategies/validate` answers 200 with `valid` or `refused`; `POST /v1/features` takes the feature's name with its code; and a diff answers `earlier`, `later`, and `code_diff`, the builder spec's structured diff waiting for step 6.8. The templates are the modules of `fefat.strategy.starting_points`, written whole in the engine guide's "Strategy versions". A password that replaces another revokes every API token, a first one none. Not in this step also: `GET /v1/strategies/{id}` alone, which neither the Prompt nor `01-architecture.md` §7 lists, and indexing at `fefat up`'s start, which waits in `BACKLOG.md`.

### 5.3 Backtest job

Depends on: 5.2, 4.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

A backtest is a job: submitted through the API, executed through the executor and the engine, deduplicated by hash, with artifacts on disk and metrics in the database.

#### Prerequisites

- Steps 5.2 and 4.5 merged.

#### Prompt

```text
Masterplan step 5.3 — Backtest job.

Read docs/masterplan/01-architecture.md §6 and §7 (Runs). Implement `POST /v1/runs` (strategy version, params, config: instrument, timeframe, range, fidelity, fee table, slippage class, latency, reference capital): compute the run hash, return the existing run with 200 if it exists, otherwise create the run row and a `backtest` job (202). The job runs `ff.backtest.run` inside the executor (so user strategy code never loads in the server), writes artifacts (trade paths included) under the workspace, stores metrics and the fidelity summary in `runs`, records the dataset used for each instrument (its origin and provider; the catalog's recommended source by default where several datasets cover it) in the run's config and run.json, and emits progress events (data loaded, features computed, engine running with percent, artifacts written). Implement `GET /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/cancel`.

Tests: dedupe by hash; a failing strategy marks the run failed with the error; cancellation mid-run; artifacts match the SDK's own output for the same inputs (byte-identical trades table). Extend the e2e seed from 4.3 so the test server always has a completed run `demo-run-01` on synthetic data (later UI steps rely on it).

Not in this step: pages, result endpoints (5.7–5.8).
```

#### Done means

1. Submitting the same run twice returns the same id; artifacts exist under the workspace; metrics are in the database.
2. The app's run equals a notebook run of the same strategy and config (identical trades, test).
3. Progress events appear in the stream during a real run.

#### Your checks

- On the interactive API page (`/docs`, after login), submit a run of a template strategy with `POST /v1/runs`; watch `GET /v1/jobs` until it succeeds; `GET /v1/runs/{id}` shows metrics.

#### If it fails

- If the app and the notebook differ, the config defaults differ; the run config must be fully explicit and stored in run.json.

#### Amendment

2026-10-12 (D-37): a run records the dataset's origin and provider instead of a platform-or-imported `data_source`.

2026-11-10 (Phase 5 kickoff, D-93): a run's identity is its run key (D-62, D-83). `POST /v1/runs` takes a strategy version and the run's settings, which mirror `RunConfig` (fidelity, latency, slippage, limit fill, roll handling, fee table, capital, replay, provider, and contract), the instrument and the timeframe coming from the version's strategy and the dataset from the provider, `origin` being `import` for every dataset until the connectors (D-38); it answers 200 with the run that the request lookup of step 3.7 or the run folders already hold, and otherwise 202 with a row of `runs` (migration `0005`: a UUIDv7 id beside the unique `run_key`, the version, the settings, the status, the job, the origin `manual`, and, once saved, the metrics, the eras, the warnings, and the folder) and a `backtest` job. The job runs `ff.backtest.run` in the executor through a spec kind `backtest` (D-91), which builds the strategy from its version's code in the runner, so that the trader's code never loads in the server or a worker of the pool, and the row is indexed from `run.json` once the folder is whole; `fefat.backtest` gains the listing of saved runs, which the index and `fefat db import-workspace` read (D-84), and a run's record, request, and artifacts have their states checked against their `StrEnum`s on reading and their mappings held read-only (from `BACKLOG.md`). `ff.backtest.run` reports nothing as it goes, so the step gives it a callable told each stage, the data loaded, the features computed, the engine running, and the artifacts written, which the runner passes on as the job's progress; the engine's run is one call of the binding, so its percent is the stage's start and end unless the binding reports one. The robustness summary counts a version's declared parameters where it declares them (from `BACKLOG.md`): the count is an input of the metrics, so the run's key must cover it, the `engine-golden` skill deciding whether a version moves. The concurrency that jobs side by side open, from `BACKLOG.md`: a `.partial` folder skipped and removed after a day; a run's own snapshots passed to the engine cache's builder, and its partitions' digests checked; the feature cache's index written by two processes, and its prune, which passes over a folder without an index and the `.tmp` files a refused write leaves; and two saves of one new feature at once, the second returning the version already saved. A cancel stops the runner through the executor's check each second (D-91), so the pool keeps its workers, and one process per job moves to step 13.2 with its backlog line, this step updating the dispatcher's `shortcut:` comment, which names it. The harness's seed saves the demo template as the strategy `demo`, runs it on the synthetic fixtures through the SDK, and indexes both with `fefat db import-workspace` before `fefat up`, generating a longer synthetic span from a seed with `scripts/gen_fixtures.py` where steps 5.8 and 5.9 need more trades; `demo-run-01` is the specs' name for that strategy's first run, found through `GET /v1/runs`, since a row's id is new at each seed and a run's key is a hash. The home page's running-jobs card and the jobs drawer's backlog lines go to step 5.6. Not in this step also: the runs' pages.

2026-11-11 (step 5.3, D-96): as the step built it. `POST /v1/runs` takes `strategy_version_id`, the version's index row, its `parameters`, `start` and `end`, and `settings`, the SDK's own `RunConfig`; it indexes the library, checks the version's file as indexed, and looks the run up in the executor through a spec kind `run_lookup`, which builds the strategy from the version's code with its parameters, applies the settings, and finds the run its request made: 200 with that run, indexed where it was not, the row of a submission waiting on its request being that run; else 202 with the row of the same request waiting on an active job, or a new row with its queued `backtest` job, made in one transaction, a strategy whose expressions call Python queuing a job each time. A run's status is derived, not kept: `succeeded` once its folder is indexed, its job's before, so that the reaper's requeues never leave two statuses apart; the row keeps no folder, which is `runs/<run key>`, and no versions or snapshots, which `run.json` holds; it holds its job or its run key, the key unique, and triggers refuse its update or delete once the key is set, while a job whose run proved saved under another row's key removes its own row and names that one in its result. The job runs `ff.backtest.run` in the executor within 6 hours and 8 GiB (your answer), reporting its stages, 30 data loaded, 50 features and signals computed, 60 engine running, 100 artifacts written, or 100 the saved run opened, and indexes the folder into its row. A run of a saved version names it in `run.json` (`StrategyRecord.saved_version`, which `StrategyVersion.strategy(**parameters)` sets and a copy that changes a field drops), and the robustness summary counts the version's declared parameters through an optional field of the engine's config, which the run key covers while every config without it keeps its bytes. No run key, golden, or version moved; the request keys and the feature cache's keys move, as at every change of the SDK's code (`runtime_key`), so a run first asked for again after the update evaluates its signals and computes its features once more, then finds its saved run by its run key. A saved version whose code now reads another version of a feature than it pinned is refused. The data check is two looks at the store, what a run pins worked out before a bar is loaded and again once the engine, its reruns, and its metrics are done, a difference refusing the run before anything is saved, rather than the run's snapshots handed to the cache's builder, which reads whole months; digests as recorded (your answer), `fefat data verify` in `BACKLOG.md`. The engine cache builds a month under its contract's lock, SQLite's exclusive lock on `<contract>.lock` (your answer); the feature cache's index is read again and merged at its write, and its prune reaches folders without an index and `.tmp` files a day old; a feature save another process made first returns its version; and a stop, a target, or a trailing stop a multiple of a feature no slot holds, and a feature of the strategy's own code that reads its module, are refused at the save. The jobs' models move to `fefat_app.job_models`. The harness's seed saves the breakout template, on ES, as `demo` and runs it on the fixtures, 18 trades, indexed with `fefat db import-workspace`. From the reviews: the check made again under the engine cache's lock is proven by a test; a stop asked once a backtest's runner reports its run saved no longer cancels its job, which indexes the run; a cache's read of a file another process removes meanwhile passes over it; the seed stops where its index refuses; the checks written twice are kept once; and a feature the code defines is checked through a combination that reads it too. Not in this step also: filters and paging of `GET /v1/runs`, which step 5.6 adds.

### 5.4 Data catalog page and chart viewer

Depends on: 5.1, 4.3 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

You can see your data: what you have, how good it is, and the bars on a chart that loads by visible window.

#### Prerequisites

- Steps 5.1 and 4.3 merged.

#### Prompt

```text
Masterplan step 5.4 — Data catalog page and chart viewer.

Build the Data section of the web app: a catalog page in three parts — **Catalog products** (each with coverage by month as a small heat strip, quality status, last update, its source, and an Update action backed by `POST /v1/catalog/sync` that runs the sync from 1.9 as a `source_sync` job; paid downloads show the cost preview and need an explicit confirmation before anything is pulled; progress in the jobs drawer), **Sources** (the source guide from 1.9 with each source's terms and connection state, and a Connect action backed by `POST /v1/sources` that stores a key through the credential store and never shows it again), and **Your data** (imported datasets with the same columns; the import wizard arrives in 5.12) — plus instruments with tick size and point value, and a chart viewer: Lightweight Charts 5 candlesticks with a volume pane, instrument and timeframe pickers, a continuous/raw toggle, bars loaded by the visible range through `/v1/market/bars` with paging and caching, a crosshair readout, and session shading from the calendar. Wrap Lightweight Charts in a reusable `PriceChart` component with a stable API (series, panes, markers, primitives) that 5.9 and Phase 6 reuse.

Playwright: open the catalog, connect a synthetic source, update a synthetic catalog product and see its coverage change, open the chart for the seeded synthetic instrument, scroll back, assert bars are fetched and rendered.

Not in this step: indicators on the chart, trade markers.
```

#### Done means

1. Playwright specs pass on both projects with screenshots attached, including the connect and update flows.
2. Scrolling back on a year of 5-minute bars stays smooth (no request larger than 20,000 bars; requests are cached).
3. `PriceChart` is documented in `web/src/charts/README.md`.
4. An update that needs a paid Databento download never calls the download API without your confirmation (test with a mocked client).

#### Your checks

- Open the chart for ES 5-minute, scroll back a few weeks; it should stay responsive and never trap the page scroll.

#### If it fails

- Timestamps off by hours: the chart expects UTC seconds; convert from ns and apply the display time zone in the UI, not in the API.

#### Amendment

2026-10-12 (D-37): the catalog page shows catalog products and the source guide with a Connect action instead of "platform data"; the sync job and endpoints were renamed.

2026-11-10 (Phase 5 kickoff, D-93): no connector (D-38, your answer). Catalog products are the four of `catalog.yaml`, each with its coverage by month, quality status, last import, the datasets that hold it with their provider and origin, and the guide's recommended source; its Update starts step 5.1's `catalog_sync` job for the product, which runs the quality report with its progress in the jobs drawer, no download and no cost preview. Sources is the guide, what each source offers and costs, its terms and their page, its desktop use, and its presets, with an Import that opens step 5.12's wizard where a source has a preset, and no Connect, no `POST /v1/sources`, and no connection state. Your data lists the datasets of roots outside the catalog. Done means 4 and the connect flow wait with the connectors (`BACKLOG.md`), so the Playwright flow updates a synthetic product and sees its quality status change from unchecked. `PriceChart` lives in `web/src/charts/` over Lightweight Charts 5.2.1, `attributionLogo` on, its panes through version 5's pane API and its colours from `web/DESIGN.md`'s tokens; bars come by the visible range through TanStack Query, keyed by their window; sessions are shaded by the bars' trade dates; and the instrument and timeframe pickers may be Radix's selects. This step adds `style-src 'self' 'unsafe-inline'` to the server's policy (`fefat_app.http.security_headers`), the first step that needs it, with its decision line and a test that an inline script stays refused. The API sends the chart's instants in seconds, so If it fails' conversion from nanoseconds is the API's, and applying the display time zone alone is the UI's. The settings page says that a password change revokes the API tokens (step 5.2). Your checks read MES, the product on your PC, for ES. Dependencies: `lightweight-charts` 5.2.1.

### 5.5 Strategy page

Depends on: 5.2, 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Strategies are visible and editable in the app: code in an editor, saved as immutable versions with validation, plus history and a parameter form. The builder (Phase 6) generates code into this same editor.

#### Prerequisites

- Steps 5.2 and 5.4 merged.

#### Prompt

```text
Masterplan step 5.5 — Strategy page.

Build the Strategies section: a list (name, kind, latest version, last run); a strategy page with the code of the selected version in a reusable `CodeEditor` component (CodeMirror 6, Python syntax, editable), "Validate" (`POST /v1/strategies/validate`: import and signal-frame check in the executor, errors underlined by line) and "Save as new version" with a changelog (drafts kept in local storage until saved), a version history list with changelogs, a parameter form rendered from the version's JSON schema (a small schema-driven form renderer with number, boolean, enum, and string fields, validation messages, and defaults), and "Create from template" which copies a template into a new strategy with version 1.

Playwright: create a strategy from a template, see version 1, change the stop in the code, validate, save version 2, see both in the history; introduce a syntax error and see it underlined.

Not in this step: the builder (Phase 6), running (5.6), feature editing (6.2).
```

#### Done means

1. Playwright passes with screenshots, including the save and syntax-error paths.
2. The schema-driven form renders every parameter type used by the templates and shows validation errors.
3. The form renderer and `CodeEditor` are reusable components used again in Phases 6, 7, and 9.
4. Validation runs only in the executor (test).

#### Your checks

- Create a strategy from a template; change one number in the code; validate; save version 2; the history shows two versions.

#### If it fails

- The iOS keyboard covering the editor: the editor container must use the visual viewport height; the symbol bar must stay above the keyboard.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): `CodeEditor` lives in `web/src/ui/` over `codemirror` 6.0.2 with `@codemirror/lang-python` 6.2.1 and `@codemirror/lint` 6.9.7, which underlines step 5.2's error at its line, and loads lazily. Validate calls `POST /v1/strategies/validate` and Save as new version `POST /v1/strategies/{id}/versions` (step 5.2); a new version asks for its hypothesis, one sentence stating the edge, and the page shows it above the code (D-29, from `BACKLOG.md`); drafts in local storage are read through zod. The record of abandoned ideas (D-29, from `BACKLOG.md`): a strategy can be marked abandoned with the point where it broke and the lesson, kept as a file beside its versions that the index reads into columns of `strategies` (migration `0006`), and the list and the page show it, so that the library keeps its failures. The form renderer covers every parameter type the templates declare. If it fails' iOS keyboard leaves with the phone (D-54). Dependencies: the CodeMirror packages.

### 5.6 Run launch and run list

Depends on: 5.3, 5.5 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

You can start a backtest from the strategy page and follow it to completion.

#### Prerequisites

- Steps 5.3 and 5.5 merged.

#### Prompt

```text
Masterplan step 5.6 — Run launch and run list.

Add a "Run backtest" dialog on the strategy page: instrument, dataset (origin and provider, where several cover the instrument), timeframe, date range (with the data coverage shown so you cannot pick what you do not have), fidelity (auto by default), fee table, slippage class, parameters (the form from 5.5), and a cost-free "estimate" line (bars and ticks to process). Submitting calls `POST /v1/runs`; a cached run opens immediately with a "cached" badge. Build the Runs section: a list with status, strategy and version, range, key metrics once done, and live progress for running jobs via the stream; filters by strategy and status; cancel. The run page shell shows status and the config until results land (5.7).

Playwright: launch a run on synthetic data, watch progress reach 100%, land on the run page.

Not in this step: results views.
```

#### Done means

1. Playwright passes on both projects.
2. Launching an identical run shows the cached badge and opens the existing run.
3. Progress updates live on the run list for a running job; reload keeps it.

#### Your checks

- Launch a real run, close the tab for a minute, reopen it: the run page shows the progress or the result.

#### If it fails

- The date picker must use trade dates from the calendar, not browser-local dates, or ranges will be off by a day near midnight.

#### Amendment

2026-10-12 (D-37): the launch form picks a dataset by origin and provider instead of platform or imported data.

2026-11-10 (Phase 5 kickoff, D-93): the dialog may be Radix's modal dialog (D-93). It shows the instrument and the timeframe that the version's strategy names, rather than picking them, picks the dataset by provider where several hold the instrument, every one an import until the connectors (D-38), and names a contract for a run of one contract; the coverage and the estimate come from step 5.1's datasets. From `BACKLOG.md`: a Stress action submits, beside the base run, the variants the run's settings already express, more ticks of slippage, each a run of its own, while worst-case fills, commissions at 1.5 times, and the entry a bar late wait for step 11.6; Home shows the recent runs with their robustness verdict, in two column stacks, so that the running-jobs card grows alone, showing three jobs, then a line counting the rest; and the jobs, now that backtests run for minutes: Run again on an ended job's row, a row reading Reconnecting while its stream waits, rows that hold still under the pointer, a failure dot on the jobs button until the drawer opens, with a polite live region saying each followed job's end and a job's error in your words with what to do, the list asked again when the window gets the focus, and one stream of every job's events per tab, or a list that gives each job's last event id, its login checked at each read; and the design review's two open choices, the drawer closing at any click outside or staying open beside the work, and a `title` on the top bar's icon buttons. Done means 1's two projects read as the phase's header says.

### 5.7 Results: metrics, equity, distributions

Depends on: 5.6 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

A finished run is readable at a glance: KPI cards, equity curve, drawdown, and distributions, with every number served by the API.

#### Prerequisites

- Step 5.6 merged.

#### Prompt

```text
Masterplan step 5.7 — Results: metrics, equity, distributions.

Implement `GET /v1/runs/{id}/equity?max_points` (min/max-bucketed downsampling of bar equity plus daily equity and drawdown), `GET /v1/runs/{id}/stats` (the metrics model plus breakdowns), and `GET /v1/runs/{id}/distribution` (histograms of trade P&L, R multiples, MAE/MFE, holding time, computed server-side). Build the run page: KPI cards (net P&L, profit factor, expectancy in R, win rate, max drawdown, Sharpe, trades, fidelity split), the equity and drawdown chart (ECharts, lazy-loaded), breakdown tables (by exit reason, hour, weekday, year, fidelity era), the fidelity-check deltas if present, and the distributions. Numbers come from the API; the client computes nothing.

Contract test: every number on the page equals the SDK's `Run.metrics` for the same run (a Playwright test reads the DOM and compares with the API, and a pytest compares API with SDK).

Not in this step: trades table, chart with trades.
```

#### Done means

1. Contract tests pass (API equals SDK; DOM equals API).
2. Playwright passes on both projects with screenshots.
3. The equity endpoint returns at most `max_points` points and preserves the true max drawdown (test).

#### Your checks

- Open a real run: the KPI cards show the same numbers as `run.metrics` in a notebook for the same run id.

#### If it fails

- Downsampling that loses the drawdown low means the bucketing is not min/max; fix the endpoint, not the chart.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): the KPI cards are the eight as written (your answer), in `web/DESIGN.md`'s stat sizes at weight 700, which ships with them. Under them stands the robustness summary (D-29, from `BACKLOG.md`): its five scores of 20, their total, the verdict, the red flags that fired, which of 30, 100, and 200 trades the run reaches, and `fragile_to_slippage` beside the verdict, all of which `Metrics.robustness` holds. ECharts 6.1.0 lives in `web/src/charts/`, loaded lazily and coloured from the tokens, and every figure comes from the API through one shared formatter. The equity downsampling and the distributions are functions of `fefat.backtest` over a run's equity and trades, which the API serves, each bucket keeping its lowest and highest so that the drawdown's trough survives. Your checks' run id is the row's `run_key`, which names the folder a notebook opens with `Run.open`. Dependencies: `echarts` 6.1.0.

### 5.8 Trade table

Depends on: 5.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Every trade is inspectable in a table with filters and sorting, ready to be linked to the chart.

#### Prerequisites

- Step 5.7 merged.

#### Prompt

```text
Masterplan step 5.8 — Trade table.

Implement `GET /v1/runs/{id}/trades` with keyset pagination (a cursor that continues from the last row seen, so paging stays fast on large tables), sorting (time, P&L, R, holding time, MAE, MFE), and filters (side, exit reason, date range, P&L sign, fidelity, ambiguous flag), reading the trades Parquet through DuckDB; and `POST /v1/runs/{id}/query` (a read-only DuckDB SELECT over the run's artifacts, row and byte caps, used later by the agent). Build the trades tab on the run page with TanStack Table and virtualisation: columns for entry and exit time and price, side, size, net P&L, R, MAE/MFE, exit reason, contract, fidelity, ambiguous; sticky header; column chooser; CSV export of the current filter; and a small "SQL" tab with a query box and a results grid for power users. Selecting a row emits a `selectedTrade` event that 5.9 consumes.

Tests: pagination and filters in pytest; the query endpoint rejects writes and unbounded queries; Playwright selects a trade and asserts the event.

Not in this step: the chart.
```

#### Done means

1. Pagination, sorting, and filter tests pass; a 50,000-trade synthetic run pages without loading everything.
2. Playwright passes on both projects.
3. CSV export matches the API filter (test).

#### Your checks

- On a real run, filter to losing trades with exit reason `stop`, sort by MAE: the worst-MAE trades are at the top.

#### If it fails

- DuckDB reading the Parquet from the workspace path must use a read-only connection and never lock the SQLite file.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): `duckdb` 2.0.0, below 3, with its decision line, reads a run's Parquet files through a read-only connection of its own, never the SQLite file, for the keyset pages, the sorting, the filters, the CSV export, which the API serves under the page's filter, and `POST /v1/runs/{id}/query`; `@tanstack/react-table` 9.3.1 and `@tanstack/react-virtual` 3.14.26 build the table; the column chooser may be a Radix menu (D-93); and the 50,000-trade run is generated by its test in a temporary folder, never committed. The columns are those of the run's `trades` (`fefat.backtest.schemas`: the entry's and the exit's instants and prices, side, lots, net P&L, R, MAE and MFE, exit reason, the entry's and the exit's contracts, and path fidelity), sent as the phase's header says; a trade's fidelity and its ambiguous flag come from its fills, which the query joins, since `trades` holds neither. The higher-contrast mode lands with this first dense table (from `BACKLOG.md`): a `prefers-contrast: more` block that raises the hairlines and the muted text, and, where Windows forces colours, the current sidebar row and a job's bar in `Highlight`, the bar's track bordered in `CanvasText`. Dependencies: `duckdb`, `@tanstack/react-table`, and `@tanstack/react-virtual`.

### 5.9 Trade review chart

Depends on: 5.8, 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer, code-review · Security: no · Model hint: default

#### Purpose

Inspect any trade in context: a trader uses it to judge whether entries and exits happened where the strategy intended, so marker placement must be exact.

#### Prerequisites

- Steps 5.8 and 5.4 merged; a seeded run `demo-run-01` in the e2e fixtures.

#### Prompt

```text
Masterplan step 5.9 — Trade review chart.

Add a trade review chart to the run results page. Reuse the `PriceChart` wrapper from 5.4. Implement `GET /v1/runs/{id}/chart?from&to` returning the bars for the window, the strategy's feature series (from the signals artifact, limited to the columns the strategy used), and the fills and bracket levels for trades in the window. Markers use fill time and price from the fills ledger; the client computes no P&L. Draw entry-to-exit connectors and stop and target bands as chart primitives, and the feature series as indicator panes below the price. Selecting a table row (5.8) centres the chart on that trade; previous and next buttons step through trades. Add an "Explain" button on the selected trade backed by `POST /v1/runs/{id}/explain/{trade_id}` (runs `Run.explain` in the executor and returns the event list), shown as a readable timeline beside the chart. Load bars around the viewport so a 200,000-bar run stays responsive. At 390×844 the chart is full width, the table becomes a bottom sheet, and page scroll is never trapped.

Not in this step: drawing tools, multiple timeframes on one chart.
```

#### Done means

1. A Playwright spec passes: open the demo run, select trade 3, the entry marker tooltip equals the table row's entry time and price, no console errors.
2. Contract test: every marker's time and price equals the fills ledger for the window (pytest over the chart endpoint); the explain endpoint's fills equal the ledger.
3. Screenshots and a 20-second recording are in the PR, confirmed by `ui-verifier`.

#### Your checks

- Watch the recording. Run `just dev` and click three trades: the arrow sits on the candle whose time is in the table.

#### If it fails

- Markers one candle off: say "trade N is one bar late; check the bar-timestamp convention (ts_open versus ts_close) in the chart endpoint", not "fix the chart".
- Flaky test: refuse longer timeouts and ask for the cause.
- After two failed corrections, start a new session with a sharper prompt.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): `demo-run-01` is the specs' name for the seeded demo strategy's first run (step 5.3), found through the runs list. The chart reuses `PriceChart`: its markers from the run's `fills`, its connectors and its stop and target bands as Lightweight Charts 5 primitives, and its panes from the strategy's feature columns in `signals`. A trade's id is its `entry_order`, as `Run.explain` takes it. Explain runs `Run.explain` as a job of a new kind, `explain`, its work in `works_of` (D-90), since a replay through the reference engine can take seconds; it runs no code of yours, only the run's saved spec and signals, so it needs no executor spec kind. `POST /v1/runs/{id}/explain/{trade_id}` answers 202 with the job, whose result is the explanation, which Done means 2 reads. `Explanation` keeps the reference engine's log entries, an instant, a kind, an order, a rule, and a text each, beside its lines, so that the timeline is read as data; its refusals, TBBO, fills on two fidelities, prints across a roll, an entry by reversal, and data or settings changed since the run, read in your words; and its replay searches the trade date before for the mark it starts from, where a session's first bucket holds no print or bar (from `BACKLOG.md`). The layout at 390 by 844 leaves with the phone (D-54).

### 5.10 Run comparison, version diff, reproduce-run check

Depends on: 5.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Runs can be compared side by side, versions diffed, and any run reproduced to prove the pinning works.

#### Prerequisites

- Step 5.9 merged.

#### Prompt

```text
Masterplan step 5.10 — Run comparison, version diff, reproduce-run check.

Implement `POST /v1/runs/compare` (two to four run ids: metrics side by side with deltas, overlaid equity curves normalised to the reference capital, trade-count and exit-reason breakdown deltas) and a comparison page reachable from the run list (multi-select) with the overlay chart (ECharts) and a metrics table; a version diff view on the strategy page using `@codemirror/merge` (side-by-side, unified in a narrow window) with the structured builder-spec diff when present; and a "Reproduce" action on a run that re-runs it with the pinned versions and snapshot and reports whether the trades table hash matches (a `reproduce` job).

Tests: compare endpoint math; reproduce on a synthetic run matches; Playwright for the compare page and the diff view on both projects.

Not in this step: studies (Phase 11).
```

#### Done means

1. Playwright passes for compare and diff on both projects with screenshots.
2. The reproduce job reports a match for a synthetic run and for one of your real runs.
3. The compare endpoint's deltas equal the difference of the stored metrics (test).

#### Your checks

- Create version 2 of a strategy (change a stop), run it, compare with version 1: the equity overlay and the metric deltas make sense; open the diff: the stop change is highlighted.

#### If it fails

- A reproduce mismatch on real data means something was not pinned (a fee table or the calendar override file); the run config must capture it.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): `@codemirror/merge` 6.12.3 shows the diff side by side, the unified form of a narrow window leaving with the phone (D-54). Comparing and reproducing are functions of `fefat.backtest` that the app serves: the compare's deltas are differences of the stored metrics, and its curves each run's `equity_daily` over its capital; the `reproduce` job, a kind `JobKind` already names, runs a run's request again with its pinned versions and snapshots into a folder of its own, past the request lookup and the saved run, through step 5.3's `backtest` spec kind, since it builds the strategy from its version's code, and compares its trades table's hash (`fefat_engine.table_hash`) with the saved run's. Dependencies: `@codemirror/merge`.

### 5.11 Notifications on completion

Depends on: 5.6, 4.6 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

Your phone tells you when a run finishes, even with the app closed.

#### Prerequisites

- Steps 5.6 and 4.6 merged; the app installed on your phone.

#### Prompt

```text
Masterplan step 5.11 — Notifications on completion.

Implement web push: VAPID keys (the key pair that identifies your server to the browsers' push services) generated on first run and stored in the credential store, `POST/DELETE /v1/push/subscriptions`, a service-worker push handler that shows "Run <name> finished: net P&L …" and opens the run page on tap, a settings toggle that requests permission on a tap (required on iOS), and a generic `notify` hook in the job runner where each job kind registers its own message and link: register `backtest` completion and failure now (7.10 registers prop simulations; 12.2 the rest). Send with pywebpush. Document the iOS requirements (16.4+, installed app, permission from a user gesture).

Tests: subscription storage; the job hook enqueues a push; the service worker handler is unit-tested with a fake push event.

Not in this step: notification preferences per kind (Phase 12).
```

#### Done means

1. Tests pass; the settings toggle subscribes and unsubscribes.
2. A real run started from the phone produces a notification on the locked phone; tapping it opens the run (screenshot or photo in the PR).

#### Your checks

- Enable notifications on your phone, start a run, lock the phone: the notification arrives when the run finishes.

#### If it fails

- No notification on iOS: the app must be opened from the home screen icon (standalone) and permission requested from a tap; Safari tabs do not receive push.

#### Amendment

2026-10-23 (D-54): skipped. Web push existed for the phone; a finished run shows in the jobs drawer (4.4) and on the run page. Notifications and the `notify` hook are the backlog's phone item, so 7.10 registers no job kind with it.

### 5.12 Import wizard for your own market data

Depends on: 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: yes · Model hint: default

#### Purpose

Traders bring in their own market data from the app: choose a file, map it, preview it, and import it with the same checks as the command line.

#### Prerequisites

- Step 5.4 merged (the wizard builds on its catalog page and on the importer from 1.10).

#### Prompt

```text
Masterplan step 5.12 — Import wizard for your own market data.

Read docs/masterplan/02-engine-and-data.md §1.8 and the importer and profiles from step 1.10. Implement `POST /v1/uploads` (multipart; size and type limits from config; stored under workspaces/default/uploads/<id>/ with a SHA-256; CSV, TSV, Parquet, and zip or gzip archives of them — Phase 7 reuses it for trade logs and Phase 10 extends it to other file types), `GET/POST /v1/import-profiles`, `POST /v1/imports/preview` (sample rows as they would be stored, the problems detected, and the calendar check's verdict, computed in the executor), and `POST /v1/imports` (an `import` job). Build the wizard in the Data section: choose a file (upload, or for large files a path under the import roots allowed in config), pick a preset or a saved profile or start a new one, map columns with a live preview table, set the time zone and bar stamping, pick or define the instrument (tick size, point value, currency, calendar), review the problems and the calendar check, and import with progress in the jobs drawer; the profile is saved for next time. Imported datasets appear under "Your data" in the catalog with their quality report, and charts and backtests can use them.

Playwright: import a synthetic CSV in a NinjaTrader-style layout with a new instrument, fix a deliberately wrong time zone after the preview flags it, finish, and open the dataset's chart.

Not in this step: trade logs for the prop simulator (Phase 7), alternative non-price data (Phase 10).
```

#### Done means

1. Playwright passes on both projects with screenshots, including the time-zone correction.
2. Preview and import run in the executor, never in the server process (test).
3. A saved profile re-imports a second file in the same layout without any mapping (test).

#### Your checks

- On your PC, import a real export from your own charting platform with the wizard; then open the imported product's chart.

#### If it fails

- A preview that looks right with a calendar check that fails usually means the time zone or bar stamping is set wrong in the profile; the wizard should say which.

#### Amendment

2026-11-10 (Phase 5 kickoff, D-93): `POST /v1/uploads` reads multipart forms through `python-multipart` 0.0.33, below 1, with its decision line, under a body limit of its own above the 1 MiB every other route keeps, and stores each file under `workspaces/default/uploads/<id>/` (`FefatPaths` gains the folder) with an `upload.json` of its name, size, SHA-256, and time; the folder is the record, and no `uploads` table arrives until Phase 10 writes state into one (D-83). A large file, or a Databento batch folder, which the wizard imports through the importer of step 1.6 since your bulk history comes in them (`docs/data-inventory.md`), is a path under the `import_roots` of `config.toml`, which this step reads first (D-85). The preview runs `preview_file` in the executor through a spec kind of its own, and the `import` job, a kind `JobKind` already names, hands the executor an import spec kind over `import_file` or `import_databento`, so that a file's size meets the executor's memory limit rather than ending a worker of the pool (D-90); neither importer reports progress, so the job reports its stages, the file read, the partitions written, and the quality report of step 5.1's sync. A new instrument is saved through `fefat.market.saved_instruments` under the data folder's `instruments/`, with no table (D-84); profiles stay files under `profiles/`, saved through `save_profile` and indexed (D-84). From `BACKLOG.md`: one writer of the raw manifest, a lock, since imports now run as jobs beside other writers; bars that keep the trade dates of the calendar they were imported with, dated again or refused after a calendar change; a file with bars in a daily break refused for those bars, with their dates, rather than for an offset; and a profile's error from Polars read as a problem of the preview, never a traceback. Your checks gain: export the three NinjaTrader MNQ contracts the store lacks (MNQZ2020, MNQH2024, and MNQH2025) again, and import those that read clean (from `BACKLOG.md`).

### 5.13 End-to-end suite and demo

Depends on: 5.10, 5.12 · Plan mode: skip · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

The MVP is coherent, the whole flow is covered by one end-to-end suite, and you can demo it.

#### Prerequisites

- Steps 5.10 and 5.12 merged.

#### Prompt

```text
Masterplan step 5.13 — End-to-end suite and demo.

Walk every page of the app at 1280×800 with the ui-verifier and fix the layout and contrast issues found. Write one Playwright end-to-end flow: log in, connect a synthetic source and update a synthetic catalog product, import a synthetic CSV through the wizard, create a strategy from a template, run it on synthetic data, wait for completion, open results, select a trade, see it on the chart, create version 2 with a parameter change, run, compare. Record a 60-second demo video with Playwright and write docs/demo-mvp.md with the click path for me. Update docs/engine-guide.md with an "In the app" section.

Not in this step: new features.
```

#### Done means

1. The end-to-end flow passes in CI.
2. The ui-verifier reports no remaining issues (its report is attached).
3. `docs/demo-mvp.md` exists and the video is attached to the PR.

#### Your checks

- Follow `docs/demo-mvp.md` from start to finish.

#### If it fails

- Anything that scrolls sideways at 1280×800 is a layout bug; report the page and the element.

#### Amendment

2026-10-12 (D-37): the end-to-end flow connects a synthetic source and updates a catalog product instead of a platform product.

2026-10-23 (D-54): no phone pass and no dependency on 5.11; the walk is at desktop size only.

2026-11-10 (Phase 5 kickoff, D-93): the flow runs without a connector: log in, update a synthetic catalog product and see its quality job end, import a synthetic CSV through the wizard, create a strategy from a template, run it on synthetic data, wait for completion, open the results, select a trade and see it on the chart, create version 2 with a parameter change, run it, and compare. CI's Ubuntu leg already runs `just e2e` (D-92). The engine guide's "In the app" section names the templates of step 5.2.

## Phase exit

```text
/phase-exit 5 — Run the exit procedure for Phase 5: clean-clone suite including the end-to-end flow; /code-review high; /security-review; demo = docs/demo-mvp.md; retro; backlog groomed; the upgrade step with the majors held for it (BACKLOG.md); the repository returned to private (D-80); tag phase-5 (web MVP).
```
