# Phase 6 — Feature lab and strategy builder

**Goal.** The hybrid workflow you chose: features written in a code editor with an instant chart and statistics preview, leak results shown in the app, analytics pages, a combination builder, and a no-code strategy builder that generates the Python definition and runs a backtest.

**You get.** Write a feature on your phone or PC, preview it in a second, save a version, combine it, build a strategy from two features in a form, look at the generated code, run it.

**Depends on.** Phase 5.

**Open decisions for the kickoff.** The default preview instrument and range; whether the builder's first release needs every execution-template option or a curated subset.

## Kickoff

```text
/phase-kickoff 6 — Read docs/masterplan/phases/P06-feature-lab-and-builder.md, docs/masterplan/00-product-spec.md §2.1, and docs/masterplan/02-engine-and-data.md §2.1 and §6. Ask me the open decisions. Reconcile with the feature API and the executor from Phases 3–5; open the kickoff PR.
```

## Steps

### 6.1 Feature library pages

Depends on: 5.12 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Your features are visible in the app: a library with versions, validation status, and where each feature is used.

#### Prerequisites

- Phase 5 complete.

#### Prompt

```text
Masterplan step 6.1 — Feature library pages.

Using the `/v1/features` endpoints from 5.2 (extend as needed: usage by strategy versions, validation status, analytics summary), build the Lab section: a feature list (name, latest version, validation badge, used-by count, last preview), a feature page with the code of the selected version (CodeMirror, read-only here), the parameter schema, the version history with diffs (reuse the diff view from 5.10), and the usage list. Phone: list and detail stack; code scrolls inside its box.

Playwright: open the library, open a seeded feature, switch versions, see the diff.

Not in this step: editing, preview.
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The usage list links to the strategies and versions that pin the feature.
3. The validation badge reflects the stored `ValidationReport` (passed, failed, not run).

#### Your checks

- Open the library on your phone and read a feature's code and history.

#### If it fails

- If versions show out of order, sort by `version_no`, never by created time strings.

### 6.2 Editor and preview run

Depends on: 6.1 · Plan mode: required · Reviews: step-reviewer, ui-verifier, code-review · Security: yes · Model hint: hard

#### Purpose

The heart of the lab: edit a feature's code and see it computed within a second, with lint and errors inline, on desktop and on the phone.

#### Prerequisites

- Step 6.1 merged.

#### Prompt

```text
Masterplan step 6.2 — Editor and preview run.

Make the feature page editable with the `CodeEditor` component from 5.5 (CodeMirror 6, Python mode, the symbol bar above the phone keyboard) and a "Preview" button that posts the draft code and parameters to `POST /v1/features/preview` (instrument, timeframe, range from a picker; defaults from settings), which runs through the warm executor from 4.5 and returns the computed series (downsampled for the window), summary statistics (count, NaN share, min, max, mean, std, last values), and lint results with line numbers; syntax errors return the line and are underlined in the editor. "Save as new version" posts to `/v1/features/{id}/versions` with a changelog; a draft is kept in local storage until saved. Previews must not create versions.

Playwright: edit a seeded feature, preview, see statistics, introduce a syntax error, see it underlined, fix it, save version 2.

Not in this step: the chart pane (6.3), the leak check in the UI (6.4).
```

#### Done means

1. Preview returns within about a second for a month of 5-minute bars after warm-up (timed test).
2. Playwright passes on both projects, including the syntax-error path.
3. User code runs only in the executor (a test asserts the server process never imports the draft).

#### Your checks

- On your phone, change a parameter default in a feature, tap Preview, read the statistics; then save version 2.

#### If it fails

- The iOS keyboard covering the editor: the editor container must use the visual viewport height; the symbol bar must stay above the keyboard.

### 6.3 Preview chart and statistics panel

Depends on: 6.2 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The preview is visual: the feature under the price chart, aligned, with its distribution and a quick forward-return relationship.

#### Prerequisites

- Step 6.2 merged.

#### Prompt

```text
Masterplan step 6.3 — Preview chart and statistics panel.

Extend the preview: show the price chart (`PriceChart` from 5.4) with the feature outputs as indicator panes (one pane per output, or overlaid on price when the feature declares `overlay=True`), aligned to bar closes; a statistics panel with the summary from 6.2, a histogram, and a quick "forward return by quintile" table for a configurable horizon computed server-side with the analytics module (clearly labelled as a quick look, with the trials counter). Phone: the chart and panes are full width; the statistics are a sheet.

Playwright: preview a seeded feature, assert a pane renders with the right number of points; desktop and phone.

Not in this step: the full analytics page (6.5).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The pane values at a given bar equal the API preview values (contract test).
3. The quintile table matches `fefat.analytics` for the same inputs (pytest).

#### Your checks

- Preview `rsi_stretch` on your phone: the pane follows the price chart as you scroll, and the quintile table shows whether extremes behave differently.

#### If it fails

- Misalignment by one bar between pane and price: the preview series must be stamped with `ts_close` converted the same way the bars are.

### 6.4 Leak results in the app

Depends on: 6.3 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: default

#### Purpose

Saving a feature runs the leak detector and shows you what it found, in words.

#### Prerequisites

- Step 6.3 merged.

#### Prompt

```text
Masterplan step 6.4 — Leak results in the app.

Run `ff.features.validate` as a `feature_validate` job on every new version (and on demand through `POST /v1/features/validate`), store the ValidationReport with the version, and show it on the feature page: a badge (passed, failed, warnings), the failing cut with the first differing row and both values, the lint findings with line numbers, and a short explanation of what the check means and what it cannot catch (from the module docstring). A failed version can still be saved but is marked, and the strategy builder warns when it is used.

Playwright: save a leaky feature (seeded `close.shift(-1)`), see the failed badge and the explanation; fix and save; see passed.

Not in this step: anything else.
```

#### Done means

1. Playwright passes on both projects.
2. The report shown in the UI equals the stored report (contract test).
3. A strategy using a failed feature shows the warning in its page and in the run dialog.

#### Your checks

- Save a deliberately leaky feature from your phone and read the explanation: it should tell you the first bar whose value changed when the future was removed.

#### If it fails

- Validation that takes minutes on long ranges should run on a bounded range by default (configurable), with the full check available on demand.

### 6.5 Feature analytics page

Depends on: 6.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, leakage-auditor · Security: no · Model hint: default

#### Purpose

Judge a feature's predictive power in the app, with honest statistics and the trials counter in view.

#### Prerequisites

- Step 6.4 merged.

#### Prompt

```text
Masterplan step 6.5 — Feature analytics page.

Build an Analytics tab on the feature page backed by `GET /v1/features/{id}/analytics` (an `analytics` job over a chosen instrument, timeframe, range, and horizons): quantile forward-return table with confidence intervals, IC by year and IC decay by horizon (ECharts), event study for boolean features, and a correlation matrix across selected library features (clustered heatmap). Show the trials counter and a one-paragraph reading guide. Results are cached by inputs.

Playwright: run analytics on the seeded predictive feature, assert the IC chart renders and the counter increments.

Not in this step: studies (Phase 11).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Page numbers equal `fefat.analytics` output (contract test).
3. The trials counter persists across sessions and increments per examined feature-horizon pair (test).

#### Your checks

- Run analytics on two of your features; the correlation heatmap shows whether they are redundant.

#### If it fails

- IC that looks too good on a long horizon is often overlapping-window inflation; the SDK uses daily rank IC with block bootstrap for a reason — check the page is calling the same function.

### 6.6 Combination builder

Depends on: 6.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Combine features without code, with the generated code always visible.

#### Prerequisites

- Step 6.4 merged.

#### Prompt

```text
Masterplan step 6.6 — Combination builder.

Build a "Combine" dialog in the Lab: pick one or two library features (with versions and parameters), choose a combinator from `fefat.features.combine` (arithmetic, comparison, cross, rolling window, normalisation, resample from a higher timeframe, spread across instruments), set its parameters with the schema-driven form, see the generated code and a live preview (6.3), name it, and save it as a new feature (version 1) whose JSON description is stored for later editing. Editing a combination reopens the dialog from the stored description. Phone: a stepper (pick, combine, preview, save).

Playwright: build `rsi(14) - rolling_mean(rsi(14), 10)`, preview, save; reopen and change the window.

Not in this step: the strategy builder.
```

#### Done means

1. Playwright passes on both projects.
2. The generated code equals the SDK combinator's code string for the same inputs (contract test), so the feature versions and validates like any other.
3. Reopening a saved combination restores the form exactly.

#### Your checks

- On your phone, build the z-score of ATR over 50 bars from existing features, preview it, save it.

#### If it fails

- If the generated code differs between the dialog and the SDK, the dialog is generating code itself; it must call the SDK through the API.

### 6.7 Rule builder

Depends on: 6.6, 5.5 · Plan mode: required · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: hard

#### Purpose

Entry and exit conditions over features, assembled in a form, producing the signal expressions of a signal strategy.

#### Prerequisites

- Steps 6.6 and 5.5 merged.

#### Prompt

```text
Masterplan step 6.7 — Rule builder.

Build the first half of the strategy builder on the strategy page: a rule editor where each rule is a tree of conditions over library features and constants (greater than, less than, between, crosses above/below, is true, within N bars of), combined with and/or groups, for long entry, short entry, long exit, short exit; features are picked from the library with their parameters; a live "signals preview" shows the count of entry signals over the preview range and marks them on the price chart. The builder state is the `builder_spec` JSON (schema defined here, versioned); `POST /v1/strategies/build` turns the spec into the Python `SignalStrategy` definition through the SDK and returns the code, which is shown read-only beside the form. Phone: rules as stacked cards; the code in a sheet.

Playwright: build a two-feature long-entry rule, see signal markers, view code.

Not in this step: the execution template form (6.8).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The generated code validates as a strategy version (it imports and produces a signal frame on synthetic data; test).
3. The builder spec round-trips through the SDK (spec → code → spec where possible, or spec stored alongside code; documented).

#### Your checks

- Build "RSI below 30 and price above session VWAP" on your phone and see the entry markers on the chart.

#### If it fails

- Signal counts that differ between the preview and a later backtest usually mean the preview used a different range or fidelity; the preview must state its range.

### 6.8 Execution-template form and code generation

Depends on: 6.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The second half of the builder: stops, targets, trailing, time rules, filters, and sizing from the `StrategySpec` schema, with the complete generated code and a "save as version".

#### Prerequisites

- Step 6.7 merged.

#### Prompt

```text
Masterplan step 6.8 — Execution-template form and code generation.

Render the execution template from the `StrategySpec` JSON schema (generated in 2.3) with the schema-driven form renderer, grouped as Entry, Exits, Filters, Sizing, with sensible defaults and inline help from the schema descriptions; combine it with the rule builder spec into the full `builder_spec`; generate the complete `SignalStrategy` Python definition through `/v1/strategies/build`; show it read-only with an "Eject to code" action that creates a code-mode version editable in the strategy page's editor from 5.5 (after which the builder is disabled for that strategy, with a clear note). "Save as new version" stores code and spec. Validate before saving (import in the executor).

Playwright: complete the template for the rule from 6.7, save version 1, open the code, eject, edit one line, save version 2, see the builder disabled.

Not in this step: running (already exists), the agent.
```

#### Done means

1. Playwright passes on both projects.
2. A builder-made version runs through the existing run dialog and produces trades on synthetic data (end-to-end test).
3. Ejected versions are marked `kind: code` and the builder is hidden for them.

#### Your checks

- Finish a strategy in the builder on your phone, read the generated code, run it.

#### If it fails

- If the form shows raw schema keys instead of labels, the Rust `schemars` attributes need `description` and `title`; fix at the source so the SDK docs improve too.

### 6.9 Builder-to-backtest end to end

Depends on: 6.8 · Plan mode: skip · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The lab and the builder are coherent, tested end to end, and demoed.

#### Prerequisites

- Step 6.8 merged.

#### Prompt

```text
Masterplan step 6.9 — Builder-to-backtest end to end.

Write one Playwright flow: create a feature in the editor, preview, save; combine it with a library feature; build a strategy with the rule builder and the execution template; run a backtest; open the trade chart; confirm the feature pane shows the feature used. Run the ui-verifier over the Lab and builder pages at both sizes and fix findings. Record a demo video; write docs/demo-lab.md with the click path. Update docs/engine-guide.md with a "Feature lab and builder" section.

Not in this step: new features.
```

#### Done means

1. The flow passes on both projects in CI.
2. The ui-verifier report shows no remaining phone issues.
3. `docs/demo-lab.md` exists with the video attached to the PR.

#### Your checks

- Follow `docs/demo-lab.md` on your phone.

#### If it fails

- Report the exact page and element; the fix belongs to that step's component.

## Phase exit

```text
/phase-exit 6 — Run the exit procedure for Phase 6: clean-clone suite including both end-to-end flows; /code-review high; /security-review (code execution from the editor); demo = docs/demo-lab.md; retro; backlog groomed; tag phase-6.
```
