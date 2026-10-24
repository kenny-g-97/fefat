# Phase 9 — Event strategies

**Goal.** The second strategy kind: Python classes with an `on_bar` callback and an order API for path-dependent logic, running on the same Rust execution core with the same fills, proven equal to signal strategies where both can express a strategy, sandboxed, editable in the app, and supported by the agent.

**You get.** Strategies that scale in, react to fills, and keep state — written in Python, as fast as the design allows, with the same trust as signal strategies.

**Depends on.** Phase 8 (the agent exists; this phase adds its support) and Phase 2.

**Open decisions for the kickoff.** The first event strategy you want to port (something path-dependent you already trade); whether scale-in and multi-instrument coordination are needed in the first cut.

## Kickoff

```text
/phase-kickoff 9 — Read docs/masterplan/phases/P09-event-strategies.md and docs/masterplan/02-engine-and-data.md §2.2. Ask me the open decisions. Reconcile with the engine's ExitPlan, bindings, and executor; open the kickoff PR.
```

## Steps

### 9.1 The `on_bar` bridge

Depends on: 8.11 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Python strategy code is called once per bar close with zero-copy access to features and bars, never inside a bar.

#### Prerequisites

- Phase 9 kickoff done.

#### Prompt

```text
Masterplan step 9.1 — The on_bar bridge.

Read docs/masterplan/02-engine-and-data.md §2.2. Implement the event-strategy path: `fefat.strategy.EventStrategy` base class with `on_start(ctx)`, `on_bar(ctx)`, `on_fill(ctx, fill)`, `on_session_end(ctx)`; a Rust-backed `ctx` exposing the current bar, `ctx.f.<feature>` current values and `ctx.f.<feature>[-k]` history (future rows cannot be indexed), position and open orders, the clock, and the calendar; features precomputed in Python and handed over once as Arrow. The engine calls into Python at bar close through PyO3 with the GIL held only during the callback; a `wake` column (optional) skips callbacks on bars with no setup and no live position. Orders and exit plans declared in `on_bar` are executed by the Rust `ExitPlan` intrabar.

Tests: a trivial event strategy that mirrors a signal-strategy template yields identical trades (parity test); future indexing raises; callback count equals bar count without `wake` and fewer with it.

Not in this step: the full order API (9.2), reference engine support (9.3).
```

#### Done means

1. The parity test passes on synthetic data.
2. Future-row access raises a clear error (test).
3. A 5-year event strategy with a `wake` column runs within the design target (reported).

#### Your checks

- In a notebook, port your simplest strategy to `EventStrategy` and run it: the trade list equals the signal-strategy version's.

#### If it fails

- If Python exceptions inside `on_bar` crash the engine, the bridge must convert them into a run failure with the traceback in the log.

### 9.2 Order API and parity tests

Depends on: 9.1 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Everything the execution template can do, the order API can do too, plus scaling in and reacting to fills.

#### Prerequisites

- Step 9.1 merged.

#### Prompt

```text
Masterplan step 9.2 — Order API and parity tests.

Implement the order API on `ctx`: `buy`, `sell`, `close`, `cancel`, `replace`, market/limit/stop-market with time-in-force, brackets built from the same `ExitPlan` types (stop, targets, breakeven, trailing, time exits), scaling in (adds to a position with per-leg exits), and `ctx.state` for user state (persisted in the run log for `explain`). Document the API in docs/engine-guide.md. Extend parity: for every execution-template feature, an event-strategy rewrite produces identical trades (generated templates, Hypothesis). Event-strategy runs store trade paths and fills like any run, so they can be prop-simulated: add a test that a scale-in run replays in the prop simulator to the same account events as the reference machine fed with its full-resolution path.

Not in this step: reference engine support.
```

#### Done means

1. Parity tests pass across generated templates.
2. A scale-in strategy with per-leg targets produces the expected fills on a scenario.
3. The API documentation lists every method with an example.

#### Your checks

- Write a two-leg scale-in in a notebook and read the fills: two entries, two exits with the right reasons.

#### If it fails

- Order replacement semantics (modify versus cancel-and-new) must follow the fill spec's activation rule; replacing re-activates after latency.

### 9.3 Reference engine support

Depends on: 9.2 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Event strategies have the same oracle as signal strategies: the readable reference engine.

#### Prerequisites

- Step 9.2 merged.

#### Prompt

```text
Masterplan step 9.3 — Reference engine support.

Read docs/spec/fill-semantics.md (event order and activation) and the order API documented in docs/engine-guide.md after 9.2. Extend `python/fefat/src/fefat/reference/engine.py` to run `EventStrategy` classes with the same callback and order API (pure Python, slow, readable; the reference stays the specification, so no shortcuts for speed), and extend the differential test to event strategies on generated tapes and generated strategies (random order placement, replacement, and cancellation at bar closes; scale-in legs with their own exits). Make `Run.explain(trade_id)` work for event-strategy runs, including the user state at each callback, and add a scenario file for the callback ordering rules so they are documented like fills.

Not in this step: UI, performance work.
```

#### Done means

1. The differential test passes for event strategies on 10,000 generated cases.
2. `Run.explain` shows user state alongside events for an event-strategy trade.

#### Your checks

- Explain one trade of your ported strategy; the printed state shows the variables you track.

#### If it fails

- If the reference engine and Rust disagree only on event strategies, the difference is usually callback ordering at equal timestamps; the spec's event order applies to callbacks too.

### 9.4 Sandboxed execution and process-pool sweeps

Depends on: 9.3 · Plan mode: optional · Reviews: step-reviewer, code-review · Security: yes · Model hint: default

#### Purpose

Event strategies run through the executor like everything else, and sweeps of them use processes since they hold the GIL.

#### Prerequisites

- Step 9.3 merged.

#### Prompt

```text
Masterplan step 9.4 — Sandboxed execution and process-pool sweeps.

Make the backtest job accept `kind: event` strategies: the executor loads the class in the subprocess, the engine runs with callbacks there, artifacts are written the same way. Add a process-pool `run_batch` for event strategies (one process per trial, shared cache mapped in each) with the same interface as the Rust batch, and make the Phase 11 study orchestrator (when it arrives) agnostic to the kind. Limits apply per trial.

Tests: an event-strategy run through the API equals the notebook run; a batch of 32 trials uses multiple processes; a strategy that loops forever is killed at the timeout.

Not in this step: UI.
```

#### Done means

1. API and batch tests pass.
2. A 32-trial event-strategy batch shows near-linear speedup on 16 cores (reported).
3. Timeouts and memory limits apply per trial.

#### Your checks

- Run your event strategy from the app's run dialog; it completes and the results page works unchanged.

#### If it fails

- Windows process spawning with large arguments is slow; pass the spec through a file, not the command line.

### 9.5 Code editor page for event strategies

Depends on: 9.4, 6.9 · Plan mode: optional · Reviews: step-reviewer, ui-verifier · Security: no · Model hint: default

#### Purpose

Event strategies are written in the app: an editor with validation, lint, and versioning.

#### Prerequisites

- Steps 9.4 and 6.9 merged.

#### Prompt

```text
Masterplan step 9.5 — Code editor page for event strategies.

Extend the strategy page's editor from 5.5 to `kind: event` strategies: validation now imports the class, instantiates it, and runs one bar on synthetic data in the executor (`POST /v1/strategies/validate` gains the event path), lint covers the callback API (future indexing, state mutation in `on_fill`), a template picker offers two event-strategy templates (a scale-in and a fill-reactive example), and the run dialog is unchanged.

Playwright: open an event template, introduce an error, validate, see the line, fix, save version 2, run.

Not in this step: agent support (9.6).
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. Validation runs in the executor only (test).
3. Templates run on synthetic data and produce trades (test).

#### Your checks

- Edit an event template on desktop, validate, save, run.

#### If it fails

- Validation must time out quickly (a few seconds); a strategy that hangs on one bar must not hang the page.

### 9.6 Agent support and performance tests

Depends on: 9.5 · Plan mode: skip · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

The agent writes and edits event strategies through proposals, and the event path has a performance baseline.

#### Prerequisites

- Step 9.5 merged.

#### Prompt

```text
Masterplan step 9.6 — Agent support and performance tests.

Read docs/masterplan/04-agent.md §4 and the skills written in 8.8 for the house style. Add a `fefat-event-strategies` skill (the EventStrategy and order API, state, patterns such as scale-in and fill-reactive exits, pitfalls such as reading future rows or mutating state in `on_fill`, how to propose a change) and make `propose_change` validate event strategies in the executor with the same import-and-run-one-bar check as the editor. Add event-strategy tasks to the eval suite (write one, convert one, fix a planted bug in one). Add criterion-style benchmarks for the callback path (Python callback cost per bar, with and without `wake`, with 1, 5, and 20 features) and record baselines in docs/validation/benchmarks.md with a CI regression gate as for Phase 2.

Not in this step: new engine features, optimisation beyond the obvious.
```

#### Done means

1. The agent can turn a signal strategy into an event strategy through a proposal (replayed fixture).
2. Benchmarks and the gate are in place with recorded numbers.
3. The eval suite includes event-strategy tasks with recorded pass rates.

#### Your checks

- Ask the agent to "rewrite strategy X as an event strategy that adds a second unit after the first target"; review the proposal; accept; run.

#### If it fails

- Callback cost far above the target means the `ctx` is allocating per bar; the bridge must reuse buffers.

## Phase exit

```text
/phase-exit 9 — Run the exit procedure for Phase 9: clean-clone suite; engine-accuracy-reviewer over the phase diff; /security-review (code execution); demo = port one real strategy and show parity; retro; backlog groomed; tag phase-9.
```
