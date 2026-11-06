# Phase 4 — Local app

**Goal.** The application skeleton on your PC: a SQLite-backed local server with login, a React web shell, a job runner with resumable progress streams, and a subprocess executor for user code. Phone access is deferred until FEFAT is fully functional (D-54).

**You get.** `fefat up`, log in from your browser, run a demo job and watch its progress survive a reload.

**Depends on.** Phase 3 (the SDK exists; the app wraps it).

**Kickoff (2026-11-06, pull request #56, D-83, D-84).** The steps were written before Phases 1 to 3 wrote the code the app wraps. `fefat_app` holds the `fefat` command alone (`cli.py`, with `fefat data` and `fefat cache` in argparse, and `cache_commands.py`): no `ports.py`, `container.py`, `database/`, `jobs/`, `executor.py`, `credentials.py`, `http/`, or `services/` yet, and none of the server's libraries is installed. `fefat.config` resolves `FEFAT_HOME` and `FEFAT_DATA_DIR` and reads no `config.toml`. The SDK keeps what it saves as files under `FEFAT_HOME`: feature versions, the leak detector's reports, import profiles, and saved runs named by their run key with a lookup of their requests; nothing carries a UUID. `web/` is create-vite's scaffold, React with TypeScript, oxlint, and vitest, without Tailwind, a router, a query library, an API client, Playwright, or a formatter, and no `ui-verifier` agent exists. Versions checked on 2026-11-05, which each step installs with a decision line of its own: for the server fastapi 0.162.0, uvicorn 0.54.0, sqlalchemy 2.1.8, alembic 1.20.1, keyring 25.7.0, argon2-cffi 25.1.0, and httpx 0.28.1 for the tests; for `web/` vite 8.3.6, react and react-dom 19.3.1, typescript 6.0.3 with @types/node 24.19.2 (TypeScript 7 and @types/node 26 held, D-83), tailwindcss and @tailwindcss/vite 4.3.4, the shadcn CLI 4.23.0, @tanstack/react-router 1.170.46 with @tanstack/router-plugin 1.168.48, @tanstack/react-query 5.106.1, openapi-typescript 7.13.0, openapi-fetch 0.17.0, react-hook-form 7.91.0, zod 4.6.7, lucide-react 1.69.0, @playwright/test 1.65.0, vitest 5.1.0, oxlint 1.91.0, and oxfmt 0.76.0, pinned exactly while in beta. Conventions for every step of the phase: workspace files stay the record of what the SDK saves, and the database indexes them (D-84); the seams are `typing.Protocol`s in `fefat_app/ports.py`, built once in `container.py` from `config.toml` and reached through FastAPI dependencies (D-27), and `fefat_app.services` imports neither FastAPI nor SQLAlchemy, which an import-linter contract holds from step 4.2; frozen Pydantic models at every boundary and a `StrEnum` for every state, under pyright's strict mode; ids are UUIDv7; every folder under `FEFAT_HOME` comes from `FefatPaths`; the server listens on 127.0.0.1 alone (D-54); and a setup change a step needs (a hook, a permission rule, an editor setting) goes in a commit of its own before the step's work. The name, the icon, the port, where versions live, and the design brief below are your answers (D-83).

**Skills.** `software-design-principles` for every step; `designing-architecture` for each new package or seam: the database, the credential store, the ports, and the container (4.1), the HTTP ring and the services (4.2), the jobs (4.4), and the executor (4.5); `frontend-design:frontend-design` and `unslop` for the steps that build screens, 4.3 and 4.4, with `web/DESIGN.md` once step 4.3 has written it (D-77).

**Open decisions for the kickoff** (settled 2026-11-06, D-83)**.** The app's display name and icon placeholder; the default port (8765 suggested); the design brief for `web/DESIGN.md` (D-28): who uses it, the job it does (a research terminal: dense numbers, charts, long desk sessions), what you like and dislike in the trading tools you use today, light or dark by default, and any reference to follow exactly.

## Design brief (2026-11-06)

Collected at the kickoff for step 4.3, which writes `web/DESIGN.md` from it (D-28, `08-code-design.md` §5). Your words here win over `web/DESIGN.md`, then unslop's values, then the `frontend-design` skill's defaults (D-77).

- **Who and what.** You now, and other futures and crypto traders later. FEFAT is a research terminal read for hours at a desk, dense with numbers and charts, often beside a charting platform.
- **Name and icon.** FEFAT everywhere: each page's title in the browser's tab names the page, then FEFAT, and the login page shows FEFAT with "feature engineering for algorithmic trading" small beneath it. The icon is a placeholder until Phase 14: an F monogram on a neutral tile, one SVG drawn in the accent.
- **Theme.** Dark by default and tuned first, with a light theme in the settings.
- **Reference.** None to follow exactly. Step 4.3 derives the direction from the product with unslop and takes unslop's exact values where this brief is silent.
- **Keep.** Calm surfaces, with colour only where it means something: neutral chrome and one accent, used rarely (the primary action, the selection, the one figure that matters), and the colour in the charts and the figures. Dense, scannable tables: compact rows, tabular figures in one format per column, numbers aligned right, many rows on one screen.
- **Avoid.** Red and green on everything: they mark the sign of a profit or loss and an alert, nothing else. Cluttered toolbars and nested dialogs: few controls in view, and settings one level deep. Small, low-contrast text: every figure and label, muted ones included, at a readable size and contrast. Interruptions: inline edits and undo rather than modals and confirmations for routine actions, and a confirmation only where an action cannot be undone.
- **Type.** One bundled sans with tabular figures for the interface and one monospace for code, hashes, and the editor, such as IBM Plex Sans or Inter with JetBrains Mono or IBM Plex Mono, all under the SIL Open Font License. The font files ship with the app, since the content security policy allows no remote font (`01-architecture.md` §8).
- **Motion.** The floor of one deliberate motion per screen counts the motion the app starts by itself: an entrance, an automatic transition, a pulsing mark. Feedback to your own input does not count: a press, an expand, a progress bar moving, the theme's cross-fade. Reduced motion is respected.
- **Accent.** Step 4.3 derives it from the direction, checks its contrast on the dark neutrals, and shows it in its first screenshots, where you can change it as one token.
- **Home.** The app opens on a home page: a dashboard of widgets, each linking to its page, the strategy builder, the feature lab, the backtester, and the data import. Its first widgets are the recent runs with their robustness verdict, the feature library, and the running jobs. Step 4.3 builds the page with a placeholder in each widget, step 4.4 fills the running jobs, and the steps that build the other pages fill theirs (`BACKLOG.md`).
- **The design reviewer's notes** (its first run, 2026-10-10, from `BACKLOG.md`): tabular numbers; a spacing scale in `rem` with page gutters, so that no text touches the window's edge; `color-scheme` in a meta tag as well as in the CSS, so that the dark theme never paints white first; a cross-fade when the theme switches; and a pressed state and a 44 px target on every control, the safe-area padding of phone tabs waiting for the phone item (D-54). Where a 44 px target meets unslop's rows of 32 to 36 px in dense navigation and tables, `web/DESIGN.md` decides, this brief asking for dense tables.

## Kickoff

```text
/phase-kickoff 4 — Read docs/masterplan/phases/P04-local-app.md and docs/masterplan/01-architecture.md §4–§9. Ask me the open decisions. Verify current versions of Vite, React, Tailwind, shadcn/ui, TanStack Router and Query, openapi-typescript, FastAPI, SQLAlchemy, Alembic, and uvicorn, and pin them in the kickoff PR along with any step amendments. Load the `frontend-design` skill and read docs/masterplan/08-code-design.md §5; collect the design brief and record it in the kickoff PR for step 4.3.
```

## Steps

### 4.1 App-state database, workspace folders, settings

Depends on: 3.8 · Plan mode: required · Reviews: step-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

App state has a home: a SQLite database with migrations, a workspace folder layout, and a settings model, all under `FEFAT_HOME`.

#### Prerequisites

- Phase 3 complete.

#### Prompt

```text
Masterplan step 4.1 — App-state database, workspace folders, settings.

Read docs/masterplan/01-architecture.md §4 and §5. In `python/fefat_app/src/fefat_app/database/` set up SQLAlchemy 2 models and Alembic (batch mode for SQLite) for the tables in §5 that this phase needs: settings, workspaces, datasets and dataset_snapshots, instruments, catalog_products, data_sources, import_profiles, features and feature_versions, strategies and strategy_versions, strategy_version_features, runs, jobs, events. Versioned tables are insert-only (enforced by a trigger or by the repository layer with a test). UUIDv7 ids. WAL mode. A `fefat db upgrade` command. Migrate the file-based feature versions from Phase 3 and the import profiles saved in Phase 1 into the database on first run (`fefat db import-workspace`), keeping the files as a backup.

Extend `fefat.config` from 0.5 (one module for `FEFAT_HOME` and `FEFAT_DATA_DIR` resolution with platformdirs defaults) with `config.toml` and validated settings (port, bind address, process-pool size, model defaults), and reuse `fefat_app.credentials` from 1.6 (keyring over the Windows credential store, with the `fefat secrets` CLI) for every API key.

Tests: migrations up and down from empty; insert-only enforcement; config round-trip; secrets stored outside the repo (a test that greps the repo and FEFAT_HOME for a known test secret and finds it only in the credential store).

Not in this step: the server, the UI.
```

#### Done means

1. `fefat db upgrade` creates the schema; `alembic downgrade base` empties it; both tested.
2. Updating a `feature_versions` row raises or is rejected (test).
3. Secrets round-trip through keyring and never land on disk in plaintext (test).

#### Your checks

- Run `fefat db upgrade` and open `%LOCALAPPDATA%\FEFAT\fefat.sqlite` with any SQLite viewer: the tables exist. Run `fefat secrets set anthropic` and then `fefat secrets list`: it shows the name, not the value.

#### If it fails

- keyring backend missing on Windows is unusual; if it happens, the fallback must fail loudly, never write a plaintext file.

#### Amendment

2026-10-12 (D-37): the tables are `catalog_products` and `data_sources` instead of `platform_products`.

2026-11-06 (Phase 4 kickoff, D-83, D-84): `Depends on: 3.8` reads as Phase 3 complete, its exit included. Workspace files stay the record of what the SDK saves, and the database indexes them (D-84): `fefat db import-workspace` reads the feature versions, the leak detector's reports, and the saved import profiles into their tables and can run again at any time, adding only the files it has not seen and moving and deleting nothing, so that a notebook's `ff.features.save` and the app's save land in the same files; the files are no longer a backup of the database. The step creates the tables this phase reads or writes, `settings`, `workspaces`, `features`, `feature_versions`, `feature_validations`, `import_profiles`, `jobs`, and `events`; step 4.2 adds `sessions` and `api_tokens` in a migration of its own, and the data, strategy, and run tables arrive with the Phase 5 steps that first write them (D-83). `feature_versions` takes the fields of `FeatureVersion` (name, version, hash, code, parameter schema, inputs, outputs, warm-up in bars and in sessions, creation time) and a combination's description as `combination_json`, which step 6.6's dialog reopens (from `BACKLOG.md`); `feature_validations` takes a row for each report it reads, keyed by the report file's SHA-256, with its instrument, timeframe, provider, window, and parameters and the verdict `ValidationReport.passed` works out, since the file keeps only the latest report of its hash (from `BACKLOG.md`); and `import_profiles` indexes each saved profile by name and kind with its file's SHA-256. Triggers refuse an update or a delete of a `feature_versions` or `feature_validations` row, which a test holds. Ids are UUIDv7 from a short function of RFC 9562's layout in `fefat_app.database`, with a test, since Python 3.12's `uuid` has no `uuid7`. `fefat_app.credentials` and `fefat secrets` never shipped, since D-38 left them out of step 1.6: this step writes them over keyring and the Windows credential store, behind the `CredentialStore` port, the first in `ports.py`, built in `container.py`; `fefat secrets` never prints a value, keyring's `fail` backend raises where no store is usable, and the step's test that no secret lands on disk in plain text is the backlog's (from `BACKLOG.md`). `fefat.config` reads `config.toml` with the standard library's `tomllib` into a frozen settings model: the port, 8765 by default; the bind address, which must be 127.0.0.1 (D-54); the process pool's size, with `01` §6's default; and the import roots of `01` §8. Model defaults wait for step 8.2, and what the app edits, such as the password and the theme, lives in the `settings` table (D-83). `FefatPaths` gains `config_file`, `database_file`, `logs_dir`, and `profiles_dir`, which `fefat.market.importers.profiles` builds by hand today, and creates nothing on disk; and `resolve_paths` refuses a `FEFAT_DATA_DIR` inside a git working tree, where an import would write licensed data beside tracked files, unless an environment variable allows it, which the tests that read `fixtures/` as their data folder set (from `BACKLOG.md`). `ff.features.ref` accepts a saved version whose code and inputs give its hash with the parameter schema it keeps, so that a Pydantic release that writes the schema otherwise no longer refuses the versions a run pins (from `BACKLOG.md`). The commands join `fefat_app.cli` as groups in modules of their own, as `fefat cache` did, since `cli.py` holds 358 lines: `fefat db upgrade`, `fefat db downgrade base`, which runs Done means 1's `alembic downgrade base` with the Alembic configuration that ships inside the package, `fefat db import-workspace`, and `fefat secrets`. Dependencies: sqlalchemy 2.1.8, alembic 1.20.1, and keyring 25.7.0, each with a decision line (D-27).

### 4.2 Local server, login, typed client generation

Depends on: 4.1 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

`fefat up` starts a server you can log in to, and the web app's types follow the API automatically.

#### Prerequisites

- Step 4.1 merged.

#### Prompt

```text
Masterplan step 4.2 — Local server, login, typed client generation.

Read docs/masterplan/01-architecture.md §7–§8. Implement the FastAPI app in `python/fefat_app/src/fefat_app/http/`: `fefat up` (uvicorn on the configured port, on localhost only), password set on first run (Argon2, stored in settings), `POST /v1/auth/login` issuing an HttpOnly session cookie (Secure when HTTPS, SameSite=Strict), CSRF token for state-changing requests, a bearer token for notebooks (`fefat token create`), rate limiting on login, `GET /v1/me`, `GET/PUT /v1/settings` (secrets write-only), `GET /v1/healthz`, `GET /v1/version`, problem+json errors, request ids in logs. Serve the built web app from `web/dist` when present. CSP as in §8.

Export the OpenAPI schema with `just gen-api` to `web/openapi.json` and generate `web/src/api/schema.d.ts` with openapi-typescript; a CI check fails on drift. Add `just up` (runs `fefat up`) and enable FastAPI's interactive `/docs` page after login, so you can try endpoints from the browser without `curl`.

Tests: login flow, CSRF rejection, bearer token for the API, a bind address other than localhost refused, security headers present.

Not in this step: the web UI, jobs.
```

#### Done means

1. `fefat up` starts; `/v1/healthz` answers; `/docs` works only after login (or is disabled outside dev).
2. Login, CSRF, bearer, and bind-address tests pass.
3. `just gen-api` produces the schema and the TypeScript types; CI drift check is wired.

#### Your checks

- Run `fefat up`, open `http://localhost:8765`, set a password, log in: `/v1/me` returns your user. Try `curl` to `/v1/settings` without the cookie: 401.

#### If it fails

- Cookies not set in the browser: `Secure` must be off on plain http://localhost; the server decides by scheme.

#### Amendment

2026-11-06 (Phase 4 kickoff, D-83): `fefat up` and `fefat token create` join `fefat_app.cli` as step 4.1's commands do, and `fefat up` runs uvicorn inside the command's own process, on the port and address of `config.toml`. The password is hashed with argon2-cffi and kept in the `settings` table. Sessions and API tokens are tables of this step's migration, `sessions(id, token_hash, created_at, expires_at, last_seen_at)` and `api_tokens(id, name, token_hash, created_at, last_used_at, revoked_at)`, each token random and stored as its SHA-256, Argon2's cost being for the password alone. The login's rate limit is a counter in the server's memory, without a dependency, and the login takes JSON, so python-multipart is not needed. The routers live in `fefat_app/http/` over services in `fefat_app/services/`, and a third import-linter contract holds that the services import neither FastAPI nor SQLAlchemy (`08-code-design.md` §1.5). Request ids go to log files under `FefatPaths.logs_dir`, and `/docs` sits behind the login. `fefat up` serves `web/dist` when it exists, and a path the API does not own falls back to its `index.html`, so that a reload on a page of the web app works. `just gen-api` writes `web/openapi.json` and then the types through `pnpm --dir web exec openapi-typescript`, version 7.13.0, whose peer range names TypeScript 5 and which runs on the 6.0.3 that `web/` keeps (D-83); the allow rule for `pnpm --dir web exec` goes in a setup commit of its own. Dependencies: fastapi 0.162.0, uvicorn 0.54.0, argon2-cffi 25.1.0, and httpx 0.28.1, which FastAPI's test client needs, as a development dependency, each with a decision line.

2026-11-06, while doing the step (D-86): FastAPI 0.162.0 sets no upper bound on Starlette and resolves Starlette 1.10.0, whose test client imports `httpx2` first and deprecates `httpx`, so the development dependency is httpx2 2.16.0 in place of httpx 0.28.1. The plan you approved adds `POST /v1/auth/logout`, which `01-architecture.md` §7 lists, and `fefat password set`, the first run's prompt as a command; `/docs` asks for the password through the browser's own prompt until step 4.3's login page exists; and the routes that change the password and manage API tokens, which step 4.3's settings page needs, wait in `BACKLOG.md` with `fefat token revoke`.

### 4.3 Web shell, login, navigation, UI test harness

Depends on: 4.2 · Plan mode: required · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

The web app exists: login, navigation, the data layer wired to the typed client, and a Playwright harness every later UI step uses.

#### Prerequisites

- Step 4.2 merged.

#### Prompt

```text
Masterplan step 4.3 — Web shell, login, navigation, UI test harness.

Read docs/masterplan/01-architecture.md §2 (web stack) and §3 (the `web/src` layout), docs/masterplan/08-code-design.md §5, and the design brief from the Phase 4 kickoff; load the `frontend-design` and `unslop` skills. Write `web/DESIGN.md` first — unslop's direction in its five lines (product, character, world, moments, signature), the palette as four to six named hex values from one tinted neutral ramp and one accent, the typefaces and type scale, the layout concept and alignment, the principles that make FEFAT's screens its own, with unslop's exact values where the brief does not decide — review it against the generic defaults the `frontend-design` skill lists and unslop's signs, record what you changed and why, and only then build: the tokens become the Tailwind theme and CSS variables, and shadcn/ui components are themed from them. In `web/` set up Vite + React + TypeScript with Tailwind and shadcn/ui, TanStack Router (file-based routes) and TanStack Query, laid out as `src/app`, `src/areas/<area>`, `src/ui`, `src/charts`, `src/api` with an import-boundary lint (chosen at the kickoff: `eslint-plugin-boundaries`, or oxlint's `no-restricted-imports` patterns) keeping areas from importing each other, an `openapi-fetch` client over the generated types, a login page, a protected app layout with a sidebar (Lab, Strategies, Runs, Prop, Agent — placeholders for now), a settings page (change password, API tokens, model defaults, data folder shown read-only), dark and light themes, and an error boundary.

Add the Playwright harness: a seeded test server (`just e2e` starts `fefat up` on a temp FEFAT_HOME with synthetic data), a desktop viewport project (1280×800), a login fixture, screenshot helpers; and the `ui-verifier` subagent under `.claude/agents/` (model: sonnet) that runs the harness and reports per criterion with screenshots. Configure `just dev` to run the server and the Vite dev server with a proxy.

Not in this step: any domain page.
```

#### Done means

1. `just dev` opens the app and login works.
2. Playwright specs pass for login and navigation; screenshots are attached to the PR.
3. `just build-web` produces `web/dist`, and `fefat up` serves it.
4. `web/DESIGN.md` exists with tokens, type, layout, principles, and the review notes; the screenshots show the themed components, not shadcn's defaults.

#### Your checks

- Run `just dev`, log in, open each placeholder page. Toggle dark mode.

#### If it fails

- Vite proxy and cookies: the dev server must proxy `/v1` to the server with cookies passed through; otherwise login appears to succeed and every request is 401.

#### Amendment

2026-10-09: the step now starts from the design brief and writes `web/DESIGN.md` with the `frontend-design` skill (D-28), and lays out `web/src` by product area with import boundaries (D-27).

2026-10-23 (D-54): no phone layout, bottom tabs, or phone viewport project; the harness and every later UI step verify at desktop size, and the phone pass is the backlog's phone item.

2026-11-04 (D-77): the `unslop` skill joins `frontend-design`: `web/DESIGN.md` opens with its direction and takes its exact values where the brief is silent, and the shell's screens pass its audit and checklist before the reviewers run.

2026-11-06 (Phase 4 kickoff, D-83): the design brief is this file's `## Design brief` section. `web/` is create-vite's scaffold (React, TypeScript 6.0.3, oxlint, vitest), so the step adds, at the versions of the phase's header and with a decision line: Tailwind through `@tailwindcss/vite`; shadcn/ui, whose CLI copies its components into `src/ui/` to be themed there; TanStack Router with file-based routes through `@tanstack/router-plugin`, and TanStack Query; `openapi-fetch` over step 4.2's generated types; react-hook-form with zod for the settings forms; lucide's icons; and Playwright, whose browser `pnpm --dir web exec playwright install chromium` installs. `@/` names `src/` in the TypeScript and Vite configurations. TypeScript stays at 6.0.3 with @types/node 24, since TypeScript 7 ships no `tsserver`, which the `typescript-lsp` plugin's server forks, and moved the compiler API that openapi-typescript calls (D-83). The import boundary is `scripts/check_web_imports.py`, a standard-library script in `just check` that resolves every import of `src/areas/<area>/`, through `@/` or a relative path, and fails one that reaches another area: oxlint implements `no-restricted-imports` but not `import/no-restricted-paths`, and its patterns cannot resolve a relative path, while `eslint-plugin-boundaries` would bring a second linter for one rule (D-83, `08-code-design.md` §1.5). Setup commits come first, each on its own: oxfmt becomes the formatter of `web/`, pinned exactly while in beta, with its check in `just check`, the format-on-edit hook's prettier branch and its smoke case becoming oxfmt's, VS Code's settings formatting TypeScript, JavaScript, JSON, and CSS with oxfmt rather than the Prettier extension, and the Prettier and ESLint recommendations dropped, prettier being the fallback if the beta blocks the step (from `BACKLOG.md`); `.claude/agents/ui-verifier.md` (model: sonnet) joins the read-only reviewers that `.claude/hooks/reviewer-shell-commands.mjs` lists, whose smoke tests expect every agent under `.claude/agents/` held read-only, a changed copy tested with `--hooks` before it is installed; the allow rules for `just e2e` and Playwright; `just doctor` reports `rust-analyzer`, `pyright-langserver`, and `typescript-language-server`; and if the `typescript-lsp` plugin cannot start its server on Windows, where `typescript-language-server` is an npm `.cmd` shim that a program starts only through a shell, a project plugin runs its `lib/cli.mjs` through `node` (both from `BACKLOG.md`). `just dev` replaces its placeholder, and `just e2e` and `just build-web` join the justfile. The verify skill's `ui-recipe.md` drops its 390 px check (D-54). The areas are `home`, `lab`, `strategies`, `runs`, `prop`, `agent`, `data`, and `settings`; the sidebar lists Home, Lab, Strategies, Runs, Prop, Agent, Data, and Settings, and the app opens on the home page of the brief, each widget a placeholder for now. The settings page shows the model defaults from step 8.2 on. The `design-reviewer` joins the meta line (D-34).

### 4.4 Jobs: local process pool, resumable progress streams, cancel

Depends on: 4.2, 4.3 · Plan mode: required · Reviews: step-reviewer, code-review, ui-verifier, design-reviewer · Security: no · Model hint: hard

#### Purpose

Long work runs in the background on your cores, reports progress that survives reloads and dropped connections, and can be cancelled.

#### Prerequisites

- Steps 4.2 and 4.3 merged.

#### Prompt

```text
Masterplan step 4.4 — Jobs: local process pool, resumable progress streams, cancel.

Read docs/masterplan/01-architecture.md §6. Implement `python/fefat_app/src/fefat_app/jobs/`: the `jobs` state machine with compare-and-set transitions, a `Dispatcher` interface with a `LocalDispatcher` over a process pool sized from config (workers are separate processes that import `fefat`), leases with heartbeats and a reaper for dead workers, `cancel_requested_at` checked between chunks with a hard kill after a grace period, and the append-only `events` table written by workers (progress percent, message, structured data). Implement `GET /v1/streams/{stream_id}` as SSE over the events table (event id = row id, `Last-Event-ID` resume, 15-second heartbeats) and `GET /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`. Add a `demo` job kind that counts for N seconds and reports progress, for tests and for your check.

In the web app add a jobs drawer (list, progress bars, cancel) using a fetch-based SSE reader that reconnects with the last event id.

Tests: state transitions; a killed worker's job is requeued up to max attempts; cancel stops a demo job; the SSE reader resumes without duplicates after a simulated disconnect.

Not in this step: real job kinds (backtests come in 5.3).
```

#### Done means

1. Job tests pass, including requeue after a killed worker and cancellation.
2. The SSE resume test passes with no duplicate or missing events.
3. The jobs drawer shows a running demo job with live progress (screenshot).

#### Your checks

- Start a 60-second demo job from the settings page (a "Run demo job" button), reload the browser mid-way: the progress bar continues from where it was. Cancel it: it stops within a few seconds.

#### If it fails

- SSE over the Vite proxy may buffer; disable response buffering for `/v1/streams` in the proxy config.

#### Amendment

2026-11-06 (Phase 4 kickoff, D-83): the jobs drawer is a screen, so the `ui-verifier` and the `design-reviewer` review the step, which builds from `web/DESIGN.md` with the `frontend-design` and `unslop` skills and ends with unslop's audit and checklist (D-77). The `Dispatcher` port joins `ports.py`, and the `LocalDispatcher` in `fefat_app/jobs/` runs a `concurrent.futures.ProcessPoolExecutor` with the spawn start method, the only one Windows has, sized by step 4.1's `config.toml`, over the `jobs` and `events` tables of step 4.1; each process opens the database in WAL mode with a busy timeout, since several workers write events at once. The jobs drawer and the home page's running-jobs widget read one SSE reader in `src/api/`, so the widget is filled in this step (the design brief).

### 4.5 Executor: subprocess isolation and limits for user code

Depends on: 4.4 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

Feature and strategy code runs in a separate process with time and memory limits, so a bad loop or a memory explosion cannot take the app down, and results are validated before use.

#### Prerequisites

- Step 4.4 merged.

#### Prompt

```text
Masterplan step 4.5 — Executor: subprocess isolation and limits for user code.

Read docs/masterplan/01-architecture.md §6 (Executor). Implement `Executor.run(ExecutionSpec) -> ExecutionResult` with a `SubprocessExecutor`: it writes the spec (kind, code files, args, data references, limits) to a job folder, launches the workspace interpreter (`sys.executable`, never a bare `python`) with `-m fefat_app.executor <folder>` and a scrubbed environment (no secrets, FEFAT_DATA_DIR read-only by convention), a wall-clock timeout, and a memory limit (a Windows Job Object; RLIMIT_AS elsewhere), streams JSON-line progress into the events table, and reads `result.json` plus Parquet outputs, validating them against Pydantic models and schema checks before returning. Kinds in this step: `feature_preview` (compute a feature over a range and return stats and a downsampled series) and `python_snippet` (run a snippet against an upload or dataset with a captured stdout tail). Also add a warm worker option: one long-lived runner process per workspace that executes previews without interpreter start-up, restarted on failure.

Tests: an infinite loop is killed at the timeout; a memory bomb is killed at the limit (sized small); a snippet cannot see the credential store or environment secrets; an invalid result.json is rejected; the warm worker survives a failing preview.

Not in this step: backtest jobs (5.3), the agent.
```

#### Done means

1. Timeout, memory, secret-scrubbing, and validation tests pass on Windows (and Linux in CI).
2. A feature preview through the warm worker completes in under a second for a month of 5-minute bars after the first call (timed test, generous bound).
3. The PR documents what the executor does and does not protect against (it is crash containment, not a security boundary).

#### Your checks

- From a notebook, call the executor with a snippet that sleeps for 30 seconds under a 5-second timeout: it returns `timeout` within about 5 seconds.

#### If it fails

- Memory limits on Windows need `CreateJobObject` via `pywin32` or ctypes; if the dependency is unwelcome, the limit may be enforced by polling the process's working set, documented as approximate.

#### Amendment

2026-11-06 (Phase 4 kickoff, D-83): the `Executor` port joins `ports.py`. The runner is `python -m fefat_app.executor <folder>` from `sys.executable`, `executor.py` becoming a package with a `__main__.py` if it would pass 400 lines. On Windows the memory limit is a Job Object created through `ctypes`, without pywin32, polling the working set being the documented fallback. `feature_preview` builds the feature from its code with `ff.features.from_source` (step 3.7) and computes it with `ff.features.compute` (step 3.3), whose cache serves a repeated preview, over the bars `load` gives; `python_snippet` runs against a dataset of the store, since uploads arrive in Phase 10. The scrubbed environment keeps `FEFAT_HOME` and `FEFAT_DATA_DIR`, drops every variable that holds a secret, and sets `PYTHON_KEYRING_BACKEND` to keyring's null backend, so that a snippet asking keyring for a key gets none, which the test of a snippet that cannot see the credential store holds. A snippet could still read the store through the Windows API, as any program you run can, which is why the executor is crash containment and not a security boundary (`01-architecture.md` §6), as Done means 3 asks the pull request to say. The timed preview of Done means 2 runs on a generated month of minute bars (`python/tests/generated_minutes.py`) read at 5 minutes, not on your data, with its generous bound.

### 4.6 Phone access over Tailscale, installable app, smoke test from the phone

Depends on: 4.3, 4.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: yes · Model hint: default

#### Purpose

The app on your phone: installed to the home screen, over HTTPS, reaching your PC privately, with the groundwork for notifications.

#### Prerequisites

- Steps 4.3 and 4.4 merged; Tailscale installed on the PC and on the phone, signed in to the same account; in the Tailscale admin console, MagicDNS and HTTPS certificates enabled for your tailnet (the step explains where).

#### Prompt

```text
Masterplan step 4.6 — Phone access over Tailscale, installable app, smoke test from the phone.

Read docs/masterplan/01-architecture.md §2 (phone access) and §8. Complete `--expose tailscale` from 4.2 (which binds to the Tailscale interface): obtain the HTTPS certificate for this machine's tailnet name (`tailscale cert`, or `tailscale serve` as a reverse proxy — choose the simpler reliable path and document it), and serve HTTPS so cookies are Secure and the service worker can register. Add the PWA pieces with vite-plugin-pwa in injectManifest mode: manifest (name, icons, standalone display), a service worker with an app-shell cache and an update prompt, an "Add to Home Screen" hint for iOS, and a settings toggle showing the Tailscale URL and a QR code.

Write docs/phone-checklist.md: first the one-time Tailscale setup in plain words (install on both devices, sign in, enable MagicDNS and HTTPS certificates in the admin console, where to find the machine name), then the smoke test. Run it with me: open the tailnet URL on the phone, log in, install, open from the home screen (no browser chrome), see the jobs drawer, start a demo job, watch progress, lock the phone, unlock, see it continue.

Tests: the manifest and service worker are served with correct headers; HTTPS redirect for the tailnet host; localhost still works over plain http.

Not in this step: push notifications (5.11), offline behaviour beyond the app shell.
```

#### Done means

1. The app installs to your phone's home screen from the tailnet URL and opens in standalone mode.
2. The phone checklist passes end to end, with photos or screenshots in the PR.
3. Localhost access is unchanged, and `--expose` is off by default.

#### Your checks

- From your phone, away from the PC's Wi-Fi (on mobile data, Tailscale connected): open the app, log in, start the demo job, watch it progress.

#### If it fails

- Certificate errors on iOS: the tailnet HTTPS certificate must be served with the full chain; `tailscale serve` handles this, a hand-rolled uvicorn SSL config may not.
- The install prompt never appears on iOS: there is none; use Share → Add to Home Screen, which the hint explains.

#### Amendment

2026-10-23 (D-54): skipped. Phone access is deferred until FEFAT is fully functional; the Tailscale exposure, the HTTPS certificate, the installable app, and the phone checklist are the backlog's phone item, to be run as written then.

## Phase exit

```text
/phase-exit 4 — Run the exit procedure for Phase 4: clean-clone suite including Playwright; /security-review over the server, auth, and executor; demo = log in, start the demo job, reload, watch it continue, cancel it; retro; backlog groomed; tag phase-4.
```
