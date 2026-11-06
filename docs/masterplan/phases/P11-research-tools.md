# Phase 11 — Research tools

**Goal.** Studies on top of the engine: batch runs on all 16 cores, parameter optimization with heatmaps, overfitting safeguards (trial ledger, holdout, deflated Sharpe, PBO), walk-forward with a stitched out-of-sample curve, Monte Carlo robustness, and agent tools for all of it.

**You get.** Honest answers to "which parameters, and should I believe them?"

**Depends on.** Phase 10 in the written order. If you move this phase earlier at a kickoff: 11.1–11.4 need only Phase 5; 11.5 needs the prop simulator (P7); 11.7 needs the agent (P8); event-strategy sweeps in 11.1 need P9 — amend the `Depends on` lines accordingly.

**Skills.** `backtest-expert` for every step — this phase is the skill's methodology made into tools (plateaus over peaks, walk-forward, stress, trial counting); `frontend-design` and `unslop` with `web/DESIGN.md` for the pages.

**Open decisions for the kickoff.** The locked holdout period (the latest 12 months is natural and matches the tick-fidelity year); the default study budget (time) before confirmation; which strategy to use as the running example.

## Kickoff

```text
/phase-kickoff 11 — Read docs/masterplan/phases/P11-research-tools.md, docs/masterplan/02-engine-and-data.md §9 (research tools), and docs/masterplan/01-architecture.md §6 (sweeps). Ask me the open decisions. Load the `backtest-expert` skill and pull in the D-29 backlog items that target this phase (the stress profile in 11.6, the regime breakdown in 11.4). Reconcile with run_batch, the jobs runner, and the prop Monte Carlo (shared bootstrap code); open the kickoff PR.
```

## Steps

### 11.1 Batch runs and sweep artifacts

Depends on: 10.7 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Many runs at once, cheaply, producing the matrix that every later analysis reads.

#### Prerequisites

- Phase 11 kickoff done.

#### Prompt

```text
Masterplan step 11.1 — Batch runs and sweep artifacts.

Read docs/masterplan/02-engine-and-data.md §9 (research tools) and docs/masterplan/01-architecture.md §6 (sweeps). Implement `fefat.research.sweep(strategy, param_grid | sampler, start, end, config)`: parameters are classed as feature (recomputed and cached), signal threshold (cheap: signal frame recomputed from cached features), or execution (free: the same signal frame); trials are planned to share work; signal strategies run through `run_batch` on Rayon over the shared cache; event strategies through the process pool. The sweep artifact is a trials table (params, metrics, run hash, artifact pointer for top-K only) and a daily P&L matrix (trial × day) in Parquet. Progress is reported per chunk; the sweep is resumable (completed trial hashes skipped).

Tests: a 100-trial sweep on synthetic data equals 100 individual runs; resume after an interruption; the matrix dimensions and the metrics agree.

Not in this step: optimizers, pages.
```

#### Done means

1. Equality, resume, and matrix tests pass.
2. 1,000 execution-parameter trials on a synthetic year complete within the design target on this PC (reported).
3. The artifact schema is documented in docs/engine-guide.md.

#### Your checks

- In a notebook, sweep stop and target over 10 × 10 values for your strategy on one year and look at the trials table sorted by expectancy.

#### If it fails

- If feature-parameter trials recompute features repeatedly, the planner is not grouping by feature parameters; fix the planner.

### 11.2 Studies with time and CPU caps

Depends on: 11.1 · Plan mode: required · Reviews: step-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

Sweeps are jobs in the app with an estimate first, a cap, live progress, cancellation that keeps partial results, and a trials page.

#### Prerequisites

- Step 11.1 merged.

#### Prompt

```text
Masterplan step 11.2 — Studies with time and CPU caps.

Implement `studies` (kind sweep for now): `POST /v1/studies` with a spec (strategy version, parameter space, range, config), `POST /v1/studies/{id}/estimate` (a calibration trial, then an estimate of trials, wall time, and CPU time), caps (max trials, max wall minutes) enforced by the orchestrator job which dispatches chunks of trials to the process pool (signal strategies: one `run_batch` call per chunk), `GET /v1/studies/{id}/trials` (sortable, filterable), `POST /v1/studies/{id}/cancel` keeping completed trials. Build the Studies section: launch dialog (parameter space editor from the parameter schema: lists, ranges, steps; estimate shown before launch), study page with live progress and the trials table, and "save as run" for top trials (full artifacts, trade paths included, materialised on demand, so the trial can also be prop-simulated).

Playwright: launch a 50-trial study on synthetic data with a cap, watch progress, cancel at 50%, see 25 trials kept.

Not in this step: optimizers, heatmaps.
```

#### Done means

1. Playwright passes on both projects.
2. The estimate is within 2x of the actual time for the synthetic study (test with tolerance).
3. Cancellation keeps completed trials (test).

#### Your checks

- Launch a 200-trial study with a 5-minute cap; watch the estimate, then the progress; open the best trial's run.

#### If it fails

- Chunk sizes must balance: too small wastes process start-up, too large delays progress; 20–50 trials per chunk is the starting point.

### 11.3 Optimization and heatmaps

Depends on: 11.2 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Grid, random, and Bayesian search with visualisations that show plateaus, not just the best point.

#### Prerequisites

- Step 11.2 merged.

#### Prompt

```text
Masterplan step 11.3 — Optimization and heatmaps.

Add samplers to studies: grid, random (seeded), and Bayesian through Optuna's ask-and-tell interface in batches (the orchestrator asks for a batch, runs it, tells results), with an objective chosen from the metrics (expectancy in R, profit factor, Sharpe, custom expression) and constraints (minimum trades, maximum drawdown). Build the study results views: a 2-D heatmap of the objective over any two parameters (ECharts), parallel coordinates for more, the objective's distribution, and a "plateau" view that highlights neighbourhoods where the objective is stable (the SDK computes neighbourhood means and stds). Document "pick the plateau, not the peak" in the page's reading guide.

Playwright: run a small Bayesian study on synthetic data, see the heatmap.

Not in this step: overfitting statistics (11.4).
```

#### Done means

1. The three samplers run through the orchestrator (tests); Bayesian improves over random on a synthetic objective (statistical test with tolerance).
2. Playwright passes on both projects with screenshots.
3. The plateau computation is tested on a planted landscape.

#### Your checks

- Run a Bayesian study for your strategy; look at the heatmap: is the best point on a plateau or a spike?

#### If it fails

- Optuna must be driven by the orchestrator, not inside worker processes; the study object lives in one place.

### 11.4 Overfitting safeguards

Depends on: 11.3 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

The app keeps count of what you tried and shows you the statistics that deflate optimistic results.

#### Prerequisites

- Step 11.3 merged; the holdout decision.

#### Prompt

```text
Masterplan step 11.4 — Overfitting safeguards.

Implement the trial ledger (every run and every study trial counted per strategy lineage, persisted), the deflated Sharpe ratio using the lineage's trial count, PBO (probability of backtest overfitting) computed from the sweep's daily P&L matrix with combinatorially symmetric cross-validation, and a locked holdout: a date range per workspace that no run touches by default; unlocking it is explicit, logged, and shown as a banner on every result computed over it. Show deflated Sharpe, PBO, and the trial count on study pages and run pages; add a reading guide.

Tests: deflated Sharpe decreases as the trial count grows; PBO is high on a planted noise sweep and low on a planted real-edge sweep; the holdout blocks runs by default and logs unlocks.

Not in this step: walk-forward.
```

#### Done means

1. The statistical tests pass on planted cases.
2. The holdout lock works in the SDK and the app, with the banner.
3. Study pages show the three safeguards with the guide.

#### Your checks

- Set the holdout to your latest 12 months, try to run a backtest over it from the app: it refuses until you unlock, and the unlock is logged.

#### If it fails

- PBO implementation errors are common; the test with planted noise versus planted edge is the guard — do not weaken it.

### 11.5 Walk-forward

Depends on: 11.4 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

Optimise in a window, test in the next, stitch the out-of-sample results into one honest curve, and feed it to the prop simulator.

#### Prerequisites

- Step 11.4 merged.

#### Prompt

```text
Masterplan step 11.5 — Walk-forward.

Implement walk-forward studies: anchored or rolling in-sample windows with out-of-sample windows, an optimizer per window (reusing 11.3), selection by objective with plateau preference, a stitched out-of-sample run (trades and daily P&L concatenated with the chosen parameters per window) saved as a run with `origin: walk_forward`, and an efficiency ratio (out-of-sample versus in-sample performance). For signal strategies flat at each session end with unit sizing, choose each window's parameters from the sweep's daily P&L matrix without re-running; otherwise re-run per window. Either way, backtest each out-of-sample window once with its chosen parameters as a saved run (sweep trials carry no trade paths), so the stitched run has full trades, fills, and trade paths. Build the walk-forward page: windows table, parameters per window, the stitched equity curve against the in-sample curves, and a "use for prop simulation" action that opens the prop simulator with the stitched run as its backtest file (it carries the window runs' trade paths, so the prop simulator re-runs nothing).

Tests: the matrix shortcut equals re-running on synthetic data; the stitched run's trades equal the concatenation of window runs; the prop simulator accepts the stitched run.

Not in this step: Monte Carlo robustness.
```

#### Done means

1. Equality and stitching tests pass.
2. Playwright passes on both projects with screenshots.
3. A stitched run opens in the prop simulator launch dialog as the default backtest file, with its trade paths and path fidelity.

#### Your checks

- Run a rolling walk-forward (12 months in, 3 out) for your strategy and read the efficiency ratio; then run the prop Monte Carlo on the stitched run.

#### If it fails

- Windows that overlap the holdout must be excluded automatically; the holdout banner should never appear by accident.

### 11.6 Monte Carlo robustness

Depends on: 11.5 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Distributions for a strategy's drawdown and return under resampling and stress, sharing code with the prop Monte Carlo.

#### Prerequisites

- Step 11.5 merged.

#### Prompt

```text
Masterplan step 11.6 — Monte Carlo robustness.

Implement strategy robustness studies reusing the prop bootstrap code: day-block bootstrap of the daily P&L (and of trades for trade-level metrics), random trade skipping, cost multipliers, slippage ticks, parameter-neighbourhood reruns (small perturbations around the chosen parameters), and a report: distributions of maximum drawdown, net P&L, and Sharpe with percentiles, the probability of a drawdown worse than a threshold, and sensitivity bars for each stress. Build the robustness page with the distributions and the sensitivity view.

Tests: reproducibility by seed; the bootstrap preserves a planted autocorrelation; a planted fragile strategy shows high sensitivity to slippage.

Not in this step: agent tools.
```

#### Done means

1. Tests pass; the report fields are documented.
2. Playwright passes on both projects with screenshots.

#### Your checks

- Run robustness on your strategy: what is the 95th-percentile drawdown, and how much does one extra tick of slippage cost per year?

#### If it fails

- Shared bootstrap code must live in one module used by both Phase 7 and this step; duplicated implementations drift.

### 11.7 Agent tools for studies

Depends on: 11.6 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

The agent can plan, launch (with your confirmation), and read studies, and knows the hygiene rules.

#### Prerequisites

- Step 11.6 merged.

#### Prompt

```text
Masterplan step 11.7 — Agent tools for studies.

Read docs/masterplan/04-agent.md §3 and the tool registry conventions from 8.3. Replace the `run_study` stub with real tools: `plan_study` (returns the estimate from 11.2), `run_study` (consent: confirm cost; parameters validated against the strategy's schema), `get_study_summary` (objective, best plateau, deflated Sharpe, PBO, trial count), `query_study_trials` (DuckDB over the trials table, SELECT only, row cap), `run_walk_forward`, `run_robustness`; outputs are compact tables with study ids. Complete the `optimization-hygiene` skill (trial counts, the holdout, plateau selection over peaks, walk-forward before prop, what deflated Sharpe and PBO mean, when to stop optimising). Add eval tasks: the agent must refuse to unlock the holdout on request, must report the trial count and the deflated Sharpe with any optimised result, and must recommend a plateau when the heatmap has one.

Not in this step: new study kinds, changes to the safeguards.
```

#### Done means

1. Replayed fixtures show the agent planning, confirming, and summarising a study.
2. The eval suite includes the holdout-refusal task and it passes.

#### Your checks

- Ask the agent to "optimise the stop and target and tell me if I should trust it": it runs a study after confirmation and reports deflated Sharpe, PBO, and the trial count.

#### If it fails

- The holdout unlock must not be reachable through any tool; it is a settings action by you only.

### 11.8 End to end

Depends on: 11.7 · Plan mode: skip · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

The research workflow is coherent and demoed: sweep, safeguards, walk-forward, robustness, prop.

#### Prerequisites

- Step 11.7 merged.

#### Prompt

```text
Masterplan step 11.8 — End to end.

Read the demo documents from earlier phases (docs/demo-mvp.md and docs/demo-prop.md) for the format. Write one Playwright flow on synthetic data: launch a sweep with a cap, read the heatmap and the three safeguards, run a rolling walk-forward, open the stitched run, run robustness, send the stitched run to the prop simulator and see it preselected in the launch dialog. Run the ui-verifier over the Studies pages at both sizes and fix findings. Record a demo video; write docs/demo-research.md with the click path and the questions each page answers; update docs/engine-guide.md with a "Research" section that explains, in your words, how to go from a sweep to a prop simulation honestly.

Not in this step: new features, new metrics.
```

#### Done means

1. The flow passes on both projects in CI.
2. The ui-verifier report shows no remaining issues.
3. `docs/demo-research.md` exists with the video attached.

#### Your checks

- Follow `docs/demo-research.md` with your strategy.

#### If it fails

- Report the step of the flow that broke; the fix belongs to that step's component.

## Phase exit

```text
/phase-exit 11 — Run the exit procedure for Phase 11: clean-clone suite; leakage-auditor over the phase diff; /code-review high; demo = docs/demo-research.md; retro; backlog groomed; tag phase-11.
```
