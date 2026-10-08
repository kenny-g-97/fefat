# Phase 2 — Engine

**Goal.** A backtest engine you can trust: its fill rules are written in plain language and in scenario tables you can check by hand, a slow Python reference engine implements them readably, and the fast Rust engine must match the reference exactly on thousands of generated cases. By the end you run tick-accurate backtests from a notebook in seconds.

**You get.** `ff.backtest(strategy, start, end)` with artifacts, metrics, and `run.explain(trade_id)`; a first notebook backtest at step 2.2 (slow, reference engine) and fast ones from step 2.10.

**Depends on.** Phase 1.

**Open decisions for the kickoff.** The fill defaults you sign off in 2.1 (limit fills need trade-through or touch; stop slippage in ticks; latency); the reference capital used for percentage metrics; which real month and product to use for the NautilusTrader comparison; whether you have real fill exports from a broker or prop platform (used in 2.12 and Phase 13).

## Kickoff

```text
/phase-kickoff 2 — Read docs/masterplan/phases/P02-engine.md and docs/masterplan/02-engine-and-data.md §2–§5 and §8. Ask me the open decisions above. Check the data layer from Phase 1 against what these steps assume (store API, calendar, continuous bars, fidelity coverage per day) and amend the steps if needed. Open the kickoff PR.
```

## Steps

### 2.1 Fill specification and scenario format

Depends on: 1.9 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The rules that decide every fill are written down before any engine code exists, in words you can read and in tables you can check with a calculator. You sign them off.

#### Prerequisites

- Phase 1 complete.

#### Prompt

```text
Masterplan step 2.1 — Fill specification and scenario format.

Read docs/masterplan/02-engine-and-data.md §3 and §4 (event order, activation latency) and the CME stop-trigger rule it cites. Write `docs/spec/fill-semantics.md`: a plain-language, normative specification of how market, limit, and stop-market orders are activated and filled on each data fidelity (TBBO, trades only, 1-second bars, 1-minute bars), with the conservative defaults, gap handling, same-interval stop/target ambiguity (resolve to the stop, flag ambiguous), latency, slippage classes, commissions and fees for futures and crypto (maker/taker, funding), and the fidelity tag on every fill. Every rule gets an identifier (F-MKT-01 …). Where the design doc is silent, propose a rule and mark it "proposed" for my sign-off.

Define the scenario-table format in `fixtures/scenarios/README.md` and a YAML schema: a tape (ticks or bars with timestamps), instrument parameters, orders placed at given times, and the expected fills with the rule identifiers they exercise. Scenario ids are stable (`S-fill-001` …) and later steps refer to them. Write the first 30 scenarios covering each order type on each fidelity, including `S-fill-012`: a gap through a stop (stop 4995.00, next trade 4990.25, expected fill 4990.25), a limit touched but not traded through, and a stop and target inside one bar. Expected values must be hand-computable; show the arithmetic in a comment.

Not in this step: any engine code.
```

#### Done means

1. `docs/spec/fill-semantics.md` covers every order type × fidelity cell with a rule identifier, and lists the proposed defaults in a sign-off table.
2. Thirty scenarios validate against the YAML schema (a small loader test), each citing the rules it exercises; together they cite every rule at least once.
3. You have signed off the defaults (a comment on the PR, recorded in the spec's sign-off table with the date).

#### Your checks

- Read the sign-off table and three scenarios of your choice; recompute one expected fill by hand (for example the gap-through-stop case) and confirm the number.

#### If it fails

- If a scenario's expected value looks wrong to you, say which rule you believe applies; the spec changes, then the scenario — never the other way round.

### 2.2 Python reference engine and the first notebook backtest

Depends on: 2.1 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

A slow, readable implementation of the specification that you (and the tests) can treat as the truth. It also gives you your first real backtest, from a notebook, before any Rust exists.

#### Prerequisites

- Step 2.1 merged and signed off.

#### Prompt

```text
Masterplan step 2.2 — Python reference engine and the first notebook backtest.

Read docs/spec/fill-semantics.md and the scenarios. Implement `python/fefat/ref/engine.py`: a pure-Python, deliberately simple event-driven engine over ticks or bars that implements every rule by its identifier (each rule is a small function or a clearly commented block naming the rule id), with market, stop-market, and limit orders, a bracket (stop + target, OCO), one position per strategy, integer prices and money, and an event log that records every decision. Clarity beats speed: no vectorisation, no cleverness.

Add a scenario runner that executes every YAML scenario through the reference engine and compares fills exactly. Add a minimal strategy protocol for the reference engine: a Python callable `on_bar(bar, ctx)` that may submit a market order with a bracket.

Then `notebooks/02-first-backtest.ipynb`: load one month of ES 5-minute bars and ticks via ff.data, run a trivial strategy (for example: buy when the 5-minute close crosses above the 20-bar mean, stop 12 ticks, target 24 ticks, flat by 15:05 Chicago time) through the reference engine on tick fills, and print the trade list and total P&L. It will be slow (minutes are fine); say so in the notebook.

Not in this step: Rust, the full execution template, metrics beyond totals.
```

#### Done means

1. All 30 scenarios pass through the reference engine; the runner prints the rule coverage.
2. `python/fefat/ref/engine.py` is under 600 lines, every rule id from the spec appears in it, and a reviewer unfamiliar with the code can follow one fill from tape to log.
3. The notebook runs on your data and prints a trade list with entry and exit times, prices, and reasons.

#### Your checks

- Run the notebook. Pick one trade, open the same day in your charting platform, and confirm the entry bar and the stop or target level make sense.

#### If it fails

- If the notebook takes more than ten minutes for a month, reduce to two weeks; speed is the Rust engine's job.

### 2.3 Strategy spec and signal-frame contract

Depends on: 2.2 · Plan mode: required · Reviews: step-reviewer · Security: no · Model hint: hard

#### Purpose

The declarative language of signal strategies is fixed: what the builder emits, what the SDK writes, what the engine reads.

#### Prerequisites

- Step 2.2 merged.

#### Prompt

```text
Masterplan step 2.3 — Strategy spec and signal-frame contract.

Read docs/masterplan/02-engine-and-data.md §2.1. Define `StrategySpec` as Rust types in `engine/crates/fefat-core` with serde and schemars, covering the v1 table (entries, exits, filters, sizing) and generate `python/fefat/strategy/strategy_spec.schema.json` from them in the build (a `just gen-schema` recipe and a CI check that the committed schema is current). Define the signal-frame contract: required boolean columns long_entry, short_entry, long_exit, short_exit; optional entry_price, stop_price, target_price, trail_ref, size_mult, wake; all aligned to the signal bars' ts_close.

In Python, add `fefat.strategy.SignalStrategy`, `Execution`, and the helper classes shown in 02 §5 (Market, Stop, Target, Breakeven, TimeRules, Limits, Fixed, …) as Pydantic models that validate against the schema and serialise to the spec. In this phase `features` are plain Polars expressions over the bars frame (for example `pl.col("close").ewm_mean(span=20)`); the `@ff.feature` decorator and `fefat.ta` arrive in Phase 3 and plug into the same slot. Add `SignalStrategy.signals(bars) -> LazyFrame` that evaluates the expressions into a signal frame and validates it (types, alignment, no NaN in booleans).

Extend the reference engine to execute a StrategySpec's basic subset (market entry, stop, one target, flat-by) from a signal frame, so later Rust steps have an oracle for templates too.

Not in this step: trailing, breakeven, multiple targets in the reference engine (2.8), Rust engine.
```

#### Done means

1. `just gen-schema` produces the JSON schema and CI fails if it drifts from the Rust types.
2. Pydantic models round-trip: `SignalStrategy(...).to_spec()` validates against the schema and loads back equal.
3. A scenario-style test runs a signal frame plus a spec through the reference engine and matches hand-computed fills.

#### Your checks

- In a notebook, construct the example strategy from `02-engine-and-data.md` §5 with inline Polars expressions in place of `rsi(n=14)` and `ff.ta.atr(14)` (those arrive in Phase 3) and print `strat.to_spec()`; it reads like the builder form you expect.

#### If it fails

- schemars and Pydantic disagree on a type (for example enums): adjust the Rust side to plain tagged enums; the schema is the contract.

### 2.4 Rust core types and determinism harness

Depends on: 2.3 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

The engine's foundations: fixed-point money, newtype timestamps, orders, positions, a ledger with invariants, and a harness that proves runs are deterministic.

#### Prerequisites

- Step 2.3 merged.

#### Prompt

```text
Masterplan step 2.4 — Rust core types and determinism harness.

Read docs/masterplan/02-engine-and-data.md §4. In `fefat-core` implement the i64 newtypes (Price in 1e-9 units, Qty, Money in micro-units, Ts in ns), instrument parameters, the order model (market, stop-market, limit; side; time-in-force; activation time; OCO group), fills, positions, and a Ledger whose accounting identity (cash + position value = equity) is checked in debug builds and by proptest. Typed errors with thiserror; deny unwrap, panic, and unchecked indexing via clippy lints in the workspace; no HashMap iteration where order affects output (use BTreeMap or sorted vectors).

Add a determinism harness in `fefat-cli`: run the same synthetic input twice (and across two processes) and compare BLAKE3 hashes of the outputs; make it a test. Add the run-key function (BLAKE3 over spec, signal-frame hash, data partition hashes, engine and fill-model versions) and expose engine and fill-model version constants.

Not in this step: fills, the loop, data cache.
```

#### Done means

1. proptest invariants pass: accounting identity under random fills; no negative quantities from well-formed fills; long/short mirror symmetry of P&L.
2. The determinism test passes and runs in CI on both platforms with the same hash.
3. `cargo clippy -D warnings` passes with the lints enabled in the workspace.

#### Your checks

- Run `cargo nextest run -p fefat-core` (or `just test`): green. Open the ledger test file and read the accounting-identity test; it should state the identity in one line.

#### If it fails

- Overflow in money arithmetic: use checked operations and return typed errors; the engine must never wrap silently.

### 2.5 Memory-mapped data cache

Depends on: 2.4 · Plan mode: required · Reviews: step-reviewer · Security: no · Model hint: hard

#### Purpose

The engine reads market data at memory speed, shared across threads, without decoding Parquet on every run.

#### Prerequisites

- Step 2.4 merged.

#### Prompt

```text
Masterplan step 2.5 — Memory-mapped data cache.

Read docs/masterplan/02-engine-and-data.md §1.6. In `fefat-data` implement a cache builder that converts canonical Parquet partitions into uncompressed Arrow IPC files under FEFAT_HOME/cache/engine/<root>/<contract>/<month>/ with three levels (1-minute bars, 1-second bars, ticks) and an index of row offsets so the engine can descend from a bar to its seconds and ticks directly. The reader memory-maps the files (memmap2; the only unsafe in the workspace, documented) and exposes column slices. The cache is keyed by the partition content hashes and rebuilt when they change; `fefat cache build` and `fefat cache status` CLI commands drive it from Python.

Tests: round-trip equality with the Parquet source on synthetic fixtures; a missing level (ticks absent for a day) is represented explicitly; offsets map every bar to the right second and tick ranges (property test).

Not in this step: the engine loop.
```

#### Done means

1. Round-trip and offset property tests pass.
2. Building the cache for one year of ES 1-minute, 1-second, and tick data takes under 3 minutes on this PC and the result size is reported (PR).
3. `fefat cache status` shows which levels exist per contract-month.

#### Your checks

- Run `fefat cache build --root ES --year 2025` then `fefat cache status`: the months you own show `1m`, `1s`, and `tick` where you have ticks.

#### If it fails

- Memory errors on Windows for large files: map per file, not per month; keep files under 2 GB.

### 2.6 Rust engine on ticks with differential tests

Depends on: 2.5 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

Realistic market, stop, and limit fills on ticks, proven identical to the reference engine on every scenario and on thousands of generated tapes. Prop drawdown simulation later depends on these fills, so a plausible but wrong rule here would corrupt every later result without a visible error.

#### Prerequisites

- Steps 2.1–2.5 merged; the fill specification signed off.

#### Prompt

```text
Masterplan step 2.6 — Rust engine on ticks with differential tests.

Read docs/spec/fill-semantics.md, fixtures/scenarios/README.md, and how python/fefat/ref/engine.py fills orders. In `fefat-engine` implement the event loop over the tick level of the cache for one instrument: session and timer events, order activations (placed at a bar close, active at close plus latency), market events, then the bar-close decision; market, stop-market, and limit orders; a bracket with OCO; one position per strategy; fills by the rule identifiers in the spec, each fill tagged with its rule id and fidelity; the ledger from 2.4. Add a `fefat-cli run` that takes a spec, a signal frame (Arrow IPC), and a cache path and writes orders, fills, and an event log as Arrow IPC.

Follow the specification for gaps and same-tick ties; where it is silent, stop and ask rather than guess. Add the differential test: a Python test drives both engines on every YAML scenario and on 10,000 Hypothesis-generated tapes (random walks with gaps, random orders) and asserts identical fills; failures print the smallest failing tape. The Python bindings arrive in 2.10, so this test drives Rust through `fefat-cli`: batch many tapes into one invocation (one input file, one output file) so the suite runs in minutes, and record the runtime in the PR.

Not in this step: bar fidelities (2.7), trailing, breakeven, multiple targets, filters, sizing (2.8), costs (2.9).
```

#### Done means

1. Every scenario in `fixtures/scenarios/` passes in Rust, each showing tape, orders, and expected fills in the test output.
2. Property tests: no fill outside the traded price range of its interval; no fill before activation; equity equals cash plus position value at every tick.
3. The Python reference engine agrees on every scenario and on 10,000 seeded random tapes; the seed is recorded so a failure reproduces.
4. The determinism hash is unchanged between two runs of the same input.

#### Your checks

- Open scenario S-fill-012 (gap through a stop) in `fixtures/scenarios/`: stop 4995.00, next trade 4990.25, so the fill must be 4990.25. Run `notebooks/checks/2.06.ipynb`; the last cell prints `0 differences` for the differential run.

#### If it fails

- If Rust and the reference disagree, ask for the smallest failing tape and judge it against the spec by hand. If Claude Code proposes changing a scenario's expected value, refuse: scenarios are the specification; change the spec first if the spec is wrong.
- Flaky property test: refuse larger tolerances; ask for the cause.

### 2.7 Bar-fidelity fills and hierarchical skipping

Depends on: 2.6 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Days with only 1-second or 1-minute bars are simulated by the spec's pseudo-tick rules, and the engine skips work it cannot need, with a test proving skipping changes nothing.

#### Prerequisites

- Step 2.6 merged.

#### Prompt

```text
Masterplan step 2.7 — Bar-fidelity fills and hierarchical skipping.

Read docs/spec/fill-semantics.md (bar fidelities) and docs/masterplan/02-engine-and-data.md §4 (hierarchical replay). Implement bar-fidelity replay: a bar is replayed as four pseudo-ticks (open, adverse extreme, favourable extreme, close) according to the spec; stop and target inside one bar resolve to the stop and the fill is flagged ambiguous; fills carry the fidelity tag 1s or 1m. Implement hierarchical descent: process the 1-minute bar first and descend to 1-second bars and ticks only when the bar's range can reach a trigger level (a working order, a trailing update, or an account floor), using the cache's offsets.

Tests: scenarios for bar fidelities from 2.1 pass; "skip equals no-skip": on synthetic months with mixed fidelity, the skipping engine and a naive full-replay engine produce identical fills and ledgers (property test with random strategies); the reference engine agrees on bar-fidelity scenarios.

Not in this step: the full exit plan, costs.
```

#### Done means

1. Bar-fidelity scenarios pass in Rust and in the reference engine.
2. The skip-equals-no-skip property test passes on 1,000 generated cases; the ambiguous-fill counter matches between the two.
3. A timed run shows the speedup from skipping on a synthetic year (PR).

#### Your checks

- Run `notebooks/checks/2.07.ipynb`: the comparison cell prints `identical` and the timing cell shows the skipping engine is faster.

#### If it fails

- Any difference between skip and no-skip is a bug in descent conditions, never acceptable; ask for the smallest failing case.

### 2.8 Full exit plan, filters, sizing

Depends on: 2.7 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Everything the signal-strategy template promises works: multiple targets, breakeven, trailing, time exits, session windows, daily limits, cooldowns, and sizing modes — in Rust and in the reference engine.

#### Prerequisites

- Step 2.7 merged.

#### Prompt

```text
Masterplan step 2.8 — Full exit plan, filters, sizing.

Read docs/masterplan/02-engine-and-data.md §2.1 (the v1 table) and docs/spec/fill-semantics.md. Implement `ExitPlan` in `fefat-engine`: up to three targets with fractions (ticks, ATR multiple, R multiple, column), OCO with the stop; breakeven at a profit threshold or after target N; trailing by distance, step, or indicator column, with an activation threshold and intrabar or bar-close updates; max bars or minutes; flat-by time; no-overnight and no-weekend rules; signal exits. Implement entry filters (time windows by time zone and weekday, blackout column, max trades and losses per day, daily loss stop and profit lock, cooldown, fresh-signal requirement) and sizing (fixed units, fixed notional, risk per trade in currency or percent of equity over the stop distance, size_mult column, forced one unit for prop base runs). Extend the spec where necessary, keep the schema current, and extend the reference engine to the same features.

Add 60 scenarios for these rules (trailing updates intrabar on ticks, breakeven after the first target, flat-by across a daylight-saving change, cooldown after a loss, risk sizing with rounding) and extend the differential test to random templates.

Not in this step: costs and funding (2.9), rolls.
```

#### Done means

1. The new scenarios pass in both engines; the differential test with random templates passes on 10,000 cases.
2. Property tests: a trailing stop never moves against the position; breakeven never worsens the stop; the daily loss stop prevents new entries after it triggers.
3. The schema and the Pydantic models cover every feature; `just gen-schema` is current.

#### Your checks

- Run `notebooks/checks/2.08.ipynb`: it runs the example strategy with two targets and breakeven on one real week and prints the trades with exit reasons; pick one trade with exit reason `target_1` and confirm the second half later exited at the stop moved to breakeven.

#### If it fails

- Time-zone errors around daylight-saving: the time rules must be converted to UTC per trade date using the calendar from 1.3, never by a fixed offset.

### 2.9 Costs, funding, positions across rolls

Depends on: 2.8 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

P&L is net of realistic costs, crypto funding is paid, and a position held across a futures roll is transferred correctly.

#### Prerequisites

- Step 2.8 merged.

#### Prompt

```text
Masterplan step 2.9 — Costs, funding, positions across rolls.

Read docs/spec/fill-semantics.md (costs) and docs/masterplan/02-engine-and-data.md §1.5 and §3. Implement dated fee tables in the engine (per contract per side for futures; maker/taker basis points for crypto, resting limits as maker), slippage classes per order type, funding payments at funding timestamps for perpetuals, and the roll handling for an open position: on the roll date from the roll calendar, close on the old contract and open on the new one at market, both legs costed, bracket levels shifted by the gap; or flatten, by configuration. Record every cost line in the ledger with its reason. Add the reference-engine equivalents and scenarios (a roll with an open long and a shifted stop; a funding payment while short; maker versus taker fees; negative prices as in CL in April 2020, which the fixed-point types must handle).

Not in this step: bindings, metrics.
```

#### Done means

1. Roll, funding, and fee scenarios pass in both engines; the differential test covers random fee tables.
2. The ledger's cost lines reconcile: gross P&L minus the sum of cost lines equals net P&L (property test).
3. A roll with an open position produces two fills on two contracts with the documented reason codes.

#### Your checks

- Run `notebooks/checks/2.09.ipynb`: the funding cell shows a short BTCUSDT position receiving or paying funding at the published rate for that hour.

#### If it fails

- If the roll date in the engine differs from the data layer's roll calendar, the engine must consume the calendar, not recompute it.

### 2.10 Python bindings, `ff.backtest`, run artifacts, run hash

Depends on: 2.9 · Plan mode: required · Reviews: step-reviewer, code-review · Security: no · Model hint: hard

#### Purpose

The fast engine is usable from Python with one call, every run writes its artifacts and manifest, and identical runs are recognised by hash.

#### Prerequisites

- Step 2.9 merged.

#### Prompt

```text
Masterplan step 2.10 — Python bindings, ff.backtest, run artifacts, run hash.

Read docs/masterplan/02-engine-and-data.md §5 and §7 and docs/masterplan/01-architecture.md §4. In `fefat-py` expose `run_signal_backtest(spec_json, signal_frame (Arrow), cache_paths, config) -> artifacts (Arrow tables)` and `run_batch(list of the same) -> list` (Rayon over the shared cache, GIL released), plus engine and fill-model version constants. In Python implement `fefat.backtest.run(strategy, start, end, config=...)`, exposed as `ff.backtest(...)` (the call shape used in 02 §5 and the tutorials), returning a `Run` object: it evaluates features and signals with Polars, resolves the data snapshot and cache, computes the run hash, calls the engine, writes orders, fills, trades (flat-to-flat episodes with MAE/MFE, R multiple, exit reason, contract, feature values at entry), equity_daily, bar equity, signals, log, and run.json under workspaces/default/artifacts/runs/<run_id>/, and returns an existing run when the hash matches. `Run` exposes `.trades`, `.fills`, `.equity(timeframe)`, `.config`, `.hash`.

Tests: the bindings return tables identical to fefat-cli output on the same inputs; a second identical call returns the cached run; the artifact folder matches the documented schema; identical hashes on Windows and Linux in CI for a synthetic run.

Not in this step: metrics (2.11), the web app.
```

#### Done means

1. `ff.backtest.run(...)` on a synthetic month completes and writes all artifacts with the documented schemas (schema test).
2. The run-hash dedupe test passes; CI asserts the cross-platform golden hash.
3. `run_batch` of 100 synthetic runs uses multiple cores (CPU time well above wall time, reported in the PR).

#### Your checks

- Run `notebooks/checks/2.10.ipynb`: the same strategy as 2.2 runs on the full month in seconds and the trade list equals the reference engine's list from 2.2 (the notebook compares them).

#### If it fails

- `DLL load failed` after a Rust change: `just build-engine` rebuilds the extension; the notebook kernel must be restarted.

### 2.11 Metrics and `run.explain`

Depends on: 2.10 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

Every run has the metric set from the design, computed once in Rust and verified against Python, and any trade can be explained event by event.

#### Prerequisites

- Step 2.10 merged; the reference capital decision from the kickoff.

#### Prompt

```text
Masterplan step 2.11 — Metrics and run.explain.

Read docs/masterplan/02-engine-and-data.md §7. Implement `fefat-metrics`: profit factor, expectancy (currency, ticks, R), win rate, maximum drawdown and duration, worst day, daily CVaR, Sharpe and Sortino on daily P&L, probabilistic and deflated Sharpe (trial count as an input), MAE/MFE efficiency, breakdowns by exit reason, hour of day, weekday, year, and fidelity era, P&L at +1 tick (a rerun with one extra tick of slippage), best-day share, and the frequency of large daily losses. Percentages use the reference capital in the config. Expose through the bindings and `Run.metrics` (a Pydantic model). Verify every metric against an independent Python implementation on random trade lists (test).

Implement `Run.explain(trade_id)`: replay the trade's episode through the Python reference engine on the same tape and print each event (activation, triggers, fills, exits) with the rule ids, and assert the reference's fills equal the Rust fills for that episode.

Not in this step: charts, the web app.
```

#### Done means

1. Metric parity tests pass against the Python implementation on 1,000 random trade lists.
2. `Run.explain` prints the event list for a trade and asserts agreement with Rust.
3. `Run.metrics` serialises to JSON and is stored in run.json.

#### Your checks

- In a notebook, run `run.explain(trade_id=…)` for a losing trade: the printed sequence shows the stop trigger tick and the fill with its rule id and slippage.

#### If it fails

- A metric disagreement usually comes from day boundaries (trade date versus calendar date); daily P&L must use the calendar's trade date.

### 2.12 Mixed fidelity and `fidelity_check`

Depends on: 2.11 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

Backtests spanning years with ticks only in the recent year are honest: results are split by fidelity, and the error from lower fidelity is measured.

#### Prerequisites

- Step 2.11 merged.

#### Prompt

```text
Masterplan step 2.12 — Mixed fidelity and fidelity_check.

Read docs/masterplan/02-engine-and-data.md §1.6. Make the engine choose the finest level present per day (TBBO over trades over 1-second over 1-minute) and record the fidelity era of every day in run.json and every fill. Add `fefat.backtest.fidelity_check(run)`: rerun the tick-covered period at 1-second fidelity and at 1-minute fidelity, and report the differences in trade count, net P&L, maximum drawdown, and per-trade fill prices, as the error bar for the lower-fidelity years. Show the fidelity split and the check's result in `Run.metrics` and in a `Run.report()` text summary.

If you have real fill exports (kickoff decision), add `fefat.backtest.reconcile(run, fills_csv)` that matches simulated and actual fills by time and compares slippage; otherwise stub it with a clear "no exports" message and a backlog item.

Not in this step: the web pages.
```

#### Done means

1. On a synthetic year with ticks for the last quarter only, run.json shows the fidelity eras and `fidelity_check` runs.
2. `Run.report()` prints the metrics split by era and the fidelity-check deltas.
3. A test asserts the engine picks TBBO when both TBBO and trades exist for a day.

#### Your checks

- Run `fidelity_check` on a real strategy over your tick year: read the deltas; a few percent of net P&L between tick and 1-second fills is typical, more than that tells you the strategy is sensitive to fills.

#### If it fails

- If the 1-minute rerun differs wildly, check that the strategy's stops are not inside the typical 1-minute range; that is a property of the strategy, not a bug.

### 2.13 Cross-check against NautilusTrader

Depends on: 2.12 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

An independent, established engine agrees with FEFAT on the same data under a compatibility profile, and every difference is understood.

#### Prerequisites

- Step 2.12 merged; the real month chosen at the kickoff.

#### Prompt

```text
Masterplan step 2.13 — Cross-check against NautilusTrader.

Read docs/masterplan/02-engine-and-data.md §8 item 5. In a separate test-only uv environment (`python/tests/external/`), install nautilus_trader (pinned) and load the same Databento month through its Databento adapter. Run the same three simple strategies (market entries with a bracket; limit entries; stop entries) in both engines under a compatibility fill profile in FEFAT (last-quote fills, touch fills for limits, zero slippage, zero latency) that matches Nautilus's documented behaviour. Produce a comparison report: trade-by-trade matches, and every differing fill classified into a documented class (bar-boundary convention, aggressor-side limit fills, ts_recv ordering, roll handling) with an explanation. Keep this out of the default `just test` (it is slow and needs real data); add `just xcheck`.

Not in this step: changing FEFAT defaults to match Nautilus — the conservative profile stays the default.
```

#### Done means

1. `just xcheck` produces `docs/validation/nautilus-comparison.md` with match rates and the difference classes.
2. Every difference belongs to a documented class; none is "unknown".
3. The report states the versions of both engines and the data snapshot hash.

#### Your checks

- Read the comparison report: the match rate for market-order strategies should be very high; read the explanation for the largest class of differences and see whether you agree.

#### If it fails

- If Nautilus cannot load your DBN files (version mismatch), convert them with the `dbn` CLI in the test environment; do not alter the raw files.

### 2.14 Benchmarks and tutorial

Depends on: 2.13 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Performance is measured and guarded against regression, and you have a tutorial that teaches the SDK in your own words.

#### Prerequisites

- Step 2.13 merged.

#### Prompt

```text
Masterplan step 2.14 — Benchmarks and tutorial.

Add criterion benchmarks in `fefat-engine` on a seeded synthetic dataset (one year, mixed fidelity): a single signal-strategy run, a run with the full in-position tick scan, and a 1,000-run batch; record the baseline numbers in `docs/validation/benchmarks.md` with the machine description. In CI, run the benchmarks as a non-blocking job that posts the numbers and warns above a 30% regression against the stored runner baseline (shared runners are too noisy for a hard 15% gate); the local numbers on this PC are the reference. Install `cargo-mutants` and add `just mutants` for the phase exits. Profile and fix the obvious hot spots if targets in docs/masterplan/02-engine-and-data.md §4 are missed by more than 2x; otherwise note the gap for a later pass.

Write `notebooks/02-engine-tutorial.ipynb`: load data, define a feature inline, define a SignalStrategy, run, read metrics, explain a trade, run fidelity_check, run a small batch of parameter variants; and `docs/engine-guide.md` for you: the strategy template reference with every option, the fill rules in brief with a link to the spec, and how to read a run folder.

Not in this step: new engine features.
```

#### Done means

1. Benchmarks run locally and in CI (non-blocking, with the warning threshold); the baseline file exists; `just mutants` runs on `fefat-engine`.
2. The tutorial runs top to bottom on your data.
3. `docs/engine-guide.md` documents every `Execution` option with a one-line meaning.

#### Your checks

- Run the tutorial. Note the time for a 5-year run on your machine; it should be seconds, not minutes.

#### If it fails

- If targets are missed badly, do not optimise blindly: ask for a profile (`cargo flamegraph` or `perf`) and a plan before changing the loop.

## Phase exit

```text
/phase-exit 2 — Run the exit procedure for Phase 2: clean-clone suite; engine-accuracy-reviewer over the whole phase diff; /code-review high; mutation testing on fefat-engine fill code with the kill rate recorded; demo script = notebooks/02-engine-tutorial.ipynb plus run.explain on one trade; retro into CLAUDE.md and rules; backlog groomed; tag phase-2.
```
