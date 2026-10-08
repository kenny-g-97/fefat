# Phase 13 — Hardening

**Goal.** FEFAT is dependable for daily use and ready to be packaged: the local server is reviewed for security, the app survives bad inputs and long sessions, you can diagnose problems, your work is backed up and restorable, performance is checked end to end, old runs still reproduce, and a runbook plus a product-readiness checklist exist.

**You get.** Confidence, backups, and a written list of what remains before selling it.

**Depends on.** Phase 12.

**Open decisions for the kickoff.** Where backups go (a second drive, a NAS, a cloud bucket you own); how long to keep them.

## Kickoff

```text
/phase-kickoff 13 — Read docs/masterplan/phases/P13-hardening.md, docs/masterplan/01-architecture.md §8, and docs/masterplan/appendix/risk-register.md. Ask me the open decisions. Review the risk register against the code as it stands and list the mitigations not yet in place in the kickoff PR; reconcile the steps.
```

## Steps

### 13.1 Security review of the local server

Depends on: 12.5 · Plan mode: optional · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

The server exposed on Tailscale is reviewed as if it were exposed to the internet.

#### Prerequisites

- Phase 13 kickoff done.

#### Prompt

```text
Masterplan step 13.1 — Security review of the local server.

Run /security-review over the whole repository and a manual review of: authentication and session handling, CSRF, rate limiting, CSP and headers, file-path handling (imports, uploads, artifacts), the executor's environment scrubbing, secrets handling, the Tailscale exposure path, dependency vulnerabilities (`pip-audit` over `uv export`, `cargo audit`, `pnpm audit`, all in CI). Fix blocking findings; log the rest with a justification in docs/security/review-2026.md. Add the audit tools to CI with an allowlist file for accepted advisories.

Not in this step: new features.
```

#### Done means

1. No blocking findings remain; the review document lists every finding and its disposition.
2. Dependency audits run in CI and pass (with an allowlist that explains each accepted advisory).

#### Your checks

- Read `docs/security/review-2026.md`: every item has a disposition you understand.

#### If it fails

- An unfixable advisory in a transitive dependency goes to the allowlist with an expiry date, never silently.

### 13.2 Robustness and resource limits

Depends on: 13.1 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Long sessions, huge datasets, and bad inputs do not crash, hang, or exhaust the machine.

#### Prerequisites

- Step 13.1 merged.

#### Prompt

```text
Masterplan step 13.2 — Robustness and resource limits.

Add a soak test (`just soak`): the server runs for hours with a script that launches runs, studies, previews, and agent turns (replayed) continuously; memory and handle counts are sampled and must stay bounded. Add global resource governance: concurrent job limits, per-kind limits, disk-space checks before writing artifacts and caches (refuse with a clear message under a threshold), cache size limits with pruning, and an events-table retention policy. Fuzz the API with schemathesis against the OpenAPI schema and fix crashes.

Not in this step: performance tuning (13.5).
```

#### Done means

1. The soak test runs for two hours in a nightly CI job (or locally, with the report attached) with bounded memory.
2. Schemathesis finds no 5xx responses.
3. Disk and cache limits are enforced (tests).

#### Your checks

- Fill the cache limit artificially (a test command) and start a run: the app prunes or refuses with a clear message instead of failing mysteriously.

#### If it fails

- Memory growth in the server usually comes from unbounded in-memory event buffers; events belong in the table.

### 13.3 Diagnostics and logs

Depends on: 13.2 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

When something goes wrong you can see why, and you can hand Claude Code a diagnostics bundle.

#### Prerequisites

- Step 13.2 merged.

#### Prompt

```text
Masterplan step 13.3 — Diagnostics and logs.

Read docs/masterplan/01-architecture.md §8 (secrets) and the logging conventions used so far. Implement structured logging (JSON lines under FEFAT_HOME/logs with rotation and a size cap), request ids through API and jobs (and through executor subprocesses), per-job log tails in the job page with a "copy for support" button, a diagnostics page (versions of the app, engine, Python, and OS; config without secrets; data folder and cache statistics; recent errors with request ids), and `fefat diagnostics bundle` that zips logs, redacted config, the schema version, and recent job records for troubleshooting, with an allowlist-based redaction. Optional Sentry opt-in behind a setting, off by default, with the same redaction.

Not in this step: metrics dashboards, remote log shipping.
```

#### Done means

1. Every request and job carries an id visible in logs and pages.
2. The bundle contains no secrets (test greps for the test secret).
3. The diagnostics page renders on desktop and phone.

#### Your checks

- Cause a failing run (a strategy with a bug), open the job page, read the log tail; run `fefat diagnostics bundle` and look inside the zip.

#### If it fails

- Redaction must be allowlist-based (known safe keys), not blocklist-based.

### 13.4 Backups, export, restore drill

Depends on: 13.3 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

Your features, strategies, runs, and settings are backed up on a schedule and proven restorable.

#### Prerequisites

- Step 13.3 merged; the backup destination decision.

#### Prompt

```text
Masterplan step 13.4 — Backups, export, restore drill.

Implement `fefat backup` (a consistent SQLite backup via the online backup API plus the workspace folder, excluding caches and raw market data, into a timestamped archive at the configured destination, with retention) and `fefat restore <archive>` (into a fresh FEFAT_HOME, verifying the schema version and artifact hashes), a scheduled backup (Windows Task Scheduler registration from the CLI, or an in-app scheduler), and workspace export/import (a portable archive of features, strategies, runs' metrics and artifacts for sharing between machines). Perform a restore drill: back up, restore to a temporary home, start the server there, log in, open a run.

Not in this step: cloud sync.
```

#### Done means

1. Backup and restore round-trip tests pass, including artifact hash verification.
2. The scheduled backup runs on this PC (evidence in the PR).
3. The restore drill is documented in docs/runbook.md with the time it took.

#### Your checks

- Run `fefat backup`, then `fefat restore` into a temporary folder, start the server from it on another port, log in, open your latest run.

#### If it fails

- Backing up a live SQLite file by copying is unsafe; the online backup API or `VACUUM INTO` is required.

### 13.5 Performance pass

Depends on: 13.4 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The whole system is measured on real sizes, and the slow spots are fixed or recorded.

#### Prerequisites

- Step 13.4 merged.

#### Prompt

```text
Masterplan step 13.5 — Performance pass.

Measure on your real data: API latency for the key endpoints (bars, trades, equity, chart), feature preview, a 5-year backtest end to end through the app, a 1,000-trial sweep, the prop Monte Carlo, DuckDB queries over large artifacts, and the Tailscale path from the phone. Compare with the design targets; profile and fix the worst offenders where the fix is contained; record the rest in the backlog with numbers. Update docs/validation/benchmarks.md.

Not in this step: architectural changes.
```

#### Done means

1. A performance table with before/after numbers exists in `docs/validation/benchmarks.md`.
2. Any endpoint over 1 second at p95 on real data is either fixed or in the backlog with a reason.

#### Your checks

- Time a full 5-year backtest from the app on your phone: seconds for the engine, plus the time to compute features the first time.

#### If it fails

- Do not optimise without a profile; attach the profile to the PR.

### 13.6 Reproducibility audit

Depends on: 13.5 · Plan mode: skip · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

Every run you made during the build still reproduces today, which is the promise the version control makes.

#### Prerequisites

- Step 13.5 merged.

#### Prompt

```text
Masterplan step 13.6 — Reproducibility audit.

Write `fefat audit reproduce` that re-runs a sample (or all) of the stored runs with their pinned versions, snapshots, engine and fill-model versions, and compares trades-table hashes; runs made with older engine versions are re-run with the current engine and the differences are reported by engine-version change (which should be none unless a fill-model version bump occurred, in which case the changelog is cited). Run it over everything and fix the causes of any mismatch (missing pins).

Not in this step: anything else.
```

#### Done means

1. The audit report shows 100% reproduction for runs on the current engine, and explained differences for older fill-model versions.
2. Any missing pin found is fixed and covered by a test.

#### Your checks

- Read the audit report; pick an early run from Phase 5 and confirm it reproduced.

#### If it fails

- A mismatch with no engine change means a hidden input (calendar override, fee table, feature cache): find it and pin it.

### 13.7 Runbook and product-readiness checklist

Depends on: 13.6 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

How to run FEFAT day to day is written down, and what remains before selling it is an honest list.

#### Prerequisites

- Step 13.6 merged.

#### Prompt

```text
Masterplan step 13.7 — Runbook and product-readiness checklist.

Write docs/runbook.md: start and stop, update to a new version, add data, backups and restore, Tailscale and phone setup, diagnostics, common problems and fixes. Write docs/product-readiness.md: everything deferred by DECISIONS.md and BACKLOG.md that a commercial release needs (licence keys, telemetry opt-in, terms and privacy, support channel, installers and signing — Phase 14 — macOS support, documentation for customers, data-vendor terms confirmation in writing, pricing), each with an estimate and a dependency. Groom the backlog with the Phase 13 findings.

Not in this step: anything else.
```

#### Done means

1. Both documents exist and are linked from the root README.
2. The readiness checklist references the exact backlog items.

#### Your checks

- Read the runbook's "common problems" section: does it cover the issues you actually hit during the build?

#### If it fails

- If the readiness list feels short, compare it against the risk register.

## Phase exit

```text
/phase-exit 13 — Run the exit procedure for Phase 13: clean-clone suite including soak and audit jobs; /security-review; /code-review high; demo = the runbook's daily workflow performed on the phone and the PC; retro; backlog groomed; tag phase-13.
```
