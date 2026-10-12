# Phase 5 — Backtesting in the app

**Goal.** The web MVP: the data catalog with sources, sync, and an import wizard for your own data, strategies with immutable versions, backtests as jobs, results you can read on desktop and phone, a trade review chart with markers and indicator panes, run comparison, version diffs, and a notification when a run finishes.

**You get.** Connect a data source, keep your products current, and import your own files from the app, create a strategy from a template, run it, inspect every trade on the chart, compare runs, and get a push notification on your phone.

**Depends on.** Phase 4.

**Open decisions for the kickoff.** Which of your real strategies to seed as the demo (a simple one you understand well); the metrics you want on the KPI cards first.

## Kickoff

```text
/phase-kickoff 5 — Read docs/masterplan/phases/P05-backtesting-app.md, docs/masterplan/01-architecture.md §5–§7, and docs/masterplan/02-engine-and-data.md §7. Ask me the open decisions. Reconcile the steps with the Phase 4 server, jobs, and executor; pin Lightweight Charts 5 and ECharts 6 versions; open the kickoff PR. Pull in the D-29 backlog items that target this phase (the robustness summary on the results page, the hypothesis field, the stress profile, the record of abandoned ideas), and load the `frontend-design` skill with `web/DESIGN.md` for the page steps.
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

### 5.3 Backtest job

Depends on: 5.2, 4.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

A backtest is a job: submitted through the API, executed through the executor and the engine, deduplicated by hash, with artifacts on disk and metrics in the database.

#### Prerequisites

- Steps 5.2 and 4.5 merged.

#### Prompt

```text
Masterplan step 5.3 — Backtest job.

Read docs/masterplan/01-architecture.md §6 and §7 (Runs). Implement `POST /v1/runs` (strategy version, params, config: instrument, timeframe, range, fidelity, fee table, slippage class, latency, reference capital): compute the run hash, return the existing run with 200 if it exists, otherwise create the run row and a `backtest` job (202). The job runs `ff.backtest.run` inside the executor (so user strategy code never loads in the server), writes artifacts (trade paths included) under the workspace, stores metrics and the fidelity summary in `runs`, records the data source used for each instrument (platform or imported; a `data_source` field in the config, platform by default where both exist) in the run's config and run.json,, and emits progress events (data loaded, features computed, engine running with percent, artifacts written). Implement `GET /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/cancel`.

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

### 5.4 Data catalog page and chart viewer

Depends on: 5.1, 4.3 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

You can see your data: what you have, how good it is, and the bars on a chart that loads by visible window.

#### Prerequisites

- Steps 5.1 and 4.3 merged.

#### Prompt

```text
Masterplan step 5.4 — Data catalog page and chart viewer.

Build the Data section of the web app: a catalog page in three parts — **Catalog products** (each with coverage by month as a small heat strip, quality status, last update, its source, and an Update action backed by `POST /v1/catalog/sync` that runs the sync from 1.9 as a `source_sync` job; paid downloads show the cost preview and need an explicit confirmation before anything is pulled; progress in the jobs drawer), **Sources** (the source guide from 1.9 with each source's terms and connection state, and a Connect action backed by `POST /v1/sources` that stores a key through the credential store and never shows it again), and **Your data** (imported datasets with the same columns; the import wizard arrives in 5.12) — plus instruments with tick size and point value, and a chart viewer: Lightweight Charts 5 candlesticks with a volume pane, instrument and timeframe pickers, a continuous/raw toggle, bars loaded by the visible range through `/v1/market/bars` with paging and caching, a crosshair readout, and session shading from the calendar. Wrap Lightweight Charts in a reusable `PriceChart` component with a stable API (series, panes, markers, primitives) that 5.9 and Phase 6 reuse. Phone: the chart is full width, pinch and drag work, pickers collapse into a sheet.

Playwright: open the catalog, connect a synthetic source, update a synthetic catalog product and see its coverage change, open the chart for the seeded synthetic instrument, scroll back, assert bars are fetched and rendered; desktop and phone.

Not in this step: indicators on the chart, trade markers.
```

#### Done means

1. Playwright specs pass on both projects with screenshots attached, including the connect and update flows.
2. Scrolling back on a year of 5-minute bars stays smooth (no request larger than 20,000 bars; requests are cached).
3. `PriceChart` is documented in `web/src/charts/README.md`.
4. An update that needs a paid Databento download never calls the download API without your confirmation (test with a mocked client).

#### Your checks

- Open the chart for ES 5-minute, scroll back a few weeks on your phone with one thumb; it should stay responsive and never trap the page scroll.

#### If it fails

- Timestamps off by hours: the chart expects UTC seconds; convert from ns and apply the display time zone in the UI, not in the API.

#### Amendment

2026-10-12 (D-37): the catalog page shows catalog products and the source guide with a Connect action instead of "platform data"; the sync job and endpoints were renamed.

### 5.5 Strategy page

Depends on: 5.2, 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Strategies are visible and editable in the app: code in an editor, saved as immutable versions with validation, plus history and a parameter form. The builder (Phase 6) generates code into this same editor.

#### Prerequisites

- Steps 5.2 and 5.4 merged.

#### Prompt

```text
Masterplan step 5.5 — Strategy page.

Build the Strategies section: a list (name, kind, latest version, last run); a strategy page with the code of the selected version in a reusable `CodeEditor` component (CodeMirror 6, Python syntax, editable, with a symbol bar above the phone keyboard), "Validate" (`POST /v1/strategies/validate`: import and signal-frame check in the executor, errors underlined by line) and "Save as new version" with a changelog (drafts kept in local storage until saved), a version history list with changelogs, a parameter form rendered from the version's JSON schema (a small schema-driven form renderer with number, boolean, enum, and string fields, validation messages, and defaults), and "Create from template" which copies a template into a new strategy with version 1. Phone: the editor scrolls inside its box and uses the visual viewport height; the form stacks.

Playwright: create a strategy from a template, see version 1, change the stop in the code, validate, save version 2, see both in the history; introduce a syntax error and see it underlined.

Not in this step: the builder (Phase 6), running (5.6), feature editing (6.2).
```

#### Done means

1. Playwright passes on desktop and phone with screenshots, including the save and syntax-error paths.
2. The schema-driven form renders every parameter type used by the templates and shows validation errors.
3. The form renderer and `CodeEditor` are reusable components used again in Phases 6, 7, and 9.
4. Validation runs only in the executor (test).

#### Your checks

- Create a strategy from a template on your phone; change one number in the code; validate; save version 2; the history shows two versions.

#### If it fails

- The iOS keyboard covering the editor: the editor container must use the visual viewport height; the symbol bar must stay above the keyboard.

### 5.6 Run launch and run list

Depends on: 5.3, 5.5 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

You can start a backtest from the strategy page and follow it to completion.

#### Prerequisites

- Steps 5.3 and 5.5 merged.

#### Prompt

```text
Masterplan step 5.6 — Run launch and run list.

Add a "Run backtest" dialog on the strategy page: instrument, data source (platform or your imported data, where both exist), timeframe, date range (with the data coverage shown so you cannot pick what you do not have), fidelity (auto by default), fee table, slippage class, parameters (the form from 5.5), and a cost-free "estimate" line (bars and ticks to process). Submitting calls `POST /v1/runs`; a cached run opens immediately with a "cached" badge. Build the Runs section: a list with status, strategy and version, range, key metrics once done, and live progress for running jobs via the stream; filters by strategy and status; cancel. The run page shell shows status and the config until results land (5.7).

Playwright: launch a run on synthetic data, watch progress reach 100%, land on the run page.

Not in this step: results views.
```

#### Done means

1. Playwright passes on both projects.
2. Launching an identical run shows the cached badge and opens the existing run.
3. Progress updates live on the run list for a running job; reload keeps it.

#### Your checks

- Launch a real run on your phone, lock the phone for a minute, unlock: the run page shows the progress or the result.

#### If it fails

- The date picker must use trade dates from the calendar, not browser-local dates, or ranges will be off by a day near midnight.

### 5.7 Results: metrics, equity, distributions

Depends on: 5.6 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

A finished run is readable at a glance: KPI cards, equity curve, drawdown, and distributions, with every number served by the API.

#### Prerequisites

- Step 5.6 merged.

#### Prompt

```text
Masterplan step 5.7 — Results: metrics, equity, distributions.

Implement `GET /v1/runs/{id}/equity?max_points` (min/max-bucketed downsampling of bar equity plus daily equity and drawdown), `GET /v1/runs/{id}/stats` (the metrics model plus breakdowns), and `GET /v1/runs/{id}/distribution` (histograms of trade P&L, R multiples, MAE/MFE, holding time, computed server-side). Build the run page: KPI cards (net P&L, profit factor, expectancy in R, win rate, max drawdown, Sharpe, trades, fidelity split), the equity and drawdown chart (ECharts, lazy-loaded), breakdown tables (by exit reason, hour, weekday, year, fidelity era), the fidelity-check deltas if present, and the distributions. Numbers come from the API; the client computes nothing. Phone: KPI cards in a 2-column grid, charts full width, tables scroll inside their boxes.

Contract test: every number on the page equals the SDK's `Run.metrics` for the same run (a Playwright test reads the DOM and compares with the API, and a pytest compares API with SDK).

Not in this step: trades table, chart with trades.
```

#### Done means

1. Contract tests pass (API equals SDK; DOM equals API).
2. Playwright passes on both projects with screenshots.
3. The equity endpoint returns at most `max_points` points and preserves the true max drawdown (test).

#### Your checks

- Open a real run on desktop and on the phone: the KPI cards show the same numbers as `run.metrics` in a notebook for the same run id.

#### If it fails

- Downsampling that loses the drawdown low means the bucketing is not min/max; fix the endpoint, not the chart.

### 5.8 Trade table

Depends on: 5.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Every trade is inspectable in a table with filters and sorting, ready to be linked to the chart.

#### Prerequisites

- Step 5.7 merged.

#### Prompt

```text
Masterplan step 5.8 — Trade table.

Implement `GET /v1/runs/{id}/trades` with keyset pagination (a cursor that continues from the last row seen, so paging stays fast on large tables), sorting (time, P&L, R, holding time, MAE, MFE), and filters (side, exit reason, date range, P&L sign, fidelity, ambiguous flag), reading the trades Parquet through DuckDB; and `POST /v1/runs/{id}/query` (a read-only DuckDB SELECT over the run's artifacts, row and byte caps, used later by the agent). Build the trades tab on the run page with TanStack Table and virtualisation: columns for entry and exit time and price, side, size, net P&L, R, MAE/MFE, exit reason, contract, fidelity, ambiguous; sticky header; column chooser; CSV export of the current filter; and a small "SQL" tab with a query box and a results grid for power users. Selecting a row emits a `selectedTrade` event that 5.9 consumes. Phone: a card list with the key columns and a filter sheet.

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

### 5.9 Trade review chart

Depends on: 5.8, 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, code-review · Security: no · Model hint: default

#### Purpose

Inspect any trade in context, on desktop and phone: a trader uses it to judge whether entries and exits happened where the strategy intended, so marker placement must be exact.

#### Prerequisites

- Steps 5.8 and 5.4 merged; a seeded run `demo-run-01` in the e2e fixtures.

#### Prompt

```text
Masterplan step 5.9 — Trade review chart.

Add a trade review chart to the run results page. Reuse the `PriceChart` wrapper from 5.4. Implement `GET /v1/runs/{id}/chart?from&to` returning the bars for the window, the strategy's feature series (from the signals artifact, limited to the columns the strategy used), and the fills and bracket levels for trades in the window. Markers use fill time and price from the fills ledger; the client computes no P&L. Draw entry-to-exit connectors and stop and target bands as chart primitives, and the feature series as indicator panes below the price. Selecting a table row (5.8) centres the chart on that trade; previous and next buttons step through trades. Add an "Explain" button on the selected trade backed by `POST /v1/runs/{id}/explain/{trade_id}` (runs `Run.explain` in the executor and returns the event list), shown as a readable timeline beside the chart. Load bars around the viewport so a 200,000-bar run stays responsive. At 390×844 the chart is full width, the table becomes a bottom sheet, and page scroll is never trapped.

Not in this step: drawing tools, multiple timeframes on one chart.
```

#### Done means

1. A Playwright spec passes for desktop and phone: open the demo run, select trade 3, the entry marker tooltip equals the table row's entry time and price, no console errors.
2. Contract test: every marker's time and price equals the fills ledger for the window (pytest over the chart endpoint); the explain endpoint's fills equal the ledger.
3. Desktop and phone screenshots and a 20-second recording are in the PR, confirmed by `ui-verifier`.

#### Your checks

- Watch the recording. Run `just dev` and click three trades: the arrow sits on the candle whose time is in the table. Open it on your phone and scroll past the chart with one thumb.

#### If it fails

- Markers one candle off: say "trade N is one bar late; check the bar-timestamp convention (ts_open versus ts_close) in the chart endpoint", not "fix the chart".
- Flaky test: refuse longer timeouts and ask for the cause.
- After two failed corrections, start a new session with a sharper prompt.

### 5.10 Run comparison, version diff, reproduce-run check

Depends on: 5.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Runs can be compared side by side, versions diffed, and any run reproduced to prove the pinning works.

#### Prerequisites

- Step 5.9 merged.

#### Prompt

```text
Masterplan step 5.10 — Run comparison, version diff, reproduce-run check.

Implement `POST /v1/runs/compare` (two to four run ids: metrics side by side with deltas, overlaid equity curves normalised to the reference capital, trade-count and exit-reason breakdown deltas) and a comparison page reachable from the run list (multi-select) with the overlay chart (ECharts) and a metrics table; a version diff view on the strategy page using `@codemirror/merge` (side-by-side on desktop, unified on phone) with the structured builder-spec diff when present; and a "Reproduce" action on a run that re-runs it with the pinned versions and snapshot and reports whether the trades table hash matches (a `reproduce` job).

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

### 5.12 Import wizard for your own market data

Depends on: 5.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: yes · Model hint: default

#### Purpose

Traders bring in their own market data from the app, on the PC or the phone: choose a file, map it, preview it, and import it with the same checks as the command line.

#### Prerequisites

- Step 5.4 merged (the wizard builds on its catalog page and on the importer from 1.10).

#### Prompt

```text
Masterplan step 5.12 — Import wizard for your own market data.

Read docs/masterplan/02-engine-and-data.md §1.8 and the importer and profiles from step 1.10. Implement `POST /v1/uploads` (multipart; size and type limits from config; stored under workspaces/default/uploads/<id>/ with a SHA-256; CSV, TSV, Parquet, and zip or gzip archives of them — Phase 7 reuses it for trade logs and Phase 10 extends it to other file types), `GET/POST /v1/import-profiles`, `POST /v1/imports/preview` (sample rows as they would be stored, the problems detected, and the calendar check's verdict, computed in the executor), and `POST /v1/imports` (an `import` job). Build the wizard in the Data section: choose a file (upload from the PC or the phone, or for large files a path under the import roots allowed in config), pick a preset or a saved profile or start a new one, map columns with a live preview table, set the time zone and bar stamping, pick or define the instrument (tick size, point value, currency, calendar), review the problems and the calendar check, and import with progress in the jobs drawer; the profile is saved for next time. Imported datasets appear under "Your data" in the catalog with their quality report, and charts and backtests can use them.

Playwright: import a synthetic CSV in a NinjaTrader-style layout with a new instrument, fix a deliberately wrong time zone after the preview flags it, finish, and open the dataset's chart; desktop and phone.

Not in this step: trade logs for the prop simulator (Phase 7), alternative non-price data (Phase 10).
```

#### Done means

1. Playwright passes on both projects with screenshots, including the time-zone correction.
2. Preview and import run in the executor, never in the server process (test).
3. A saved profile re-imports a second file in the same layout without any mapping (test).

#### Your checks

- On your PC, import a real export from your own charting platform with the wizard; then open the imported product's chart on your phone.

#### If it fails

- A preview that looks right with a calendar check that fails usually means the time zone or bar stamping is set wrong in the profile; the wizard should say which.

### 5.13 Phone pass, end-to-end suite, demo

Depends on: 5.10, 5.11, 5.12 · Plan mode: skip · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The MVP is coherent on the phone, the whole flow is covered by one end-to-end suite, and you can demo it.

#### Prerequisites

- Steps 5.10, 5.11, and 5.12 merged.

#### Prompt

```text
Masterplan step 5.13 — Phone pass, end-to-end suite, demo.

Walk every page of the app at 390×844 and at 1280×800 with the ui-verifier and fix layout, touch-target, and contrast issues found. Write one Playwright end-to-end flow: log in, connect a synthetic source and update a synthetic catalog product, import a synthetic CSV through the wizard, create a strategy from a template, run it on synthetic data, wait for completion, open results, select a trade, see it on the chart, create version 2 with a parameter change, run, compare. Record a 60-second demo video with Playwright and write docs/demo-mvp.md with the click path for me. Update docs/engine-guide.md with an "In the app" section.

Not in this step: new features.
```

#### Done means

1. The end-to-end flow passes on both projects in CI.
2. The ui-verifier reports no remaining phone issues (its report is attached).
3. `docs/demo-mvp.md` exists and the video is attached to the PR.

#### Your checks

- Follow `docs/demo-mvp.md` on your phone from start to finish.

#### If it fails

- Anything that needs pinch-zoom on the phone is a layout bug; report the page and the element.

## Phase exit

```text
/phase-exit 5 — Run the exit procedure for Phase 5: clean-clone suite including the end-to-end flow; /code-review high; /security-review; demo = docs/demo-mvp.md; retro; backlog groomed; tag phase-5 (web MVP).
```
