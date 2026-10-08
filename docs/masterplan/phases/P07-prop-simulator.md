# Phase 7 — Prop simulator

**Goal.** The prop-firm simulator from `03-prop-simulator.md`: rules as dated, sourced data; an account state machine with a Python reference; exact mode inside the engine; fast replay that must agree with exact mode; the policy layer for your four macro-strategy dimensions; Monte Carlo with a cash ledger; and the pages to run and read it all.

**You get.** "Which plan and policy should I run this strategy under?" answered with pass probabilities, payouts, costs, and a ranking.

**Depends on.** Phase 6 in the written order. Steps 7.1–7.8 need only the engine (Phase 2) and the SDK; 7.9–7.11 need the app (Phase 6). If you move this phase earlier at a kickoff, amend 7.1's `Depends on` line.

**Open decisions for the kickoff.** The first three plans to encode (suggested: Topstep Trading Combine → XFA, My Funded Futures Rapid or Pro, Tradeify Growth or Select); the bankroll and horizon defaults; whether you trade micros or minis in evaluations.

## Kickoff

```text
/phase-kickoff 7 — Read docs/masterplan/phases/P07-prop-simulator.md, docs/masterplan/03-prop-simulator.md, and docs/masterplan/appendix/research-prop-firms.md. Ask me the open decisions. Check the firms' current pages for the three chosen plans and note changes since the research (do not encode yet). Reconcile the steps with the engine's AccountModel trait and the results model; open the kickoff PR.
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

Read docs/masterplan/03-prop-simulator.md §1 and the taxonomy in docs/masterplan/appendix/research-prop-firms.md §1. Define the rule schema as Rust types in `fefat-prop` with serde and schemars (Firm, Plan, Stage, drawdown, daily loss, consistency, session, position, payout, transitions, conduct), generate `python/fefat/prop/rules.schema.json`, and add Pydantic models in `fefat.prop`. Define the preset file format `python/fefat/prop/presets/<firm>/<plan>@<as-of>.yaml`: the rules plus `sources` (URLs with retrieval dates), `status` (draft, verified, stale), and `examples` — worked examples transcribed from the firm's documentation (for instance Topstep 50K: limit 48,000; 48,500 after +500; unchanged after −500), each a small scenario of balance or equity events and expected rule outcomes. Write a loader and a validator (`fefat prop validate-presets`).

Write the `prop-preset-refresh` skill under `.claude/skills/`: for a named preset, re-read every source URL, diff the rules against the current page text, and propose a new `@<today>` preset file with updated sources and examples; never edit an existing version.

Encode one preset in `draft` status (Topstep Trading Combine 50K) as the schema's first test; its examples run in 7.2.

Not in this step: the state machine, the engine.
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

Read docs/masterplan/03-prop-simulator.md §2. Implement the account state machine in Python first (`python/fefat/ref/prop.py`, readable, rule by rule, integer money): states and events as specified; drawdown types with high-water-mark sources and lock levels; daily loss (soft and hard) with anchors and resets; consistency windows and effects; minimum and qualifying days; session rules; position limits and scaling; payout gates, amounts, caps, splits, cadence, and effects on the floor; transitions with side effects; fees and expiry. Then implement the same in Rust in `fefat-prop` and add a differential test over generated event sequences (Hypothesis) plus every preset's worked examples as tests of both implementations.

Encode the three chosen plans as presets with sources, retrieval dates, and examples (at least one breach and one payout example each), and mark them `verified` only when their examples pass. Record in each preset the automation policy and hold-time rules as feasibility flags.

Not in this step: the engine integration (7.3), replay.
```

#### Done means

1. The three presets' examples pass in both implementations; the presets are `verified`.
2. The differential test passes on 10,000 generated event sequences.
3. `docs/prop-schema-coverage.md` lists which rules each preset exercises.

#### Your checks

- In a notebook, feed the Topstep reference machine a hand-made sequence (start 50,000; +600 day; −400 day; payout request) and read the state after each event; compare with your own understanding of the rules.

#### If it fails

- If a firm's example cannot be reproduced, the rule text is ambiguous; record both readings in the preset as `ambiguities`, pick the conservative one, and flag the preset `draft`.

### 7.3 Exact mode: drawdowns, daily loss, flat-by, limits

Depends on: 7.2 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

A strategy runs inside a prop account in the engine: breaches liquidate, daily-loss lockouts stop trading, flat-by times flatten, and contract limits cap size.

#### Prerequisites

- Step 7.2 merged.

#### Prompt

```text
Masterplan step 7.3 — Exact mode: drawdowns, daily loss, flat-by, limits.

Read docs/masterplan/03-prop-simulator.md §3.1 and docs/masterplan/02-engine-and-data.md §4 (AccountModel). Implement `PropAccount` in `fefat-prop` as an `AccountModel`: intrabar marks update intraday-trailing high-water marks and test breaches on equity; session end updates end-of-day high-water marks and daily tallies; firm day anchors handle crypto-style snapshots; daily loss soft breaches flatten, cancel, and lock until the next session; hard breaches fail the account; flat-by times flatten; contract limits and scaling tiers cap orders; the trigger levels are exposed so the hierarchical replay descends when the floor is reachable. Forced liquidations are fills by the fill spec with reason codes. Expose `fefat.prop.run_exact(strategy, rule_set, start, end, ...)` through the bindings, producing the run artifacts plus an `account_events` table.

Tests: scenarios (an intraday trailing breach inside a bar that the bar's close would not show; a soft daily-loss lockout followed by signals that must be ignored; a flat-by liquidation across a daylight-saving change; a scaling tier change effective next session); the reference prop machine fed with the engine's marks agrees with the engine's account events.

Not in this step: payouts and lifecycle in the engine (7.4), replay.
```

#### Done means

1. The scenarios pass; the reference machine agrees with the engine on generated runs.
2. Skip-equals-no-skip still holds with the prop account's trigger levels (property test).
3. `run_exact` on a synthetic year produces `account_events` with breaches and lockouts where planted.

#### Your checks

- In a notebook, run your real strategy under the Topstep preset for one month with `run_exact` and read `account_events`: do the lockouts and any breach happen on the days you would expect from the equity curve?

#### If it fails

- A breach detected at bar close but not intrabar means the account floor was not registered as a trigger level for the descent.

### 7.4 Payouts, consistency, scaling, lifecycle, fees

Depends on: 7.3 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The whole account life is simulated: evaluation, funding, payouts with their gates and caps, consistency effects, resets, expiry, and fees.

#### Prerequisites

- Step 7.3 merged.

#### Prompt

```text
Masterplan step 7.4 — Payouts, consistency, scaling, lifecycle, fees.

Complete the engine-side account model with the lifecycle: evaluation pass conditions (target, minimum days, consistency with raise-target or block-payout effects), transition to funded with side effects, payout requests under a simple default policy (request as soon as eligible), gates (qualifying days, buffers), amount rules, caps by payout number, splits, cadence, effects on the floor, lifetime caps, expiry and resets, and fee events (evaluation, activation, monthly, reset, data) recorded in a cash ledger separate from the simulated balance. Add `account_summary` (stage reached, days, payouts, fees, net cash) to the run artifacts.

Tests: each verified preset's payout examples pass through the engine path; a generated-sequence differential test against the reference machine covers transitions; ledger identity (net cash = payouts − fees).

Not in this step: policies (7.6), replay.
```

#### Done means

1. Preset payout examples pass in exact mode; differential tests pass.
2. `account_summary` for a synthetic profitable strategy shows pass, funding, and payouts with correct caps.
3. The cash ledger reconciles (test).

#### Your checks

- Run `run_exact` for a year of your strategy under one preset and read the summary: did it pass, when, how many payouts, how much net cash after fees?

#### If it fails

- Payout caps by payout number are the usual error source; the preset examples must include a third payout.

### 7.5 Equity-path export and fast replay with equivalence tests

Depends on: 7.4 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Thousands of account lifetimes can be simulated from one base run, and a test proves replay equals exact mode.

#### Prerequisites

- Step 7.4 merged.

#### Prompt

```text
Masterplan step 7.5 — Equity-path export and fast replay with equivalence tests.

Read docs/masterplan/03-prop-simulator.md §3.2. Make the engine export, for base runs with one unit and no account-state dependence, the per-episode equity envelope: running-max increases, each new low since the last peak, and a mark plus reset at every minute boundary, in price points with contract sides separate, plus a per-episode summary (final, MAE, MFE, maximum drawdown from peak). Tag runs `replayable` when the conditions hold. Implement fast replay in `fefat-prop`: given envelopes, a rule set, a size multiplier per episode, a start date, and (later) a policy, run the account state machine over the envelope events with firm commissions and the mini/micro choice applied at replay. Expose `fefat.prop.replay(run, rule_set, ...)`.

Tests: replay equals exact mode on generated strategies and rule sets (10,000 cases, identical account events and summaries); the `replayable` flag is false when a strategy reads account state (a stub standing in for the event strategies of Phase 9) and replay refuses; replay of a 5-year run completes in milliseconds (timed).

Not in this step: policies, Monte Carlo.
```

#### Done means

1. The replay-equals-exact test passes; the PR reports the case count and seeds.
2. Replay refuses non-replayable runs with a clear message.
3. Replay speed is reported (thousands of account-years per second expected).

#### Your checks

- In a notebook, replay your real base run under the three presets and compare with `run_exact` for one of them: identical `account_summary`.

#### If it fails

- Any difference between replay and exact mode is a bug in the envelope (a missing new-low record or minute mark), never acceptable; ask for the smallest failing episode.

### 7.6 Policy layer and cash ledger

Depends on: 7.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Your macro-strategy as data: accounts over time, sizing per stage, payouts and reinvestment, allocation — simulated over the shared trade stream with real-money accounting.

#### Prerequisites

- Step 7.5 merged.

#### Prompt

```text
Masterplan step 7.6 — Policy layer and cash ledger.

Read docs/masterplan/03-prop-simulator.md §4. Define `PolicySpec` as Rust types with schemars (and Pydantic models): accounts over time (plans to buy, maximum evaluation and funded accounts, start schedule and stagger, actions on fail, pass, and expiry, conditioned on bankroll); sizing per stage (fixed, risk-based, cushion ladder; firm limits enforced); payouts (when to request, minimum amount, buffer kept, share recycled into evaluations); allocation (copy all, rotate, by session, by firm, staggered start; optional per-account noise). Implement the multi-account simulation in `fefat-prop`: all accounts consume the same episode stream (so correlation is structural), each account runs the state machine from replay, the policy makes its decisions at the defined moments, and the bankroll ledger records fees, resets, activations, and payouts after split. Expose `fefat.prop.simulate(run, rule_sets, policy, bankroll, horizon)` with a `PolicyResult` (timelines per account, cash curve, summary).

Tests: a one-account policy equals plain replay; copy-all with two accounts fails both on the same day as the single account; staggered starts shift failures accordingly; ledger identity holds; firm account caps are respected.

Not in this step: Monte Carlo (7.7), pages.
```

#### Done means

1. The policy tests pass; `PolicyResult` timelines are correct on hand-built cases.
2. The schema and Pydantic models round-trip; three policy presets exist (one conservative evaluation; two staggered evaluations; a five-account copier).
3. A 10-account, 5-year simulation runs in under a second in replay (timed).

#### Your checks

- In a notebook, simulate your strategy under "two staggered evaluations at Topstep, conservative sizing when funded" and read the cash curve and the account timelines.

#### If it fails

- If two copied accounts fail on different days, the allocation is not sharing the stream; that is a correctness bug.

### 7.7 Monte Carlo

Depends on: 7.6 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Distributions, not single paths: every start date, bootstrapped days, stress, and the report metrics from the design.

#### Prerequisites

- Step 7.6 merged.

#### Prompt

```text
Masterplan step 7.7 — Monte Carlo.

Read docs/masterplan/03-prop-simulator.md §5. Implement in `fefat-prop`: rolling start dates over the base run's history; a stationary bootstrap of whole session-days shared by all accounts in a path (mean block length by the Politis–White rule, documented); stress options (ticks haircut on every fill, random trade skipping, cost multiplier); seeded, parallel over paths with Rayon. Report: pass probability and time to pass; probability and time of first payout; net cash at the horizon (mean, median, 5/25/75/95 percentiles); probability of net loss; maximum bankroll drawdown; cost per funded account; failure reasons; effective sample size; and the feasibility flags from the preset. Expose `fefat.prop.monte_carlo(...)` returning frames plus a text report; add plan ranking across rule sets by median net cash and by probability of net loss.

Tests: with zero randomness the Monte Carlo equals the rolling-start-date set; bootstrap paths preserve day-level dependence (a planted autocorrelation survives); reports reproduce with the same seed.

Not in this step: pages.
```

#### Done means

1. Determinism and bootstrap tests pass; the report fields match the design list.
2. 1,000 paths × 10 accounts × 5 years completes in well under a minute on this PC (timed in the PR).
3. The plan ranking is produced for the three presets on synthetic data.

#### Your checks

- In a notebook, run 1,000 paths of your strategy under the three presets and read the ranking and the 5th-percentile net cash: that is the number that tells you whether this is worth your money.

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

Review the `fefat.prop` API for consistency (`rule_sets.load`, `policies.load`, `run_exact`, `replay`, `simulate`, `monte_carlo`, `rank_plans`), add docstrings with examples, and write `notebooks/07-prop-simulator.ipynb`: load a base run, replay under the three presets, simulate a policy, run Monte Carlo, rank plans, show feasibility flags, and compare with exact mode for one preset. Write `docs/prop-guide.md` explaining the rule schema in plain words, how to add a preset, what the report fields mean, and the limits of replay.

Not in this step: pages.
```

#### Done means

1. The notebook runs on your data.
2. `docs/prop-guide.md` explains every report field in one sentence each.
3. Every public function has a docstring with an example.

#### Your checks

- Run the notebook end to end; read the guide's explanation of "probability of net loss" and confirm it matches your understanding.

#### If it fails

- Long Monte Carlo times in the notebook: reduce paths for the demo and state the production default.

### 7.9 Rule and policy pages

Depends on: 7.8, 6.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Rule sets and policies are managed in the app with versions, status, and sources visible.

#### Prerequisites

- Steps 7.8 and 6.9 merged.

#### Prompt

```text
Masterplan step 7.9 — Rule and policy pages.

Implement the prop endpoints from docs/masterplan/01-architecture.md §7 (rule sets and versions, policies and versions) and build the Prop section: a rule-set library (presets with status badge, as-of date, firm, plan, sources; custom rule sets created from a preset as a starting point) with a schema-driven editor for custom sets (grouped by stage, with help text) and version history; a policy library with the schema-driven form for the four dimensions and the three presets from 7.6. Phone: forms stack; sources open in the browser.

Playwright: open a preset, duplicate it as custom, change the daily loss, save version 1; create a policy from a preset.

Not in this step: simulations (7.10).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Preset files and database rule sets share one schema; a custom set validates like a preset.
3. Sources and the automation flag are visible on the rule-set page.

#### Your checks

- On your phone, open the Topstep preset and read its sources and status; duplicate it and change the daily loss limit.

#### If it fails

- The editor must not allow editing a preset in place; presets are files, custom sets are copies.

### 7.10 Simulation launch and results pages

Depends on: 7.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Run simulations from the app and read the results the way a trader would: timelines, cash curves with bands, distributions, failure reasons, and the plan ranking.

#### Prerequisites

- Step 7.9 merged.

#### Prompt

```text
Masterplan step 7.10 — Simulation launch and results pages.

Implement `POST /v1/prop/simulations` (a `prop_sim` job: source runs or a strategy version for exact mode, rule sets, policy, bankroll, horizon, paths, seed, stress options; register the kind with the notify hook from 5.11) and `GET /v1/prop/simulations/{id}` with artifacts served through endpoints (timelines, cash curve percentiles, distributions, failure reasons, ranking). Build the launch dialog (with the feasibility flags shown before launch) and the results page: account timelines (ECharts, one lane per account showing evaluation, funded, payouts, failure), cash curve with percentile bands, outcome distributions, failure-reason bars, the ranking table across rule sets, and the exact-versus-replay badge. Phone: charts full width; the ranking table scrolls in its box.

Playwright: launch a small simulation on the seeded run, wait, read the ranking table.

Not in this step: new simulation features.
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Page numbers equal the SDK's `monte_carlo` output for the same inputs and seed (contract test).
3. A simulation started from the phone sends a notification on completion (the `prop_sim` kind registered with the notify hook from 5.11).

#### Your checks

- Launch 1,000 paths for your strategy under the three presets from your phone; read the ranking and the timelines.

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

Using the prop-preset-refresh skill procedure, encode presets for Apex 4.0 (flagged: automation prohibited), Lucid, FundedNext Futures, Take Profit Trader (flagged), Alpha Futures (flagged), and Breakout (crypto), each with sources, examples, and status; verify or mark draft honestly. Add a Playwright end-to-end flow: pick a run, two rule sets, a policy, launch, read results, open the ranking. Record a demo video; write docs/demo-prop.md. Update docs/prop-guide.md with the preset list and their statuses.

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
