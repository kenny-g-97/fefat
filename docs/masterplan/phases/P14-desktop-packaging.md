# Phase 14 — Desktop packaging and distribution (product phase)

**Goal.** FEFAT becomes an installable desktop app for other traders: the backend as a sidecar inside a Tauri shell, signed installers for Windows and macOS, auto-update, platform data delivered to customers as signed data packs from a hosted service (only for products FEFAT is licensed to distribute), a first-run experience, and clean-machine tests. This phase is optional for personal use and required for a commercial release.

**You get.** `FEFAT-Setup.exe` and `FEFAT.dmg` that a trader can install without Python or Rust on their machine, and that install and update the platform data for the products FEFAT provides.

**Depends on.** Phase 13.

**Open decisions for the kickoff.** Confirm the shell (Tauri 2, decided in D-03; revisit only if the spike in 14.1 finds a blocker); how to bundle Python (a self-contained interpreter from python-build-standalone with the `fefat` wheels, versus PyInstaller); Windows signing through a cloud signing service (certificates have been issued on hardware tokens since 2023 and cannot be exported into CI secrets — Azure Trusted Signing or a similar service) and an Apple Developer membership; update channel (GitHub Releases); whether macOS is in the first release; which products the platform provides to customers, from which vendors, under which distribution licences and at what cost (`07-tools-and-costs.md` §5); and where the data packs are hosted.

## Kickoff

```text
/phase-kickoff 14 — Read docs/masterplan/phases/P14-desktop-packaging.md, docs/masterplan/01-architecture.md §1–§4 and §10, docs/masterplan/02-engine-and-data.md §1.8, and docs/masterplan/appendix/research-market-data.md §3. Research the current Tauri 2 sidecar and updater documentation, python-build-standalone, signing requirements for Windows and macOS, and the current distribution terms of the data vendors for the platform products; ask me the open decisions; write the packaging decision record draft in the kickoff PR and reconcile the steps.
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

A desktop window that feels native: tray icon, auto-start option, native menus, deep links, and the Tailscale URL for the phone.

#### Prerequisites

- Step 14.2 merged.

#### Prompt

```text
Masterplan step 14.3 — Tauri shell: window, tray, auto-start.

Build the shell: a main window hosting the web UI, a tray icon with status (running, jobs active), start-at-login option, native menu with the essentials, deep links `fefat://run/<id>` from notifications, a "phone access" dialog showing the Tailscale URL and QR code, and settings for the data folder. Keep the web UI unchanged; detect the shell to hide browser-only hints.

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

Not in this step: platform data delivery (14.6–14.7), the first-run experience, store distribution.
```

#### Done means

1. An update from version N to N+1 works on a test machine with the prompt and the migration backup.
2. The release process is documented step by step.

#### Your checks

- Install the previous build, publish a test release, see the update prompt, update, confirm your data is intact.

#### If it fails

- A failed migration must leave the pre-migration backup in place and the app able to open the previous version's database read-only.

### 14.6 Platform data packs and licence gate

Depends on: 14.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: yes · Model hint: hard

#### Purpose

Platform data becomes something FEFAT can deliver to customers: versioned, signed packs that the app verifies before installing, built only for products FEFAT is licensed to distribute.

#### Prerequisites

- Step 14.5 merged; the licensing decisions from the kickoff.

#### Prompt

```text
Masterplan step 14.6 — Platform data packs and licence gate.

Read docs/masterplan/02-engine-and-data.md §1.8 and the licensing section of docs/masterplan/appendix/research-market-data.md §3. Define the platform data pack: a versioned bundle of canonical partitions for one product and range, with a manifest (product, schemas, range, catalog version, partition hashes, licence scope, the attribution text the vendor requires) signed with a FEFAT signing key held outside the repository. Implement `fefat data pack build` (from the platform datasets the 1.9 pipeline produces), an installer that verifies the signature and every hash before writing into the store, records the pack version on the datasets, and updates incrementally, and a `PackDataSource` for the `PlatformDataSource` interface that installs from a local folder of packs. Implement the licensing seam from docs/masterplan/01-architecture.md §10 for platform data: `licence.check(product, scope)` verifies a signed entitlement token (offline, against a FEFAT public key) that lists the products a customer may install; `fefat licence issue` creates tokens (you run it for now; billing is backlog). Every install calls the check; the catalog page shows the vendor's attribution text.

Write docs/platform-data-licensing.md: for each catalog product, the vendor, the licence that allows delivering it to customers, its cost, the subscriber agreement customers must accept (CME requires one with every subscriber), and its status. The pack builder refuses products whose distribution licence is not confirmed in that file, and datasets whose licence scope does not allow distribution (data you downloaded under your own plan is for internal use only). For products without a distribution licence, add an `OwnAccountDataSource`: the same catalog and managed sync running on the customer's machine with the customer's own vendor key (the personal-phase pipeline), so they keep the platform experience at no licensing cost to FEFAT; confirm with each vendor in writing that this use of their key is allowed.

Tests: a tampered pack is refused; an incremental update installs only new partitions; the builder refuses an unlicensed product and an internal-use dataset; an install without a valid entitlement token is refused; runs pin pack versions through their data snapshots.

Not in this step: hosting (14.7), billing.
```

#### Done means

1. Pack build, verified install, and incremental update work on synthetic products (tests).
2. A tampered pack, an unlicensed product, an internal-use dataset, and a missing entitlement are all refused with clear messages.
3. docs/platform-data-licensing.md lists every catalog product with its licence, cost, subscriber agreement, and status, and which delivery each customer gets (packs, or managed sync with their own vendor account).

#### Your checks

- Read docs/platform-data-licensing.md: every product you plan to provide to customers shows a vendor, a licence, and a cost you have agreed to.

#### If it fails

- If a vendor will not license distribution of a product, offer it to customers as managed sync with their own vendor account, or as import-only; the app handles all of these the same way once the data is in the store.

### 14.7 Hosted platform data service

Depends on: 14.6 · Plan mode: required · Reviews: step-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

Customers' apps download platform data from FEFAT's service and keep it current, while all their computing stays on their own machines.

#### Prerequisites

- Step 14.6 merged; an object-storage account for the packs (decided at the kickoff), with its credentials stored as secrets.

#### Prompt

```text
Masterplan step 14.7 — Hosted platform data service.

Implement the hosted side of platform data: an object-storage bucket for packs, a publishing workflow you run (`just publish-packs`: build, sign, upload, update the catalog index), a small endpoint that verifies the customer's entitlement token from 14.6 and issues short-lived download links for the products it lists, and an `HttpPackDataSource` in the app that lists the catalog, downloads packs with resume and integrity checks, and schedules updates. The service only serves downloads: no customer data or computing goes to it. Document publishing, monitoring, and operating costs in docs/runbook.md.

Tests: end to end against a local stand-in of the service (download, resume after an interruption, signature check, refused entitlement); a real upload of one synthetic pack to the bucket and a download by the app.

Not in this step: billing and customer accounts beyond the entitlement token (backlog).
```

#### Done means

1. The app installs a pack from the hosted service and updates it (recording attached).
2. Interrupted downloads resume; tampered or unentitled downloads are refused (tests).
3. The runbook documents publishing, monitoring, and costs.

#### Your checks

- Publish one synthetic pack with `just publish-packs`, then install it from a fresh FEFAT home with the app.

#### If it fails

- Download links that expire mid-download must be renewed by the app; the resume test covers it.

### 14.8 First-run experience

Depends on: 14.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

A new user gets from install to a first backtest without reading documentation.

#### Prerequisites

- Step 14.7 merged.

#### Prompt

```text
Masterplan step 14.8 — First-run experience.

Build the first-run wizard: choose the data folder; set a password; optionally enter an Anthropic key (tested); get data — enter the entitlement token and accept the data subscriber terms the licences require, then install the platform data for the products the user trades from the hosted service; or use managed sync with their own vendor account (their own key) for products delivered that way; and/or import their own files with the import wizard; phone pairing (Tailscale explanation, QR code); a sample strategy and a one-click first backtest on the installed data. Everything skippable and reachable again from settings.

Not in this step: marketing or licensing terms.
```

#### Done means

1. The wizard completes on a clean machine and ends on a run page (recording).
2. Every step is skippable and resumable.

#### Your checks

- Run the wizard on a clean VM, install one small platform product, and confirm it ends with a backtest on it.

#### If it fails

- The wizard must never block on a network failure; every network step has a skip.

### 14.9 Clean-machine install tests

Depends on: 14.8 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The installer works where it will be used: fresh Windows and macOS machines without developer tools.

#### Prerequisites

- Step 14.8 merged.

#### Prompt

```text
Masterplan step 14.9 — Clean-machine install tests.

Read docs/release-process.md and the first-run wizard from 14.8. Add CI jobs that install the built installer on Windows and macOS runners made to look like a customer's machine (GitHub-hosted images ship Python, Rust, and Node, so the job must isolate PATH and hide those toolchains, or use a bare VM image), launch the app headless where possible or through the Tauri test driver, complete the first-run wizard by installing a small synthetic platform pack from a test instance of the data service, run the sample backtest, verify the run page, then uninstall and check nothing is left behind except the data folder. Record the results, the installer sizes, and the time to first backtest in docs/validation/install-tests.md, and make the job a required check for release tags.

Not in this step: new features, store distribution.
```

#### Done means

1. Clean-machine install jobs pass on both platforms in CI.
2. Time to first backtest on a clean machine is recorded.

#### Your checks

- Read `docs/validation/install-tests.md`; try it yourself on a friend's PC if you can.

#### If it fails

- Missing Visual C++ runtime on clean Windows machines is the classic failure; the installer must bundle or install it.

## Phase exit

```text
/phase-exit 14 — Run the exit procedure for Phase 14: release workflow green with signed installers; /security-review over the shell, updater, sidecar, data packs, and data service; demo = install on a clean machine, install platform data, and run the wizard; update docs/product-readiness.md; retro; tag phase-14 and v1.0.0-rc1.
```
