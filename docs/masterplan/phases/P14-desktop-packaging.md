# Phase 14 — Desktop packaging and distribution (product phase)

**Goal.** FEFAT becomes an installable desktop app for other traders: the backend as a sidecar inside a Tauri shell, signed installers for Windows and macOS, auto-update, the data sources a trader connects on first run (FEFAT ships no market data, D-37), signed updates of the catalog of products and sources, a first-run experience, and clean-machine tests. This phase is optional for personal use and required for a commercial release.

**You get.** `FEFAT-Setup.exe` and `FEFAT.dmg` that a trader can install without Python or Rust on their machine, and that keep the catalog of products and sources up to date; the trader's data comes from the sources they connect.

**Depends on.** Phase 13.

**Open decisions for the kickoff.** Confirm the shell (Tauri 2, decided in D-03; revisit only if the spike in 14.1 finds a blocker); how to bundle Python (a self-contained interpreter from python-build-standalone with the `fefat` wheels, versus PyInstaller); Windows signing through a cloud signing service (certificates have been issued on hardware tokens since 2023 and cannot be exported into CI secrets — Azure Trusted Signing or a similar service) and an Apple Developer membership; update channel (GitHub Releases); whether macOS is in the first release; which vendors in the source guide have confirmed in writing that the app may use a customer's own account on the customer's machine (`07-tools-and-costs.md` §5); and where the signed catalog index is hosted (GitHub Releases by default).

## Kickoff

```text
/phase-kickoff 14 — Read docs/masterplan/phases/P14-desktop-packaging.md, docs/masterplan/01-architecture.md §1–§4 and §10, docs/masterplan/02-engine-and-data.md §1.8, and docs/masterplan/appendix/research-market-data.md §3. Research the current Tauri 2 sidecar and updater documentation, python-build-standalone, signing requirements for Windows and macOS, and the current terms of the vendors in the source guide for use of a customer's own account by an app on the customer's machine; ask me the open decisions; write the packaging decision record draft in the kickoff PR and reconcile the steps.
```

## Steps

### 14.1 Packaging decision record

Depends on: 13.7 · Plan mode: required · Reviews: step-reviewer · Security: no · Model hint: hard

#### Purpose

The packaging approach is decided with evidence from a spike, before building it.

#### Prerequisites

- Phase 14 kickoff done.

#### Prompt

```text
Masterplan step 14.1 — Packaging decision record.

Spike the two Python bundling options on this PC: (a) a self-contained CPython from python-build-standalone with the fefat and fefat_app wheels and their dependencies installed into it; (b) PyInstaller. Measure size, start-up time, and whether Polars, PyArrow, DuckDB, and the fefat_engine extension work in each. Spike a minimal Tauri 2 app that launches the chosen bundle as a sidecar on a free port and opens the web UI. Write docs/adr/NNNN-desktop-packaging.md with the choice, measurements, and risks, and a target layout for the bundle.

Not in this step: the real shell, installers.
```

#### Done means

1. Both bundles were measured; the ADR states the choice with numbers.
2. The Tauri spike shows the login page from the bundled backend.

#### Your checks

- Run the spike app: a window opens, you log in, the diagnostics page shows the bundled Python path.

#### If it fails

- If neither bundle runs the engine extension, the wheel's platform tag or MSVC runtime is the cause; check with `uv pip check` inside the bundle.

### 14.2 Backend as a sidecar

Depends on: 14.1 · Plan mode: optional · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

The backend starts, stops, and recovers under the shell's control, with ports, logs, and data folders handled correctly.

#### Prerequisites

- Step 14.1 merged.

#### Prompt

```text
Masterplan step 14.2 — Backend as a sidecar.

Make the backend sidecar-ready: a `--sidecar` mode that picks a free port, prints it on stdout for the shell, writes a lock file, logs to FEFAT_HOME/logs, exits when the parent dies, and reports health; `FEFAT_HOME` resolution inside the bundle; graceful shutdown of jobs on exit; crash restart with backoff in the shell. Build the sidecar launcher in the Tauri app with the bundled Python per the ADR.

Tests: the shell starts the backend and reaches /v1/healthz; killing the backend triggers a restart; closing the shell stops the backend.

Not in this step: installers.
```

#### Done means

1. Lifecycle tests pass on Windows (and macOS in CI if included).
2. Jobs running at shutdown are cancelled cleanly and marked (test).

#### Your checks

- Open the app, start a backtest, close the window: the process tree is gone within seconds, and reopening shows the run as cancelled.

#### If it fails

- Orphaned backends on Windows need a Job Object with kill-on-close; the shell must create it.

### 14.3 Tauri shell: window, tray, auto-start

Depends on: 14.2 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

A desktop window that feels native: tray icon, auto-start option, native menus, and deep links.

#### Prerequisites

- Step 14.2 merged.

#### Prompt

```text
Masterplan step 14.3 — Tauri shell: window, tray, auto-start.

Build the shell: a main window hosting the web UI, a tray icon with status (running, jobs active), start-at-login option, native menu with the essentials, deep links `fefat://run/<id>`, and settings for the data folder. Keep the web UI unchanged; detect the shell to hide browser-only hints.

Tests: the Tauri test harness opens the window; deep links route; tray state reflects jobs.

Not in this step: installers.
```

#### Done means

1. The shell runs on this PC with tray and deep links working.
2. The web UI behaves identically in the shell and in the browser (Playwright against the shell's webview where feasible, else documented manual checks).

#### Your checks

- Install start-at-login, reboot, see the tray icon, click it: the window opens to your runs.

#### If it fails

- Webview differences (Windows WebView2 versus browsers) usually appear in CodeMirror or chart touch handling; fix in the UI, not the shell.

### 14.4 Installers for Windows and macOS, code signing

Depends on: 14.3 · Plan mode: required · Reviews: step-reviewer · Security: yes · Model hint: hard

#### Purpose

Signed installers built in CI that install on a clean machine.

#### Prerequisites

- Step 14.3 merged; a cloud signing service account for Windows (Azure Trusted Signing or similar) and an Apple Developer membership, with their credentials stored as CI secrets.

#### Prompt

```text
Masterplan step 14.4 — Installers for Windows and macOS, code signing.

Read the current Tauri 2 documentation on Windows and macOS signing. Add a release workflow: build the engine wheels, the web bundle, the Python bundle, and the Tauri app on windows-latest and macos-latest; produce an NSIS or MSI installer and a DMG; sign on Windows through the cloud signing service (Tauri documents the Azure Trusted Signing path; certificates on hardware tokens cannot live in CI) and sign plus notarise on macOS with the Apple Developer credentials; upload artifacts to a GitHub pre-release. Every binary inside the Python bundle must be signed too, or notarisation fails. Document the secrets needed and how to rotate them in docs/release-process.md (started here, completed in 14.5).

Not in this step: the updater.
```

#### Done means

1. The release workflow produces signed installers for both platforms from a tag.
2. SmartScreen and Gatekeeper accept the installers (screenshots from clean VMs).

#### Your checks

- Download the Windows installer from the pre-release on a clean Windows VM, install, launch, log in.

#### If it fails

- Notarisation failures are almost always entitlement or hardened-runtime issues with the bundled Python; the ADR's bundle layout must sign every binary inside.

### 14.5 Auto-update and release workflow

Depends on: 14.4 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

Users get updates safely, and releases are repeatable.

#### Prerequisites

- Step 14.4 merged.

#### Prompt

```text
Masterplan step 14.5 — Auto-update and release workflow.

Read the current Tauri 2 updater documentation and the docs/release-process.md started in 14.4. Enable Tauri's updater with a signed update manifest served from GitHub Releases, a release channel setting (stable, beta), an in-app update prompt with release notes, a download-then-apply flow that never leaves a half-installed app, database migrations run on first start after an update (with a pre-migration backup through `fefat backup` and a clear message if a migration fails), and a rollback note in the runbook. Make the release workflow produce and sign the manifest, verify signatures in a test, and bump versions in one place (`just release <version>`). Write docs/release-process.md: tagging, building, signing, publishing, verifying, rolling back.

Not in this step: data sources in the packaged app and catalog updates (14.6–14.7), the first-run experience, store distribution.
```

#### Done means

1. An update from version N to N+1 works on a test machine with the prompt and the migration backup.
2. The release process is documented step by step.

#### Your checks

- Install the previous build, publish a test release, see the update prompt, update, confirm your data is intact.

#### If it fails

- A failed migration must leave the pre-migration backup in place and the app able to open the previous version's database read-only.

#### Amendment

2026-10-12 (D-37): the "Not in this step" line names the data sources in the packaged app and the catalog updates (14.6–14.7) instead of platform data delivery.

### 14.6 Data sources in the packaged app and the no-shipped-data check

Depends on: 14.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: yes · Model hint: hard

#### Purpose

The packaged app gives a new trader their data the same way the personal build does: through the sources they connect with their own accounts and the files they import, with the terms of each source in view. FEFAT ships no market data, and the build proves it.

#### Prerequisites

- Step 14.5 merged; the vendor confirmations from the kickoff.

#### Prompt

```text
Masterplan step 14.6 — Data sources in the packaged app and the no-shipped-data check.

Read docs/masterplan/02-engine-and-data.md §1.8, docs/adr/0018-own-data-sources-no-shipped-data.md, and the licensing section of docs/masterplan/appendix/research-market-data.md §3. Bring the source guide, the connectors, the presets, and the sync of step 1.9 into the packaged app as they are: the catalog of products and sources ships inside the app, every dataset is fetched on the customer's machine with the customer's own account or imported from the customer's files, and nothing FEFAT runs ever receives, stores, or serves market data. Write docs/data-sources.md for customers: for each source in the guide, what it offers, its cost, the terms a trader accepts for personal use, the vendor's attribution text where its terms require one (shown on the catalog page), and the status of the vendor's written confirmation that the app may use a customer's own account on the customer's machine; the app marks a source without that confirmation as "check the terms yourself" and never hides it.

Add the no-shipped-data check: the release build fails when the installer, the bundled resources, or the signed catalog index (14.7) contain any dataset or raw vendor file (the commit guard's data-format check, run over the bundle), and a fresh install starts with an empty data folder. Reduce the licensing seam of docs/masterplan/01-architecture.md §10 to app licence keys (backlog): `licence.check` keeps returning `ok` for every data source.

Tests: the bundle check refuses a build that contains a Parquet or DBN file; a fresh install shows the catalog products with no data and every source unconnected; connecting a source in the packaged app stores the key in the OS credential store and syncs a synthetic product end to end.

Not in this step: the signed catalog updates (14.7), the first-run wizard (14.8), billing.
```

#### Done means

1. docs/data-sources.md lists every source in the guide with its offer, cost, terms, attribution text, and confirmation status.
2. The bundle check refuses a build with a data file in it, and a clean install has an empty data folder (tests, and the release workflow runs the check).
3. Connecting a source and syncing a synthetic product work in the packaged app (recording).

#### Your checks

- Install the build on a clean VM: the catalog shows your products with no data and every source unconnected; connect the crypto archive and sync one product.

#### If it fails

- A vendor will not confirm that the app may use a customer's own account: keep the source in the guide as "check the terms yourself", or as import-only; the app handles both the same way once the data is in the store.

#### Amendment

2026-10-12 (D-37): the step replaces "Platform data packs and licence gate". FEFAT no longer delivers data to customers, so packs, distribution licences, entitlement tokens, and `OwnAccountDataSource` (now simply the sync of 1.9) are gone, and the step's job is the source guide for customers and the proof that no data ships with the app.

### 14.7 Signed catalog updates from a static host

Depends on: 14.6 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

The catalog of products and sources changes between releases (a new source, a changed specification or calendar, a new preset), and customers' apps pick those changes up without an app update, from a static host that serves no market data.

#### Prerequisites

- Step 14.6 merged; the host for the index from the kickoff (GitHub Releases by default), with its credentials stored as secrets.

#### Prompt

```text
Masterplan step 14.7 — Signed catalog updates from a static host.

Define the catalog index: a versioned bundle of the product catalog, the source guide, the calendars, the roll rules, and the import presets, with a manifest (version, file hashes, the minimum app version) signed with a FEFAT signing key held outside the repository; it contains no market data, and the no-shipped-data check of 14.6 runs on it. Implement a publishing workflow you run (`just publish-catalog`: build, sign, upload) to the static host decided at the kickoff, and in the app a `CatalogUpdater` that fetches the index on a schedule and on demand, verifies the signature and every hash against the FEFAT public key, installs it next to the bundled copy, falls back to the bundled copy when verification fails or the host is unreachable, and shows the catalog version on the Data page. Document publishing, monitoring, and operating costs in docs/runbook.md.

Tests: end to end against a local stand-in of the host (download, resume after an interruption, signature check, a tampered index refused, a too-old app version refused with a clear message); a real upload of one index to the host and an update by the app.

Not in this step: market data of any kind, billing, customer accounts.
```

#### Done means

1. The app updates its catalog from the host and shows the new version (recording).
2. A tampered or unverifiable index is refused and the bundled copy stays in use (tests).
3. The runbook documents publishing, monitoring, and costs.

#### Your checks

- Publish one index with `just publish-catalog`, then watch a fresh install pick it up and show the new catalog version.

#### If it fails

- An index that fails verification must leave the bundled copy in use and say so; the tamper test covers it.

#### Amendment

2026-10-12 (D-37): the step replaces "Hosted platform data service". The hosted side serves the signed catalog index only (specifications, calendars, roll rules, presets, the source guide), never market data, so it needs no data licence and costs about nothing on a static host.

### 14.8 First-run experience

Depends on: 14.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

A new user gets from install to a first backtest without reading documentation.

#### Prerequisites

- Step 14.7 merged.

#### Prompt

```text
Masterplan step 14.8 — First-run experience.

Build the first-run wizard: choose the data folder; set a password; optionally enter an Anthropic key (tested); get data — pick the products the user trades from the catalog, connect a source from the guide (its terms shown and accepted; a key stored in the credential store) and sync them, with the cost preview before any paid download, and/or import their own files with the import wizard; a sample strategy and a one-click first backtest on the synced or imported data. Everything skippable and reachable again from settings.

Not in this step: marketing or licensing terms.
```

#### Done means

1. The wizard completes on a clean machine and ends on a run page (recording).
2. Every step is skippable and resumable.

#### Your checks

- Run the wizard on a clean VM, connect the crypto archive and sync one small product, and confirm it ends with a backtest on it.

#### If it fails

- The wizard must never block on a network failure; every network step has a skip.

#### Amendment

2026-10-12 (D-37): the wizard connects a source from the guide and syncs instead of installing platform data with an entitlement token.

### 14.9 Clean-machine install tests

Depends on: 14.8 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The installer works where it will be used: fresh Windows and macOS machines without developer tools.

#### Prerequisites

- Step 14.8 merged.

#### Prompt

```text
Masterplan step 14.9 — Clean-machine install tests.

Read docs/release-process.md and the first-run wizard from 14.8. Add CI jobs that install the built installer on Windows and macOS runners made to look like a customer's machine (GitHub-hosted images ship Python, Rust, and Node, so the job must isolate PATH and hide those toolchains, or use a bare VM image), launch the app headless where possible or through the Tauri test driver, complete the first-run wizard by connecting a synthetic source (a local stand-in of the archive) and syncing one small synthetic product, run the sample backtest, verify the run page, then uninstall and check nothing is left behind except the data folder. Record the results, the installer sizes, and the time to first backtest in docs/validation/install-tests.md, and make the job a required check for release tags.

Not in this step: new features, store distribution.
```

#### Done means

1. Clean-machine install jobs pass on both platforms in CI.
2. Time to first backtest on a clean machine is recorded.

#### Your checks

- Read `docs/validation/install-tests.md`; try it yourself on a friend's PC if you can.

#### If it fails

- Missing Visual C++ runtime on clean Windows machines is the classic failure; the installer must bundle or install it.

#### Amendment

2026-10-12 (D-37): the clean-machine test connects a synthetic source and syncs one product instead of installing a platform pack from the data service.

## Phase exit

```text
/phase-exit 14 — Run the exit procedure for Phase 14: release workflow green with signed installers; /security-review over the shell, updater, sidecar, the catalog updater, and the connectors; demo = install on a clean machine, connect a source, and run the wizard; update docs/product-readiness.md; retro; tag phase-14 and v1.0.0-rc1.
```
