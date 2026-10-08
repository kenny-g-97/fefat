# Phase 12 — Phone polish

**Goal.** The phone experience is finished: installation and update behaviour are audited, notifications cover every job kind with preferences, touch interactions on charts and forms are right, the app is fast on a phone, and it behaves well offline and on reconnect.

**You get.** An app on your phone that feels like an app.

**Depends on.** Phase 11 in the written order (all pages exist). It can run earlier if the phone matters more to you than research tools; amend 12.1's `Depends on` line at the kickoff, and the audits then cover the pages that exist.

**Open decisions for the kickoff.** Your phone and OS version; which notifications you want by default.

## Kickoff

```text
/phase-kickoff 12 — Read docs/masterplan/phases/P12-phone-polish.md and docs/masterplan/00-product-spec.md §2.4. Ask me the open decisions. Run the ui-verifier over every page at phone size and list findings in the kickoff PR, then reconcile the steps.
```

## Steps

### 12.1 Install and update audit

Depends on: 11.8 · Plan mode: skip · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Installing, launching, and updating the app on the phone is reliable.

#### Prerequisites

- Phase 12 kickoff done.

#### Prompt

```text
Masterplan step 12.1 — Install and update audit.

Audit the PWA on your phone's OS: manifest completeness (name, icons including maskable, theme colours, display standalone, start URL with the Tailscale host), the install hint flow on iOS, the service worker's update prompt (a new build is picked up within one reload, with a visible "update available" prompt), splash and status-bar appearance, and deep links from notifications. Fix findings. Add an installability check to CI on the built app: validate the manifest against the spec, assert the service worker registers, and assert the browser's install prompt event fires in a Playwright test (Lighthouse dropped its PWA category in version 12, so do not rely on it).

Not in this step: notifications beyond deep links.
```

#### Done means

1. The installability check (manifest validation, service-worker registration, install prompt event) passes in CI.
2. A new build triggers the update prompt on the phone (screenshot).
3. Icons and splash look right on your phone (photos).

#### Your checks

- Delete and reinstall the app on your phone from the Tailscale URL; it should open full-screen with the right icon and name.

#### If it fails

- iOS caches manifests aggressively; a changed icon may need a reinstall; document it in the phone checklist.

### 12.2 Notifications for every job kind, with preferences

Depends on: 12.1 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

You decide what the phone tells you: runs, studies, prop simulations, ingestions, agent proposals awaiting review.

#### Prerequisites

- Step 12.1 merged.

#### Prompt

```text
Masterplan step 12.2 — Notifications for every job kind, with preferences.

Read the push implementation from 5.11 and docs/masterplan/01-architecture.md §6 (job kinds). Extend web push to studies, prop simulations, ingestions, failed jobs, and "proposal awaiting your review"; add a notification preferences page (per kind, quiet hours in your local time zone, a test button), and make each notification carry a deep link to the right page with the tailnet origin stored at subscription time. Batch bursts (a study with many trials sends one notification at completion; several failures within a minute are grouped). Keep the push payload small and never include secrets or strategy code. Test on the phone for two kinds and attach photos.

Not in this step: email or other channels, per-strategy preferences.
```

#### Done means

1. Each kind sends the right notification with the right deep link (tests with a fake push service).
2. Preferences and quiet hours are respected (tests).
3. Phone verification photos for two kinds in the PR.

#### Your checks

- Enable only "proposal awaiting review", ask the agent for a change from desktop, lock the phone: the notification opens the proposal.

#### If it fails

- Deep links must use the tailnet origin stored at subscription time, not `localhost`.

### 12.3 Touch audit of charts and forms

Depends on: 12.1 · Plan mode: skip · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Charts pan and zoom under a thumb without hijacking page scroll, forms are tappable, and nothing requires precision.

#### Prerequisites

- Step 12.1 merged.

#### Prompt

```text
Masterplan step 12.3 — Touch audit of charts and forms.

Walk every chart (price, equity, heatmaps, timelines) and every form on the phone: pan and pinch behaviour, scroll trapping, tap targets at least 44 px, keyboard types for numeric fields, date pickers, bottom sheets closing on swipe, long tables as cards with a details sheet. Fix findings. Add Playwright phone tests for the three most common interactions (select a trade on the chart, change a parameter, accept a proposal).

Not in this step: performance.
```

#### Done means

1. The ui-verifier report at phone size shows no remaining touch findings.
2. The three phone interaction tests pass in CI.

#### Your checks

- With one thumb: open a run, select a trade from the list, pan the chart, go back, change a stop in the form, run.

#### If it fails

- Any chart that captures vertical scroll must be fixed to only capture horizontal pan unless a mode is toggled.

### 12.4 Speed on the phone

Depends on: 12.3 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Pages open fast on a phone over Tailscale: small bundles, lazy loading, cached immutable data.

#### Prerequisites

- Step 12.3 merged.

#### Prompt

```text
Masterplan step 12.4 — Speed on the phone.

Measure first, with Lighthouse (mobile) and the browser's performance tools over the Tailscale path from the phone: bundle sizes per route, time to interactive, API payload sizes, and the slowest endpoints. Then apply, in order of measured impact: route-level code splitting, lazy-loading ECharts and CodeMirror, `Cache-Control: immutable` for run artifacts (runs never change), compressed API responses, columnar JSON for large tables, prefetching the next likely page, and smaller initial queries on list pages. Record before and after numbers in docs/validation/phone-performance.md, add bundle-size budgets to CI, and keep the desktop experience unchanged (Playwright desktop suite still green).

Not in this step: offline behaviour, server-side performance (13.5).
```

#### Done means

1. Lighthouse mobile performance improves and the numbers are recorded.
2. Bundle-size budgets are enforced in CI.
3. Run pages load from cache instantly on a second visit (test).

#### Your checks

- Open a run page on your phone twice: the second open is near-instant.

#### If it fails

- The largest wins are usually lazy-loading the chart libraries; measure first.

### 12.5 Offline and reconnect behaviour

Depends on: 12.4 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The app degrades gracefully when the PC is off or the tunnel drops, and recovers without losing your drafts.

#### Prerequisites

- Step 12.4 merged.

#### Prompt

```text
Masterplan step 12.5 — Offline and reconnect behaviour.

Define and implement the offline contract: the app shell loads offline; cached runs and pages are readable; actions that need the server show a clear "PC unreachable" state with a retry; drafts (feature code, chat input, builder forms) persist locally and survive; streams reconnect automatically when the server returns; a connectivity indicator shows the Tailscale state as seen from the app. Test by stopping the server and by disabling Tailscale on the phone.

Not in this step: cloud sync (backlog).
```

#### Done means

1. Offline tests (service worker with the server stopped) pass in Playwright.
2. A draft typed while offline is there after reconnect (test).
3. The phone checklist gains an offline section and passes.

#### Your checks

- Turn off Tailscale on your phone mid-draft, type more, turn it on: the draft is intact and the stream resumes.

#### If it fails

- Never queue writes offline for later replay in this release; show the state and keep the draft. Queued writes are a sync feature.

## Phase exit

```text
/phase-exit 12 — Run the exit procedure for Phase 12: clean-clone suite; ui-verifier full pass at phone size; demo = the phone checklist end to end; retro; backlog groomed; tag phase-12.
```
