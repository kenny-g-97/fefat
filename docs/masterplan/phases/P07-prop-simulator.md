# Phase 7 — Prop simulator

**Goal.** The prop-firm simulator from `03-prop-simulator.md`: rules as dated, sourced data; an account state machine with a Python reference; replay of an existing backtest file — a saved FEFAT run or a trade log imported from another platform — through the rules and your prop strategy, never re-running the trading strategy; Monte Carlo with a cash ledger; and the pages to run and read it all.

**You get.** Pick a saved backtest, prop rules, and a prop strategy, and get pass probabilities, payouts, costs, and a plan ranking in seconds — without re-running anything.

**Depends on.** Phase 6 in the written order. Steps 7.1–7.8 need only the SDK and the run artifacts from Phase 2, including the trade paths every run stores since step 2.13; 7.9–7.11 need the app (Phase 6). If you move this phase earlier at a kickoff, amend 7.1's `Depends on` line.

**Skills.** `backtest-expert` and `software-design-principles` for every step: the account state machine and the replay are backtest code, and the skill's sample-size and friction rules apply to the Monte Carlo and the plan ranking; `frontend-design` with `web/DESIGN.md` for 7.9–7.11.

**Open decisions for the kickoff.** The first three plans to encode (suggested: Topstep Trading Combine → XFA, My Funded Futures Rapid or Pro, Tradeify Growth or Select); the bankroll and horizon defaults; whether you trade micros or minis in evaluations; which other platforms' trade logs to import first (for example NinjaTrader, Sierra Chart, TradeStation, or TradingView strategy-tester exports).

## Kickoff

```text
/phase-kickoff 7 — Read docs/masterplan/phases/P07-prop-simulator.md, docs/masterplan/03-prop-simulator.md, and docs/masterplan/appendix/research-prop-firms.md. Ask me the open decisions. Check the firms' current pages for the three chosen plans and note changes since the research (do not encode yet). Reconcile the steps with the run artifacts as they now exist (trades and trade paths from step 2.13); open the kickoff PR.
```

## Steps

### 7.1 Rule schema, preset format, refresh skill

Depends on: 6.9 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Every prop rule the research found can be expressed in one schema, presets are files with sources and worked examples, and there is a repeatable way to refresh them.

#### Prerequisites

- Phase 7 kickoff done.

#### Prompt

```text
Masterplan step 7.1 — Rule schema, preset format, refresh skill.

Read docs/masterplan/03-prop-simulator.md §2 and the taxonomy in docs/masterplan/appendix/research-prop-firms.md §1. Define the rule schema as Rust types in `fefat-prop` with serde and schemars (Firm, Plan with fees and commissions, Stage, drawdown, daily loss, consistency, session, position, payout, transitions, conduct), generate `python/fefat/src/fefat/prop/rules.schema.json`, and add Pydantic models in `fefat.prop`. Define the preset file format `python/fefat/src/fefat/prop/presets/<firm>/<plan>@<as-of>.yaml`: the rules plus `sources` (URLs with retrieval dates), `status` (draft, verified, stale), and `examples` — worked examples transcribed from the firm's documentation (for instance Topstep 50K: limit 48,000; 48,500 after +500; unchanged after −500), each a small scenario of balance or equity events and expected rule outcomes. Write a loader and a validator (`fefat prop validate-presets`).

Write the `prop-preset-refresh` skill under `.claude/skills/`: for a named preset, re-read every source URL, diff the rules against the current page text, and propose a new `@<today>` preset file with updated sources and examples; never edit an existing version.

Encode one preset in `draft` status (Topstep Trading Combine 50K) as the schema's first test; its examples run in 7.2.

Not in this step: the state machine, the replay.
```

#### Done means

1. Every taxonomy row (A1–G6) in the research appendix maps to a schema field or an explicit "not modelled" entry in `docs/prop-schema-coverage.md`.
2. The schema JSON is generated and checked in CI; the Pydantic models round-trip the Topstep draft preset.
3. The refresh skill exists and its instructions are tested by a dry run on the draft preset (no changes expected).

#### Your checks

- Open the Topstep preset file and read it next to Topstep's help page for the Trading Combine: the numbers and the sources match.

#### If it fails

- A rule that fits no field is a schema gap: extend the schema (with the ADR amended), never bend the preset.

### 7.2 Account state machine, reference implementation, first three presets

Depends on: 7.1 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The rules behave exactly as the firms describe, proven by their own examples, in a readable Python implementation first and then in Rust.

#### Prerequisites

- Step 7.1 merged; the three plans chosen.

#### Prompt

```text
Masterplan step 7.2 — Account state machine, reference implementation, first three presets.

Read docs/masterplan/03-prop-simulator.md §3. Implement the account state machine in Python first (`python/fefat/src/fefat/reference/prop.py`, readable, rule by rule, integer money): states and events as specified; drawdown types with high-water-mark sources and lock levels; daily loss (soft and hard) with anchors and resets; consistency windows and effects; minimum and qualifying days; session rules; position limits and scaling; payout gates, amounts, caps, splits, cadence, and effects on the floor; transitions with side effects; fees and expiry. Then implement the same in Rust in `fefat-prop` and add a differential test over generated event sequences (Hypothesis) plus every preset's worked examples as tests of both implementations.

Encode the three chosen plans as presets with sources, retrieval dates, and examples (at least one breach and one payout example each), and mark them `verified` only when their examples pass. Record in each preset the automation policy and hold-time rules as feasibility flags.

Not in this step: reading backtest files and the replay (7.3).
```

#### Done means

1. The three presets' examples pass in both implementations; the presets are `verified`.
2. The differential test passes on 10,000 generated event sequences.
3. `docs/prop-schema-coverage.md` lists which rules each preset exercises.

#### Your checks

- In a notebook, feed the Topstep reference machine a hand-made sequence (start 50,000; +600 day; −400 day; payout request) and read the state after each event; compare with your own understanding of the rules.

#### If it fails

- If a firm's example cannot be reproduced, the rule text is ambiguous; record both readings in the preset as `ambiguities`, pick the conservative one, and flag the preset `draft`.

### 7.3 Backtest-file replay: drawdowns, daily loss, flat-by, limits

Depends on: 7.2 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The core of the simulator: an existing backtest's trades and trade paths run through a prop account's rules — breaches, daily-loss lockouts, flat-by times, contract limits — without ever re-running the strategy.

#### Prerequisites

- Step 7.2 merged; saved runs with trade paths (every run since step 2.13).

#### Prompt

```text
Masterplan step 7.3 — Backtest-file replay: drawdowns, daily loss, flat-by, limits.

Read docs/masterplan/03-prop-simulator.md §3 and §4. Define the backtest file the simulator reads (`fefat.prop.BacktestFile`): a saved run's trades, fills, trade paths, funding payments, instrument specification, calendar reference, and fee table, loaded from the run folder or from the run exported as one file (`fefat runs export <run_id>`: a zip of the same tables and run.json, marked in its manifest as for your own use because its prices come from licensed data); imported trade logs follow in 7.5. Implement the replay in `fefat-prop`: walk the trades in time order and turn each trade path and its fills into account events — path marks for intraday-trailing high-water marks and breach tests on equity, session ends for end-of-day high-water marks and daily tallies, firm day anchors for snapshot-style rules (minute marks give equity at any minute boundary), and flat-by times — computing profit and loss from prices and fills for the chosen size and contract, with the rule set's commission table (or the backtest's fee table when the rule set has none). When a rule fires during a trade (a breach, a soft daily-loss lockout, a flat-by), cut the trade at that point of its path, price the liquidation at the path's price there plus the configured liquidation slippage (default: the fill specification's stop slippage), record the reason, and skip the backtest's later trades while the account is locked or failed. Contract limits and scaling tiers cap the size. The replay never runs strategy code. Expose `fefat.prop.replay(backtest_file, rule_set, size=…)` with an `account_events` table and the replay notes from 03 §4.5 (for example how many trades followed a forced cut on the same day).

Tests: scenarios (an intraday-trailing breach inside a trade that the trade's close would not show; a daily-loss breach after a new session starts inside a trade held overnight; a soft daily-loss lockout that skips the day's remaining trades; a flat-by cut across a daylight-saving change; a trade with two partial exits replayed at three contracts; a scaling tier effective next session); replay of compact paths equals the Python reference machine fed with the test-only full-resolution paths from 2.13, with liquidations priced the same way in both (Hypothesis, 10,000 cases); a run without trade paths is refused with a clear message; the export file round-trips.

Not in this step: payouts and lifecycle (7.4), imported trade logs (7.5), prop strategies (7.6).
```

#### Done means

1. The scenarios pass; replay equals the full-resolution reference on 10,000 generated cases (seeds recorded in the PR).
2. `replay` on a synthetic year produces `account_events` with breaches and lockouts where planted, and every cut trade carries its reason.
3. Replaying a 5-year backtest takes milliseconds (timed), and no strategy code is imported during a replay (test).

#### Your checks

- In a notebook, replay one of your saved runs under the Topstep preset for one month and read `account_events`: do the lockouts and any breach fall on the days you would expect from the equity curve? The notebook prints the replay time, and nothing re-ran.

#### If it fails

- A breach you can see in the trade path but missing from the events means the path conversion skipped a new low; fix the conversion, not the rules.

### 7.4 Payouts, consistency, scaling, lifecycle, fees

Depends on: 7.3 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The whole account life is simulated from a backtest file: evaluation, funding, payouts with their gates and caps, consistency effects, resets, expiry, and fees.

#### Prerequisites

- Step 7.3 merged.

#### Prompt

```text
Masterplan step 7.4 — Payouts, consistency, scaling, lifecycle, fees.

Complete the replay with the account lifecycle: evaluation pass conditions (target, minimum days, consistency with raise-target or block-payout effects), transition to funded with side effects, payout requests under a simple default (request as soon as eligible), gates (qualifying days, buffers), amount rules, caps by payout number, splits, cadence, effects on the floor, lifetime caps, expiry and resets, and fee events (evaluation, activation, monthly, reset, data) recorded in a cash ledger separate from the simulated balance. Add `account_summary` (stage reached, days, payouts, fees, net cash) to the replay result.

Tests: each verified preset's payout examples pass through the replay; a generated-sequence differential test against the reference machine covers transitions; ledger identity (net cash = payouts − fees).

Not in this step: prop strategies (7.6), Monte Carlo (7.7).
```

#### Done means

1. Preset payout examples pass through the replay; differential tests pass.
2. `account_summary` for a synthetic profitable backtest shows pass, funding, and payouts with correct caps.
3. The cash ledger reconciles (test).

#### Your checks

- Replay a year of one of your saved runs under one preset and read the summary: did it pass, when, how many payouts, how much net cash after fees?

#### If it fails

- Payout caps by payout number are the usual error source; the preset examples must include a third payout.

### 7.5 Imported trade logs and path enrichment

Depends on: 7.4 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: yes · Model hint: hard

#### Purpose

Backtests made elsewhere — another platform's strategy tester or your own trade records — can be prop-simulated too, at the precision their trade log allows.

#### Prerequisites

- Step 7.4 merged; a trade-list export from a platform you use, for your check.

#### Prompt

```text
Masterplan step 7.5 — Imported trade logs and path enrichment.

Read docs/masterplan/03-prop-simulator.md §4.1 and §4.4, and the import profiles from step 1.10. Implement `fefat prop import-trades <file> --profile <name>`: a trade-log importer using import profiles of kind `trade_log` (column mapping for entry and exit times and prices, side, quantity, instrument, commission, and optional MAE, MFE, and initial stop; time zone), presets for the platforms chosen at the kickoff tested on small synthetic samples in each layout, and `--preview`, which shows the trades as they would be stored before anything is written. The imported log becomes a `BacktestFile` stored under the workspace, with a path fidelity recorded per trade: `close-only` (entries and exits), `excursions` (with MAE and MFE), or `enriched:<resolution>` — when market data for the instrument and period is in the store, each trade's path is rebuilt by marking the recorded position to market on the stored bars or ticks (no strategy logic runs; the trade's own entries and exits are kept). The profile can give a worst-case adverse excursion for logs without stops. Overlapping trades on the same instrument and side become legs of one position; overlapping positions across instruments or on opposite sides are refused with a clear message (portfolio simulation is in the backlog). The replay treats each fidelity as 03 §4.4 describes — loss rules assume the worst order of extremes, profit targets count only closed trades at `excursions` fidelity, and a `close-only` log without stops or a worst case reports "pass, intraday unchecked" — and every result states its fidelity.

Tests: each preset imports its sample; enriching the trades of a FEFAT run on synthetic data reproduces that run's own trade paths exactly; replays at `excursions` fidelity, and at `close-only` fidelity with stops or a worst case, never report a plain pass that the full path fails (property test); overlapping positions are merged or refused as described; a malformed file is rejected with the row and column at fault.

Not in this step: the pages (7.10), presets beyond the kickoff's list.
```

#### Done means

1. Each preset imports its synthetic sample; the enrichment test reproduces FEFAT's own trade paths.
2. The conservative-treatment property test passes.
3. Imported backtest files list their fidelity, and replay results show it.

#### Your checks

- Export the trade list of a strategy from your own charting or trading platform, run `fefat prop import-trades <file> --profile <closest preset> --preview`, import it, enrich it from your stored data, and replay it under one preset.

#### If it fails

- If enriched results differ from the platform's own profit and loss, check the contract (ES or MES) and the time zone in the profile first; the preview shows both.

### 7.6 Prop strategy layer and cash ledger

Depends on: 7.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Your prop strategy as data: accounts over time, sizing per stage, payouts and reinvestment, allocation — simulated over one backtest file's trades with real-money accounting.

#### Prerequisites

- Step 7.5 merged.

#### Prompt

```text
Masterplan step 7.6 — Prop strategy layer and cash ledger.

Read docs/masterplan/03-prop-simulator.md §5. Define `PropStrategySpec` as Rust types with schemars (and Pydantic models): accounts over time (plans to buy, maximum evaluation and funded accounts, start schedule and stagger, actions on fail, pass, and expiry, conditioned on bankroll); sizing per stage (fixed, as recorded in the backtest and scaled, risk-based on each trade's initial risk, or a cushion ladder; mini or micro contracts; partial exits re-allocated across the new size with the recorded fractions and the engine's rounding rule; firm limits enforced); payouts (when to request, minimum amount, buffer kept, share recycled into evaluations); allocation (copy all, rotate, by session, by firm, staggered start; optional per-account noise). Implement the multi-account simulation in `fefat-prop`: all accounts consume the same backtest file's trades (so correlation is structural), each account runs the replay from 7.3–7.4, the prop strategy makes its decisions at the defined moments, and the bankroll ledger records fees, resets, activations, and payouts after split. Expose `fefat.prop.simulate(backtest_file, rule_sets, prop_strategy, bankroll, horizon)` with a `PropSimResult` (timelines per account, cash curve, summary).

Tests: a one-account prop strategy equals plain replay; copy-all with two accounts fails both on the same day as the single account; staggered starts shift failures accordingly; ledger identity holds; firm account caps are respected.

Not in this step: Monte Carlo (7.7), pages.
```

#### Done means

1. The prop-strategy tests pass; `PropSimResult` timelines are correct on hand-built cases.
2. The schema and Pydantic models round-trip; three prop-strategy presets exist (one conservative evaluation; two staggered evaluations; a five-account copier).
3. A 10-account, 5-year simulation runs in under a second (timed).

#### Your checks

- In a notebook, simulate one of your saved backtests under "two staggered evaluations at Topstep, conservative sizing when funded" and read the cash curve and the account timelines.

#### If it fails

- If two copied accounts fail on different days, the allocation is not sharing the trades; that is a correctness bug.

### 7.7 Monte Carlo

Depends on: 7.6 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Distributions, not single paths: every start date, bootstrapped days, stress, and the report metrics from the design.

#### Prerequisites

- Step 7.6 merged.

#### Prompt

```text
Masterplan step 7.7 — Monte Carlo.

Read docs/masterplan/03-prop-simulator.md §6. Implement in `fefat-prop`: rolling start dates over the backtest file's history; a stationary bootstrap of whole session-days shared by all accounts in a path (mean block length by the Politis–White rule, documented); stress options (ticks haircut on every fill, random trade skipping, cost multiplier); seeded, parallel over paths with Rayon. Report: pass probability and time to pass; probability and time of first payout; net cash at the horizon (mean, median, 5/25/75/95 percentiles); probability of net loss; maximum bankroll drawdown; cost per funded account; failure reasons; effective sample size; the path fidelity and replay notes; and the feasibility flags from the preset. Expose `fefat.prop.monte_carlo(...)` returning frames plus a text report; add plan ranking across rule sets by median net cash and by probability of net loss.

Tests: with zero randomness the Monte Carlo equals the rolling-start-date set; bootstrap paths preserve day-level dependence (a planted autocorrelation survives); reports reproduce with the same seed.

Not in this step: pages.
```

#### Done means

1. Determinism and bootstrap tests pass; the report fields match the design list.
2. 1,000 paths × 10 accounts × 5 years completes in well under a minute on this PC (timed in the PR).
3. The plan ranking is produced for the three presets on synthetic data.

#### Your checks

- In a notebook, run 1,000 paths on one of your saved backtests under the three presets and read the ranking and the 5th-percentile net cash: that is the number that tells you whether this is worth your money.

#### If it fails

- If results change with the thread count, a reduction is unordered; results must be identical for any number of threads (seeded per path).

### 7.8 SDK polish, notebook, plan ranking

Depends on: 7.7 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The prop simulator is usable from notebooks with a clear API and documented in your words.

#### Prerequisites

- Step 7.7 merged.

#### Prompt

```text
Masterplan step 7.8 — SDK polish, notebook, plan ranking.

Review the `fefat.prop` API for consistency (`rule_sets.load`, `prop_strategies.load`, `BacktestFile.from_run`, `BacktestFile.from_export`, `import_trades`, `replay`, `simulate`, `monte_carlo`, `rank_plans`), add docstrings with examples, and write `notebooks/07-prop-simulator.ipynb`: load a saved run as a backtest file, replay it under the three presets, simulate a prop strategy, run Monte Carlo, rank plans, show feasibility flags and the path fidelity, then import a trade log from another platform and simulate it the same way. Write `docs/prop-guide.md` explaining the three inputs, the rule schema in plain words, how to add a preset, what each path fidelity means, what the report fields mean, and what replay does not model.

Not in this step: pages.
```

#### Done means

1. The notebook runs on your data.
2. `docs/prop-guide.md` explains every report field and every path fidelity in one sentence each.
3. Every public function has a docstring with an example.

#### Your checks

- Run the notebook end to end; read the guide's explanation of "probability of net loss" and of the `excursions` fidelity, and confirm they match your understanding.

#### If it fails

- Long Monte Carlo times in the notebook: reduce paths for the demo and state the production default.

### 7.9 Rule-set and prop-strategy pages

Depends on: 7.8, 6.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Rule sets and prop strategies are managed in the app with versions, status, and sources visible.

#### Prerequisites

- Steps 7.8 and 6.9 merged.

#### Prompt

```text
Masterplan step 7.9 — Rule-set and prop-strategy pages.

Implement the prop endpoints from docs/masterplan/01-architecture.md §7 for rule sets and versions and for prop strategies (`/prop/strategies`) and versions, and build the Prop section: a rule-set library (presets with status badge, as-of date, firm, plan, sources; custom rule sets created from a preset as a starting point) with a schema-driven editor for custom sets (grouped by stage, with help text) and version history; a prop-strategy library with the schema-driven form for the four dimensions and the three presets from 7.6. Phone: forms stack; sources open in the browser.

Playwright: open a preset, duplicate it as custom, change the daily loss, save version 1; create a prop strategy from a preset.

Not in this step: backtest files and simulations (7.10).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Preset files and database rule sets share one schema; a custom set validates like a preset.
3. Sources and the automation flag are visible on the rule-set page.

#### Your checks

- On your phone, open the Topstep preset and read its sources and status; duplicate it and change the daily loss limit.

#### If it fails

- The editor must not allow editing a preset in place; presets are files, custom sets are copies.

### 7.10 Backtest files, simulation launch, results pages

Depends on: 7.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: yes · Model hint: default

#### Purpose

Run simulations from the app the way you described: choose an existing backtest file, prop rules, and a prop strategy, and read the results the way a trader would.

#### Prerequisites

- Step 7.9 merged.

#### Prompt

```text
Masterplan step 7.10 — Backtest files, simulation launch, results pages.

Implement `GET /v1/prop/backtest-files` (your saved runs, each ready for prop simulation, and your imported trade logs, with their mix of path fidelities, instruments, range, and trade count), `POST /v1/prop/backtest-files/preview` and `POST /v1/prop/backtest-files` (import a trade log with a profile, as a `trade_import` job; files arrive through the upload endpoint from 5.12), `POST /v1/prop/simulations` (a `prop_sim` job: a backtest file, rule sets, a prop strategy, bankroll, horizon, paths, seed, stress options; register the kind with the notify hook from 5.11), and `GET /v1/prop/simulations/{id}` with artifacts served through endpoints (timelines, cash curve percentiles, distributions, failure reasons, ranking). Build the backtest-files list (with an import dialog for trade logs), the launch dialog (pick a backtest file — a run without trade paths shows why it cannot be used — rule sets, a prop strategy, and options; feasibility flags shown before launch), and the results page: account timelines (ECharts, one lane per account showing evaluation, funded, payouts, failure), cash curve with percentile bands, outcome distributions, failure-reason bars, the ranking table across rule sets, and the path-fidelity badge with the replay notes. Add "Simulate prop accounts" on every run page, which opens the launch dialog with that run selected. Phone: charts full width; the ranking table scrolls in its box.

Playwright: launch a small simulation on the seeded run from its run page; import a synthetic trade log and simulate it; read the ranking table.

Not in this step: new simulation features.
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Page numbers equal the SDK's `monte_carlo` output for the same backtest file, inputs, and seed (contract test).
3. A simulation started from the phone sends a notification on completion (the `prop_sim` kind registered with the notify hook from 5.11).

#### Your checks

- Open one of your runs on your phone, tap "Simulate prop accounts", choose the three presets and a prop strategy, run 1,000 paths, and read the ranking and the timelines.

#### If it fails

- Timelines that overlap incorrectly on the phone need per-lane rendering, not a stacked bar.

### 7.11 More presets, end to end

Depends on: 7.10 · Plan mode: skip · Reviews: step-reviewer, engine-accuracy-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

The simulator covers the firms you care about and the whole flow is tested and demoed.

#### Prerequisites

- Step 7.10 merged.

#### Prompt

```text
Masterplan step 7.11 — More presets, end to end.

Using the prop-preset-refresh skill procedure, encode presets for Apex 4.0 (flagged: automation prohibited), Lucid, FundedNext Futures, Take Profit Trader (flagged), Alpha Futures (flagged), and Breakout (crypto), each with sources, examples, and status; verify or mark draft honestly. Add a Playwright end-to-end flow: open a saved run, simulate it under two rule sets and a prop strategy, read results and the ranking; then import a trade log and simulate it. Record a demo video; write docs/demo-prop.md. Update docs/prop-guide.md with the preset list and their statuses.

Not in this step: anything else.
```

#### Done means

1. Nine or more presets exist; each has sources, examples, and an honest status.
2. The end-to-end flow passes in CI on both projects.
3. `docs/demo-prop.md` exists with the video attached.

#### Your checks

- Follow `docs/demo-prop.md` on your phone; then open the Apex preset and confirm it is flagged for automation.

#### If it fails

- If a firm's pages have changed since the research, encode what the page says today and note the change in the preset's sources.

## Phase exit

```text
/phase-exit 7 — Run the exit procedure for Phase 7: clean-clone suite; engine-accuracy-reviewer over the phase diff; /code-review ultra on fefat-prop if the budget allows (otherwise high); mutation testing on fefat-prop with the kill rate recorded; demo = docs/demo-prop.md; retro; backlog groomed; tag phase-7.
```
