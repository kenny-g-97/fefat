# Phase 6 — Feature lab and strategy builder

**Goal.** The hybrid workflow you chose: features written in a code editor with an instant chart and statistics preview, leak results shown in the app, analytics pages, a combination builder, a no-code strategy builder that generates the Python definition and runs a backtest, and an export of a builder-made strategy to NinjaTrader 8, TradingView, and MetaTrader 5, to backtest it there (D-110).

**You get.** Write a feature, preview it in a second, save a version, combine it, build a strategy from two features in a form, look at the generated code, run it. Export it as a script for NinjaTrader 8, TradingView, or MetaTrader 5, and compare that platform's backtest with FEAT's.

**Depends on.** Phase 5.

**Open decisions for the kickoff.** The default preview instrument and range; whether the builder's first release needs every execution-template option or a curated subset; which indicators and execution options the first exports cover (those of the templates and the cross-check first, or all 32 indicators); whether MQL4 joins step 6.12 once you can open MetaTrader 4 (D-110).

## Kickoff

```text
/phase-kickoff 6 — Read docs/masterplan/phases/P06-feature-lab-and-builder.md, docs/masterplan/00-product-spec.md §2.1, and docs/masterplan/02-engine-and-data.md §2.1 and §6. Ask me the open decisions. Reconcile with the feature API and the executor from Phases 3–5; open the kickoff PR.
```

## Steps

### 6.1 Feature library pages

Depends on: 5.13 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Your features are visible in the app: a library with versions, validation status, and where each feature is used.

#### Prerequisites

- Phase 5 complete.

#### Prompt

```text
Masterplan step 6.1 — Feature library pages.

Using the `/v1/features` endpoints from 5.2 (extend as needed: usage by strategy versions, validation status, analytics summary), build the Lab section: a feature list (name, latest version, validation badge, used-by count, last preview), a feature page with the code of the selected version (CodeMirror, read-only here), the parameter schema, the version history with diffs (reuse the diff view from 5.10), and the usage list.

Playwright: open the library, open a seeded feature, switch versions, see the diff.

Not in this step: editing, preview.
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The usage list links to the strategies and versions that pin the feature.
3. The validation badge reflects the stored `ValidationReport` (passed, failed, not run).

#### Your checks

- Open the library and read a feature's code and history.

#### If it fails

- If versions show out of order, sort by `version_no`, never by created time strings.

### 6.2 Editor and preview run

Depends on: 6.1 · Plan mode: required · Reviews: step-reviewer, ui-verifier, design-reviewer, code-review · Security: yes · Model hint: hard

#### Purpose

The heart of the lab: edit a feature's code and see it computed within a second, with lint and errors inline.

#### Prerequisites

- Step 6.1 merged.

#### Prompt

```text
Masterplan step 6.2 — Editor and preview run.

Make the feature page editable with the `CodeEditor` component from 5.5 (CodeMirror 6, Python mode) and a "Preview" button that posts the draft code and parameters to `POST /v1/features/preview` (instrument, timeframe, range from a picker; defaults from settings), which runs through the warm executor from 4.5 and returns the computed series (downsampled for the window), summary statistics (count, NaN share, min, max, mean, std, last values), and lint results with line numbers; syntax errors return the line and are underlined in the editor. "Save as new version" posts to `/v1/features/{id}/versions` with a changelog; a draft is kept in local storage until saved. Previews must not create versions.

Playwright: edit a seeded feature, preview, see statistics, introduce a syntax error, see it underlined, fix it, save version 2.

Not in this step: the chart pane (6.3), the leak check in the UI (6.4).
```

#### Done means

1. Preview returns within about a second for a month of 5-minute bars after warm-up (timed test).
2. Playwright passes on both projects, including the syntax-error path.
3. User code runs only in the executor (a test asserts the server process never imports the draft).

#### Your checks

- Change a parameter default in a feature, click Preview, read the statistics; then save version 2.

#### If it fails

- The iOS keyboard covering the editor: the editor container must use the visual viewport height; the symbol bar must stay above the keyboard.

### 6.3 Preview chart and statistics panel

Depends on: 6.2 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

The preview is visual: the feature under the price chart, aligned, with its distribution and a quick forward-return relationship.

#### Prerequisites

- Step 6.2 merged.

#### Prompt

```text
Masterplan step 6.3 — Preview chart and statistics panel.

Extend the preview: show the price chart (`PriceChart` from 5.4) with the feature outputs as indicator panes (one pane per output, or overlaid on price when the feature declares `overlay=True`), aligned to bar closes; a statistics panel with the summary from 6.2, a histogram, and a quick "forward return by quintile" table for a configurable horizon computed server-side with the analytics module (clearly labelled as a quick look, with the trials counter).

Playwright: preview a seeded feature, assert a pane renders with the right number of points.

Not in this step: the full analytics page (6.5).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The pane values at a given bar equal the API preview values (contract test).
3. The quintile table matches `fefat.analytics` for the same inputs (pytest).

#### Your checks

- Preview `rsi_stretch`: the pane follows the price chart as you scroll, and the quintile table shows whether extremes behave differently.

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

- Save a deliberately leaky feature and read the explanation: it should tell you the first bar whose value changed when the future was removed.

#### If it fails

- Validation that takes minutes on long ranges should run on a bounded range by default (configurable), with the full check available on demand.

### 6.5 Feature analytics page

Depends on: 6.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer, leakage-auditor · Security: no · Model hint: default

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

Depends on: 6.4 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Combine features without code, with the generated code always visible.

#### Prerequisites

- Step 6.4 merged.

#### Prompt

```text
Masterplan step 6.6 — Combination builder.

Build a "Combine" dialog in the Lab: pick one or two library features (with versions and parameters), choose a combinator from `fefat.features.combine` (arithmetic, comparison, cross, rolling window, normalisation, resample from a higher timeframe, spread across instruments), set its parameters with the schema-driven form, see the generated code and a live preview (6.3), name it, and save it as a new feature (version 1) whose JSON description is stored for later editing. Editing a combination reopens the dialog from the stored description.

Playwright: build `rsi(14) - rolling_mean(rsi(14), 10)`, preview, save; reopen and change the window.

Not in this step: the strategy builder.
```

#### Done means

1. Playwright passes on both projects.
2. The generated code equals the SDK combinator's code string for the same inputs (contract test), so the feature versions and validates like any other.
3. Reopening a saved combination restores the form exactly.

#### Your checks

- Build the z-score of ATR over 50 bars from existing features, preview it, save it.

#### If it fails

- If the generated code differs between the dialog and the SDK, the dialog is generating code itself; it must call the SDK through the API.

#### Amendment

2026-11-21 (D-110, your check of step 5.5's pull request): you asked to make new strategies by using and combining features from the feature library. A combination saved here is a library feature like any other, so step 6.7's rules can pick it. Its stored description (`fefat.features.combinations`), a tree of named operators over library features, is what the exports of steps 6.10 to 6.12 translate.

### 6.7 Rule builder

Depends on: 6.6, 5.5 · Plan mode: required · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: hard

#### Purpose

Entry and exit conditions over features, assembled in a form, producing the signal expressions of a signal strategy.

#### Prerequisites

- Steps 6.6 and 5.5 merged.

#### Prompt

```text
Masterplan step 6.7 — Rule builder.

Build the first half of the strategy builder on the strategy page: a rule editor where each rule is a tree of conditions over library features and constants (greater than, less than, between, crosses above/below, is true, within N bars of), combined with and/or groups, for long entry, short entry, long exit, short exit; features are picked from the library with their parameters; a live "signals preview" shows the count of entry signals over the preview range and marks them on the price chart. The builder state is the `builder_spec` JSON (schema defined here, versioned); `POST /v1/strategies/build` turns the spec into the Python `SignalStrategy` definition through the SDK and returns the code, which is shown read-only beside the form.

Playwright: build a two-feature long-entry rule, see signal markers, view code.

Not in this step: the execution template form (6.8).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The generated code validates as a strategy version (it imports and produces a signal frame on synthetic data; test).
3. The builder spec round-trips through the SDK (spec → code → spec where possible, or spec stored alongside code; documented).

#### Your checks

- Build "RSI below 30 and price above session VWAP" and see the entry markers on the chart.

#### If it fails

- Signal counts that differ between the preview and a later backtest usually mean the preview used a different range or fidelity; the preview must state its range.

#### Amendment

2026-11-21 (D-110, your check of step 5.5's pull request): this step is the revisit of step 5.5's Strategies pages you asked for once the Feature Lab exists. Read those pages and `web/DESIGN.md`'s Strategy page pattern first, and say in the plan what changes on them. New strategies are made here by using and combining features from the feature library, step 6.6's combinations among them, so New strategy offers to start from the library's features beside the templates. `builder_spec` names each feature by its library name, version, and parameters and holds no free Python, since steps 6.10 to 6.12 translate it into other platforms' languages.

### 6.8 Execution-template form and code generation

Depends on: 6.7 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

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

- Finish a strategy in the builder, read the generated code, run it.

#### If it fails

- If the form shows raw schema keys instead of labels, the Rust `schemars` attributes need `description` and `title`; fix at the source so the SDK docs improve too.

#### Amendment

2026-11-21 (D-110, your check of step 5.5's pull request): a version saved with its `builder_spec` is what the exports of steps 6.10 to 6.12 read. An ejected code version cannot be exported, so Eject to code says so before you choose it, and the ejected version's page says so after.

### 6.9 Builder-to-backtest end to end

Depends on: 6.8 · Plan mode: skip · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

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
2. The ui-verifier report shows no remaining issues.
3. `docs/demo-lab.md` exists with the video attached to the PR.

#### Your checks

- Follow `docs/demo-lab.md`.

#### If it fails

- Report the exact page and element; the fix belongs to that step's component.

### 6.10 NinjaScript export

Depends on: 6.8 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer, ui-verifier, design-reviewer · Security: yes · Model hint: hard

#### Purpose

Export a builder-made strategy as a NinjaScript strategy, backtest it in NinjaTrader 8, and compare its trades with FEAT's run of the same version.

#### Prerequisites

- Step 6.8 merged: a strategy version saved with its `builder_spec`.
- The Phase 6 kickoff's answer on which indicators and execution options the first exports cover.
- For Your checks: NinjaTrader 8 with the instrument's data, and the same bars imported into FEAT from NinjaTrader.

#### Prompt

```text
Masterplan step 6.10 — NinjaScript export.

Read D-110, docs/spec/fill-semantics.md, docs/validation/nautilus-comparison.md (its NinjaTrader 8 section and difference classes), python/tests/external/README.md (the NinjaTrader runbook), python/tests/external/ninjatrader/FefatCrossCheck.cs, fefat.features.combine and fefat.features.combinations, fefat.indicators, strategy_spec.schema.json, and the `builder_spec` schema of step 6.7.

Build the export's core and its first target. An export is for backtesting on the other platform, to cross-check FEAT's results: it writes a file, places no orders, and connects to nothing.

1. SDK: `ff.strategy.export(version, target)` gives the script's file name, its text, and notes on what differs on the target. It reads a builder-made version's `builder_spec` alone, runs none of the trader's code, and gives the same text for the same version each time. The script's header names the strategy, its version, and its hash. Text from the strategy, such as its hypothesis, is escaped for the target's comments and strings, since the trader compiles the file.
2. Translations: one table per target of each indicator, each combination node, and each execution option the kickoff chose. An indicator is written out as FEAT defines it (seed, smoothing, warm-up) wherever the platform's built-in differs, so that its values match after the warm-up.
3. Refusals: a code version, a custom Python feature, a node or option without a translation, and higher-timeframe or cross-instrument nodes are refused by name, all of them at once, and no partial script is written.
4. App: `GET /v1/strategies/{id}/versions/{n}/export?target=ninjascript`, and an Export card on the strategy page with the target, the script read-only, Copy, Download, and the notes. A code version's card says why it cannot be exported. Steps 6.11 and 6.12 add a target and nothing else to the card.
5. Notes, in the script and on the page: NinjaTrader's fills along a bar's path and its limit fills on a gap (step 2.14's classes `bar_path` and `gap_limit_clamped`), its commission template, its session template and time zone, and its contract rolls.
6. The comparison: reuse `fefat_xcheck`'s reader of NinjaTrader's Trades export, its matching of trades, and its difference classes, with FEAT's run of the same version on the same bars under the compatibility profile of scripts/xcheck.py. Write its report under docs/validation/.
7. docs/engine-guide.md gains a section "Exporting a strategy".

Not in this step: Pine Script (6.11), MQL5 (6.12), MQL4, code strategies, custom Python features, and live trading.
```

#### Done means

1. The same version exports the same text twice, and golden scripts for fixed specs hold that text (test).
2. Every indicator, combination node, and execution option either translates or is refused by name, and text from the strategy cannot break out of a comment or a string (tests).
3. The exported script compiles in NinjaTrader 8, and its Strategy Analyzer trades match FEAT's run of the same version apart from the documented classes (the report under `docs/validation/`, with no `unknown` difference).
4. The Export card passes Playwright with screenshots, an exported strategy and a refused one among them.
5. `docs/engine-guide.md` says how to export a strategy, what an export covers, and what differs on NinjaTrader 8.

#### Your checks

- Export a builder-made strategy, save the file into `Documents\NinjaTrader 8\bin\Custom\Strategies\`, compile it in the NinjaScript Editor (F5), and run it in Strategy Analyzer on the same instrument and dates as FEAT's run. Export the Trades tab and run the comparison: its report counts the trades that match and names a class for each that differs.

#### If it fails

- If NinjaTrader refuses to compile the file, delete it and compile again: your other strategies keep running on the last good build. The fix belongs in the target's translation table.
- A trade that differs with no class is a bug in the translation or a rule the notes do not name: find which before widening a class.
- Indicator values that differ after the warm-up usually mean the script used the platform's built-in where FEAT's definition differs.

### 6.11 Pine Script export

Depends on: 6.10 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer, ui-verifier, design-reviewer · Security: yes · Model hint: default

#### Purpose

Export a builder-made strategy as a Pine Script strategy, backtest it in TradingView's Strategy Tester, and compare its trades with FEAT's run on the same bars.

#### Prerequisites

- Step 6.10 merged.
- For Your checks: TradingView in your browser. Exporting a chart's bars needed a paid plan, Essential or above, when the data-source research was done; the step's plan gives the free route first and the monthly cost of any plan the check needs.

#### Prompt

```text
Masterplan step 6.11 — Pine Script export.

Read D-110, step 6.10's export core and report, and docs/masterplan/appendix/research-data-sources.md (TradingView). First look up TradingView's current Pine Script reference (the language version, `strategy()`, its order functions, and a script's limits) and what the Strategy Tester and the chart's export offer on each plan, since both change. Recommend the free route for the check first, say what it cannot prove (it may compare a shorter window by hand), and give the monthly cost of any paid plan the check would need.

Add the `pinescript` target to step 6.10's core:

1. Its translation table for the same indicators, combination nodes, and execution options, with the same refusals by name, and text from the strategy escaped for Pine's comments and strings.
2. The notes, in the script and on the page: the Strategy Tester's own assumption about the path inside a bar, its fills of limit and stop orders, its commission and slippage settings, the chart's session and time zone, and that a continuous chart symbol rolls on TradingView's schedule rather than FEAT's.
3. The comparison runs on TradingView's own bars: the trader exports the chart's bars, imports them with the wizard's TradingView preset, runs the same version in FEAT, and compares with the Strategy Tester's list of trades. A difference FEAT's classes do not cover gets a class of its own, named for the rule that explains it.
4. The Export card offers Pine Script with no other change to it, and the engine guide's "Exporting a strategy" says what differs on TradingView.

Not in this step: MQL5 (6.12), MQL4, code strategies, custom Python features, alerts or webhooks, and live trading.
```

#### Done means

1. The same version exports the same text twice, and golden scripts for fixed specs hold that text (test).
2. Every indicator, combination node, and execution option either translates or is refused by name, and text from the strategy cannot break out of a comment or a string (tests).
3. The exported script compiles in the Pine Editor, and the Strategy Tester's trades match FEAT's run on the same bars apart from the documented classes (the report under `docs/validation/`, with no `unknown` difference), on the route the step's plan settled with you.
4. The Export card offers Pine Script (Playwright, with a screenshot).
5. `docs/engine-guide.md` says what differs on TradingView.

#### Your checks

- Export a builder-made strategy as Pine Script, paste it into TradingView's Pine Editor, add it to a chart of the same instrument and timeframe, and compare its list of trades with FEAT's as the step's report says.

#### If it fails

- If the Pine Editor refuses the script, the language may have moved on: read the current reference and fix the target's table.
- Trades all off by the same number of bars or hours usually mean another session or time zone on the chart; the notes must name the chart settings the script expects.

### 6.12 MQL5 export

Depends on: 6.10 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer, ui-verifier, design-reviewer · Security: yes · Model hint: default

#### Purpose

Export a builder-made strategy as an Expert Advisor for MetaTrader 5, backtest it in the Strategy Tester, and compare its trades with FEAT's run on the same bars.

#### Prerequisites

- Step 6.10 merged.
- For Your checks: MetaTrader 5 with a demo account, both free, at a broker that lists a symbol you want to test.

#### Prompt

```text
Masterplan step 6.12 — MQL5 export.

Read D-110, step 6.10's export core and report, docs/data-guide.md (import profiles, and a product FEAT does not know), and MetaQuotes' current MQL5 reference for Expert Advisors (`OnTick`, detecting a new bar, `CTrade`, and the Strategy Tester's tick modes).

Add the `mql5` target to step 6.10's core:

1. Its translation table for the same indicators, combination nodes, and execution options, with the same refusals by name, and text from the strategy escaped for MQL5's comments and strings. The Expert Advisor decides once per bar close. Tick size and tick value are read from the chart's symbol, and time rules take the broker's server time zone as an input.
2. The notes, in the script and on the page: the Strategy Tester's tick model, the broker's spread and commission, the account's netting or hedging mode, the broker's server time, and that a broker's symbol, such as a CFD, may not be the contract the strategy names.
3. FEAT has no MetaTrader preset: add one for MetaTrader 5's export of a symbol's bars, its layout read from a real file kept outside the repository and tested on a generated one, so that the wizard imports them. A symbol FEAT does not know needs a profile carrying its instrument, as the data guide says.
4. The comparison runs on the broker's bars: the trader exports them from MetaTrader 5, imports them into FEAT, runs the same version, and compares with the Strategy Tester's trades. A difference FEAT's classes do not cover gets a class of its own, named for the rule that explains it.
5. The Export card offers MQL5 with no other change to it, and the engine guide's "Exporting a strategy" says what differs on MetaTrader 5.

Not in this step: MQL4 (`BACKLOG.md`), code strategies, custom Python features, and live trading.
```

#### Done means

1. The same version exports the same text twice, and golden scripts for fixed specs hold that text (test).
2. Every indicator, combination node, and execution option either translates or is refused by name, and text from the strategy cannot break out of a comment or a string (tests).
3. The exported Expert Advisor compiles in MetaEditor, and the Strategy Tester's trades match FEAT's run on the same bars apart from the documented classes (the report under `docs/validation/`, with no `unknown` difference).
4. The wizard imports a MetaTrader 5 export of bars through its new preset (test on a generated file), and the Export card offers MQL5 (Playwright, with a screenshot).
5. `docs/engine-guide.md` says what differs on MetaTrader 5.

#### Your checks

- Export a builder-made strategy as MQL5, save it into MetaTrader 5's `MQL5\Experts` folder, compile it in MetaEditor, run it in the Strategy Tester on the symbol and dates of the bars you imported, and compare its trades with FEAT's as the step's report says.

#### If it fails

- Trades off by a constant number of hours usually mean the broker's server time zone input, or its clock change, is wrong.
- Positions that stack or reverse differently usually mean the account's netting or hedging mode differs from what the Expert Advisor expects.

## Phase exit

```text
/phase-exit 6 — Run the exit procedure for Phase 6: clean-clone suite including both end-to-end flows; /code-review high; /security-review (code execution from the editor); demo = docs/demo-lab.md; retro; backlog groomed; tag phase-6.
```
