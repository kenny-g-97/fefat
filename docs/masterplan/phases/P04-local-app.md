# Phase 4 — Local app and phone access

**Goal.** The application skeleton on your PC: a SQLite-backed local server with login, a React web shell that works on a phone, a job runner with resumable progress streams, a subprocess executor for user code, and the whole thing installed on your phone over Tailscale.

**You get.** `fefat up`, log in from your browser and your phone, run a demo job and watch its progress survive a reload.

**Depends on.** Phase 3 (the SDK exists; the app wraps it).

**Open decisions for the kickoff.** Your primary phone (iPhone or Android — it changes the install and notification steps); the app's display name and icon placeholder; the default port (8765 suggested); whether you already have a Tailscale account.

## Kickoff

```text
/phase-kickoff 4 — Read docs/masterplan/phases/P04-local-app.md and docs/masterplan/01-architecture.md §4–§9. Ask me the open decisions. Verify current versions of Vite, React, Tailwind, shadcn/ui, TanStack Router and Query, vite-plugin-pwa, openapi-typescript, FastAPI, SQLAlchemy, Alembic, and uvicorn, and pin them in the kickoff PR along with any step amendments.
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

Read docs/masterplan/01-architecture.md §4 and §5. In `python/fefat_app/db/` set up SQLAlchemy 2 models and Alembic (batch mode for SQLite) for the tables in §5 that this phase needs: settings, workspaces, datasets and dataset_snapshots, instruments, features and feature_versions, strategies and strategy_versions, strategy_version_features, runs, jobs, events, push_subscriptions. Versioned tables are insert-only (enforced by a trigger or by the repository layer with a test). UUIDv7 ids. WAL mode. A `fefat db upgrade` command. Migrate the file-based feature versions from Phase 3 into the database on first run (`fefat db import-workspace`), keeping the files as a backup.

Extend `fefat.config` from 0.5 (one module for `FEFAT_HOME` and `FEFAT_DATA_DIR` resolution with platformdirs defaults) with `config.toml` and validated settings (port, bind address, Tailscale exposure flag, process-pool size, model defaults), and reuse `fefat_app.secrets` from 1.6 (keyring over the Windows credential store, with the `fefat secrets` CLI) for every API key.

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

### 4.2 Local server, login, typed client generation

Depends on: 4.1 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

`fefat up` starts a server you can log in to, and the web app's types follow the API automatically.

#### Prerequisites

- Step 4.1 merged.

#### Prompt

```text
Masterplan step 4.2 — Local server, login, typed client generation.

Read docs/masterplan/01-architecture.md §7–§8. Implement the FastAPI app in `python/fefat_app/server/`: `fefat up` (uvicorn on the configured port, localhost by default; `--expose tailscale` binds additionally to the Tailscale interface address only), password set on first run (Argon2, stored in settings), `POST /v1/auth/login` issuing an HttpOnly session cookie (Secure when HTTPS, SameSite=Strict), CSRF token for state-changing requests, a bearer token for notebooks (`fefat token create`), rate limiting on login, `GET /v1/me`, `GET/PUT /v1/settings` (secrets write-only), `GET /v1/healthz`, `GET /v1/version`, problem+json errors, request ids in logs. Serve the built web app from `web/dist` when present. CSP as in §8.

Export the OpenAPI schema with `just gen-api` to `web/openapi.json` and generate `web/src/api/schema.d.ts` with openapi-typescript; a CI check fails on drift. Add `just up` (runs `fefat up`) and enable FastAPI's interactive `/docs` page after login, so you can try endpoints from the browser without `curl`.

Tests: login flow, CSRF rejection, bearer token for the API, `--expose` refusing 0.0.0.0, security headers present.

Not in this step: the web UI, jobs.
```

#### Done means

1. `fefat up` starts; `/v1/healthz` answers; `/docs` works only after login (or is disabled outside dev).
2. Login, CSRF, bearer, and bind-address tests pass; `--expose tailscale` without Tailscale installed fails with a clear message.
3. `just gen-api` produces the schema and the TypeScript types; CI drift check is wired.

#### Your checks

- Run `fefat up`, open `http://localhost:8765`, set a password, log in: `/v1/me` returns your user. Try `curl` to `/v1/settings` without the cookie: 401.

#### If it fails

- Cookies not set in the browser: `Secure` must be off on plain http://localhost; the server decides by scheme.

### 4.3 Web shell, login, phone navigation, UI test harness

Depends on: 4.2 · Plan mode: required · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The web app exists: login, navigation that works on a phone, the data layer wired to the typed client, and a Playwright harness every later UI step uses.

#### Prerequisites

- Step 4.2 merged.

#### Prompt

```text
Masterplan step 4.3 — Web shell, login, phone navigation, UI test harness.

Read docs/masterplan/01-architecture.md §2 (web stack) and the phone layout notes in docs/masterplan/00-product-spec.md §2.4. In `web/` set up Vite + React + TypeScript with Tailwind and shadcn/ui, TanStack Router (file-based routes) and TanStack Query, an `openapi-fetch` client over the generated types, a login page, a protected app layout with a sidebar on desktop and bottom tabs on phones (Lab, Strategies, Runs, Prop, Agent — placeholders for now), a settings page (change password, API tokens, model defaults, data folder shown read-only), dark and light themes, and an error boundary. Every page must work at 390×844 without horizontal scroll.

Add the Playwright harness: a seeded test server (`just e2e` starts `fefat up` on a temp FEFAT_HOME with synthetic data), projects for desktop and phone viewports, a login fixture, screenshot helpers; and the `ui-verifier` subagent under `.claude/agents/` (model: sonnet) that runs the harness and reports per criterion with screenshots. Configure `just dev` to run the server and the Vite dev server with a proxy.

Not in this step: any domain page.
```

#### Done means

1. `just dev` opens the app; login works; the layout switches to bottom tabs at phone width.
2. Playwright specs pass for login and navigation on both projects; screenshots for desktop and phone are attached to the PR.
3. `just build-web` produces `web/dist`, and `fefat up` serves it.

#### Your checks

- Run `just dev`, log in, narrow the window to phone width: bottom tabs appear and nothing scrolls sideways. Toggle dark mode.

#### If it fails

- Vite proxy and cookies: the dev server must proxy `/v1` to the server with cookies passed through; otherwise login appears to succeed and every request is 401.

### 4.4 Jobs: local process pool, resumable progress streams, cancel

Depends on: 4.2, 4.3 · Plan mode: required · Reviews: step-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

Long work runs in the background on your cores, reports progress that survives reloads and dropped phone connections, and can be cancelled.

#### Prerequisites

- Steps 4.2 and 4.3 merged.

#### Prompt

```text
Masterplan step 4.4 — Jobs: local process pool, resumable progress streams, cancel.

Read docs/masterplan/01-architecture.md §6. Implement `python/fefat_app/jobs/`: the `jobs` state machine with compare-and-set transitions, a `Dispatcher` interface with a `LocalDispatcher` over a process pool sized from config (workers are separate processes that import `fefat`), leases with heartbeats and a reaper for dead workers, `cancel_requested_at` checked between chunks with a hard kill after a grace period, and the append-only `events` table written by workers (progress percent, message, structured data). Implement `GET /v1/streams/{stream_id}` as SSE over the events table (event id = row id, `Last-Event-ID` resume, 15-second heartbeats) and `GET /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`. Add a `demo` job kind that counts for N seconds and reports progress, for tests and for your check.

In the web app add a jobs drawer (list, progress bars, cancel) using a fetch-based SSE reader that reconnects with the last event id.

Tests: state transitions; a killed worker's job is requeued up to max attempts; cancel stops a demo job; the SSE reader resumes without duplicates after a simulated disconnect.

Not in this step: real job kinds (backtests come in 5.3), push notifications.
```

#### Done means

1. Job tests pass, including requeue after a killed worker and cancellation.
2. The SSE resume test passes with no duplicate or missing events.
3. The jobs drawer shows a running demo job with live progress on desktop and phone (screenshots).

#### Your checks

- Start a 60-second demo job from the settings page (a "Run demo job" button), reload the browser mid-way: the progress bar continues from where it was. Cancel it: it stops within a few seconds.

#### If it fails

- SSE over the Vite proxy may buffer; disable response buffering for `/v1/streams` in the proxy config.

### 4.5 Executor: subprocess isolation and limits for user code

Depends on: 4.4 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

Feature and strategy code runs in a separate process with time and memory limits, so a bad loop or a memory explosion cannot take the app down, and results are validated before use.

#### Prerequisites

- Step 4.4 merged.

#### Prompt

```text
Masterplan step 4.5 — Executor: subprocess isolation and limits for user code.

Read docs/masterplan/01-architecture.md §6 (Executor). Implement `Executor.run(ExecSpec) -> ExecResult` with a `SubprocessExecutor`: it writes the spec (kind, code files, args, data references, limits) to a job folder, launches the workspace interpreter (`sys.executable`, never a bare `python`) with `-m fefat_app.exec_runner <folder>` and a scrubbed environment (no secrets, FEFAT_DATA_DIR read-only by convention), a wall-clock timeout, and a memory limit (a Windows Job Object; RLIMIT_AS elsewhere), streams JSON-line progress into the events table, and reads `result.json` plus Parquet outputs, validating them against Pydantic models and schema checks before returning. Kinds in this step: `feature_preview` (compute a feature over a range and return stats and a downsampled series) and `python_snippet` (run a snippet against an upload or dataset with a captured stdout tail). Also add a warm worker option: one long-lived runner process per workspace that executes previews without interpreter start-up, restarted on failure.

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

## Phase exit

```text
/phase-exit 4 — Run the exit procedure for Phase 4: clean-clone suite including Playwright; /security-review over the server, auth, executor, and Tailscale exposure; demo script = docs/phone-checklist.md; retro; backlog groomed; tag phase-4.
```
