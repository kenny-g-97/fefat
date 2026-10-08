# Phase 3 — Features

**Goal.** The feature system of the SDK: a clear contract for feature functions, a runtime that resolves dependencies and multiple timeframes, a cache that makes previews instant, a leak detector that catches look-ahead on save, an indicator library verified against TA-Lib, combinators, and feature analytics — all usable from notebooks and feeding signal strategies.

**You get.** `@ff.feature` functions with versions, `ff.features.validate(f)` leak checks, `ff.indicators.*`, `ff.analytics.*`, and strategies that reference library features.

**Depends on.** Phase 2.

**Skills.** `software-design-principles` for every step; `backtest-expert` for 3.4 (leak detector) and 3.8 (analytics), whose look-ahead and data-mining sections apply.

**Open decisions for the kickoff.** Your first indicator list (the defaults are the usual 30: moving averages, RSI, ATR, Bollinger, MACD, stochastic, ADX, VWAP, anchored VWAP, opening range, volume profile basics); whether you already have feature code from notebooks to port.

## Kickoff

```text
/phase-kickoff 3 — Read docs/masterplan/phases/P03-features.md and docs/masterplan/02-engine-and-data.md §6. Ask me the open decisions. Check the data API and the signal-frame contract from Phases 1–2 against these steps and amend as needed. Open the kickoff PR.
```

## Steps

### 3.1 Feature contract and versions

Depends on: 2.15 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

What a feature is, is fixed: inputs, parameters, outputs, warm-up, and an immutable content-hashed version.

#### Prerequisites

- Phase 2 complete.

#### Prompt

```text
Masterplan step 3.1 — Feature contract and versions.

Read docs/masterplan/02-engine-and-data.md §6 and §5 (the decorator example). Implement `fefat.features`: the `@ff.feature(params=..., warmup=..., inputs=...)` decorator producing a `FeatureDef` with a typed parameter schema (Pydantic, generated JSON schema), declared inputs (the bars frame by default; other features, other instruments, higher timeframes, datasets), one or more named outputs, and a declared warm-up (bars or a function of params). Calling a FeatureDef with params returns a `FeatureSpec` (definition + bound params) that evaluates to Polars expressions or a frame on the signal-bar grid. Content hash = source code of the function (normalised) + dependency hashes + parameter schema; versions are immutable `FeatureVersion` records stored as files under workspaces/default/features/<name>/v<n>.json in this phase (the database comes in Phase 4) with code, hash, schema, inputs, warm-up, and timestamps.

Rules: a feature may only read bars up to the current row (no negative shifts; the AST lint from 3.4 enforces); outputs are float columns aligned to ts_close; NaN during warm-up is allowed and flagged.

Not in this step: runtime for dependencies (3.2), cache, leak detector.
```

#### Done means

1. A feature defined in a notebook round-trips through `FeatureVersion` (save, load, identical hash); changing a default parameter or one character of code changes the hash.
2. Parameter validation rejects wrong types with a readable message.
3. Three example features (RSI, ATR, a session-time flag) live in `python/fefat/src/fefat/features/examples.py` with tests.

#### Your checks

- In a notebook, define a feature with a parameter, save it, print its version record: code, hash, and schema are there.

#### If it fails

- Hashing must not depend on file paths or on the Python version's bytecode; it is over normalised source text.

### 3.2 Runtime, dependencies, multi-timeframe and cross-instrument inputs

Depends on: 3.1 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

Features can depend on other features, on higher timeframes, and on other instruments, and the runtime evaluates them in the right order with as-of joins that only see closed bars.

#### Prerequisites

- Step 3.1 merged.

#### Prompt

```text
Masterplan step 3.2 — Runtime, dependencies, multi-timeframe and cross-instrument inputs.

Implement `fefat.features.runtime`: build a dependency graph from FeatureSpecs, evaluate in topological order, and resolve extra inputs: a higher-timeframe input is built with the bar builder and joined as-of on ts_close (a 15-minute bar is visible only after its close, never while in progress); a cross-instrument input (for example NQ bars for an ES feature) is loaded for the same range and joined as-of on ts_close with staleness recorded; a dataset input (Phase 10) is reserved in the interface. Warm-up is propagated through the graph so the requested range is complete. `ff.features.compute(specs, instrument, timeframe, start, end) -> LazyFrame` returns all outputs on the signal-bar grid.

Tests: a 15-minute feature joined onto 5-minute bars never changes a value before the 15-minute close (hand-built fixture); cross-instrument join aligns by ts_close with a staleness column; dependency cycles are rejected with a clear error.

Not in this step: cache (3.3).
```

#### Done means

1. The in-progress-bar test and the cross-instrument test pass.
2. `compute` of a three-level dependency graph returns correct values (fixture with hand-computed expectations).
3. Warm-up propagation yields no NaN in the requested range for a chain of features with known warm-ups.

#### Your checks

- In a notebook, compute a 15-minute RSI onto 5-minute ES bars for one day and print the rows around a 15-minute boundary: the value changes only at the boundary.

#### If it fails

- If values change mid-bar, the join is on ts_open; it must be on ts_close of the higher timeframe.

### 3.3 Cache

Depends on: 3.2 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Computed features are stored and reused, so previews and backtests on the same feature are instant and sweeps do not recompute.

#### Prerequisites

- Step 3.2 merged.

#### Prompt

```text
Masterplan step 3.3 — Feature cache.

Implement a feature cache under FEFAT_HOME/cache/features/: Parquet partitions keyed by (feature version hash, bound parameter hash, instrument, timeframe, input-partition hashes), computed per partition with warm-up overlap, so a new month only computes the new month. `compute` consults the cache first; `ff.features.cache_status()` and `fefat cache features --prune` manage it. Keep a small index (SQLite or JSON) of entries with sizes and last-used times.

Tests: chunked computation equals whole-range computation (exact equality, property test over random cut points); a cache hit is used when inputs are unchanged and missed when one input partition's hash changes; pruning by age works.

Not in this step: anything else.
```

#### Done means

1. Chunked-equals-whole and hit/miss tests pass.
2. A second `compute` of a one-year feature returns from cache in well under a second (timed test, generous bound).
3. Cache entries are invalidated when the underlying data partition changes (test).

#### Your checks

- In a notebook, time `compute` twice for the same feature over a year: the second call is near-instant.

#### If it fails

- If chunked results differ from whole-range results, the warm-up declared by the feature is too small; the runtime must fail loudly rather than return wrong edges.

### 3.4 Leak detector

Depends on: 3.3 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: hard

#### Purpose

Look-ahead is caught automatically when a feature is saved, by recomputing on truncated data and demanding identical values, plus a static lint for the usual mistakes.

#### Prerequisites

- Step 3.3 merged.

#### Prompt

```text
Masterplan step 3.4 — Leak detector.

Read docs/masterplan/02-engine-and-data.md §6 (leak detector) and docs/adr/ (prefix invariance). Implement `ff.features.validate(spec, instrument, timeframe, range)`: evaluate on the full range, then on data truncated at N cut points (random plus adversarial: session ends, roll dates, the last bar of a higher timeframe), truncating every input by its availability time, and require values before each cut to be identical (exact for integers and booleans; within 1e-9 relative for floats); a start-invariance check (shifting the start earlier by a warm-up multiple does not change values after warm-up) catches unbounded memory; an AST lint flags negative shifts, backward fills, centred rolling windows, and whole-frame normalisation. The result is a `ValidationReport` (passed, failing cuts with the first differing row and value, lint findings) stored with the version.

Tests: a suite of 25 planted leaks (look-ahead shift, full-sample z-score, repainting pivot, in-progress higher-timeframe bar, wrong-direction join, future-anchored VWAP, min-max scaling over the full sample, …) all flagged; 25 clean features all pass. Document what the detector misses (wrong availability timestamps, revised data, parameters chosen on the full sample) in the module docstring and in docs/engine-guide.md.

Not in this step: UI.
```

#### Done means

1. 25/25 planted leaks are flagged and 25/25 clean features pass (the suite lives in `python/tests/features/leaks/`).
2. `ValidationReport` identifies the first failing cut and row for a planted leak.
3. The lint runs in under a second and explains each finding with the line number.

#### Your checks

- In a notebook, write a deliberately leaky feature (`close.shift(-1)`) and run `validate`: it fails with the cut and the row; fix it to `shift(1)` and it passes.

#### If it fails

- False positives on floats near cut points usually come from Polars' rolling-window numerics; use the documented tolerance, never disable the check.

### 3.5 Indicators, batch 1

Depends on: 3.2 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The common indicators exist as FEFAT features with verified numerics.

#### Prerequisites

- Step 3.2 merged; the indicator list from the kickoff.

#### Prompt

```text
Masterplan step 3.5 — Indicators, batch 1.

Implement `fefat.indicators` as FeatureDefs built from Polars expressions: SMA, EMA, WMA, RSI, ATR (Wilder), true range, Bollinger bands (middle, upper, lower, width, %b), MACD (line, signal, histogram), stochastic (%K, %D), ADX with +DI/−DI, ROC, momentum, standard deviation, z-score over a window, Donchian channels, Keltner channels, OBV. Each declares its warm-up. Golden-test every one against TA-Lib (installed as a test dependency; Windows wheels exist) on the synthetic fixtures and on random series, with the documented tolerance and TA-Lib's seeding conventions reproduced exactly.

Not in this step: session-aware indicators (3.6), the agent.
```

#### Done means

1. Every indicator in the list has a TA-Lib golden test that passes within the tolerance stated in the test file.
2. Each indicator's warm-up is tested: no NaN after warm-up on a clean series.
3. `ff.indicators` has a module docstring table of indicators with parameters.

#### Your checks

- In a notebook, compute `ff.indicators.rsi(14)` on a month of ES 5-minute bars and compare three values against your charting platform's RSI: they match to the second decimal.

#### If it fails

- EMA seeding differs between libraries (SMA seed versus first value); match TA-Lib's convention and document it.

### 3.6 Indicators, batch 2 and session-aware features

Depends on: 3.5 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: default

#### Purpose

Indicators that depend on the trading session — the ones intraday futures traders use — exist and are leak-free.

#### Prerequisites

- Step 3.5 merged.

#### Prompt

```text
Masterplan step 3.6 — Indicators, batch 2 and session-aware features.

Add to `fefat.indicators`: session VWAP and anchored VWAP (anchors: session open, week open, a boolean column), opening range (high, low, width for a configurable window after the open), previous session high/low/close, session high/low so far, distance from VWAP in ATRs and in ticks, time since session open, bars since an event (boolean column), rolling realised volatility, relative volume versus the same time-of-day average over N sessions, cumulative delta from TBBO aggressor sides (tick-level input aggregated to bars), and a swing high/low detector that only confirms after N bars (no repainting). All are built on the calendar's trade dates and pass the leak detector.

Tests: hand-computed expectations on a synthetic session; leak-detector pass for every feature in this batch; the swing detector is tested to confirm only after N bars.

Not in this step: volume profile (backlog), the agent.
```

#### Done means

1. Every batch-2 feature has a hand-computed test and passes `ff.features.validate`.
2. The relative-volume feature uses only prior sessions (test).
3. Cumulative delta from TBBO equals a direct computation on the tick fixture.

#### Your checks

- In a notebook, plot session VWAP and the opening range on one real ES day: VWAP resets at the session open and the range appears after the configured window.

#### If it fails

- A session-aware feature failing the leak check at session ends means it peeks at the next session's open; anchor on the calendar, not on the next row.

### 3.7 Combinators and features inside signal strategies

Depends on: 3.4, 3.6 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: default

#### Purpose

Features combine into new features without code, and strategies reference library features by version, pinning them in every run.

#### Prerequisites

- Steps 3.4 and 3.6 merged.

#### Prompt

```text
Masterplan step 3.7 — Combinators and features inside signal strategies.

Implement `fefat.features.combine`: declarative combinators that produce new FeatureDefs from existing ones — arithmetic (add, subtract, multiply, divide, ratio to), comparisons and logic (greater than, crosses above/below, and/or/not), windows (rolling mean/std/min/max/rank/z-score, lagged values), normalisations (percent rank over N, scaled by ATR), resampling (a feature from a higher timeframe), and spreads across instruments. A combination is itself a feature with a derived code string (so it versions and validates like any other) and a JSON description (so the Phase 6 UI can render and edit it).

Make `SignalStrategy` accept library features by name and version (`features={"rsi": ff.features.ref("rsi", version=3, n=14)}`) and record the pinned feature versions in the strategy's serialised definition and in run.json (database-stored strategy versions arrive in Phase 5 and carry the same pins). Add `ff.features.library()` listing saved features and versions.

Tests: combinator code generation round-trips; a strategy referencing two library features runs end to end and run.json lists their version hashes.

Not in this step: the UI, the database.
```

#### Done means

1. Combinators produce valid FeatureDefs that pass validation and version like hand-written ones.
2. A run with library features records their versions; changing a feature's version changes the run hash.
3. The JSON description of a combination is documented for the Phase 6 UI.

#### Your checks

- In a notebook, build `rsi_stretch = rsi(14) - rolling_mean(rsi(14), 10)` with combinators, validate it, and use it in a strategy run.

#### If it fails

- If a combination's code string is not deterministic (dictionary ordering), the version hash will change between runs; the generator must sort keys.

### 3.8 Feature analytics and notebook demo

Depends on: 3.7 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: default

#### Purpose

Before any strategy exists you can judge a feature's predictive power honestly, and the phase's capabilities are demonstrated in one notebook.

#### Prerequisites

- Step 3.7 merged.

#### Prompt

```text
Masterplan step 3.8 — Feature analytics and notebook demo.

Read docs/masterplan/02-engine-and-data.md §6 (analytics). Implement `fefat.analytics`: forward returns from the next bar's first tradable price for horizons in bars (typed `Label`, rejected as a strategy input); mean forward return by feature quantile with day-block bootstrap confidence intervals; daily rank information coefficient (mean, t-statistic, by year) and its decay by horizon; a Spearman correlation matrix across features with hierarchical clustering; event studies and MAE/MFE distributions for boolean signals; and a "trials" counter that records how many features and horizons were examined, shown beside every result. Results are Polars frames plus a text report; keep plotting out of the SDK except simple helpers.

Write `notebooks/03-features.ipynb`: define a feature, validate it, compute it with cache timing, build a combination, run the analytics on two features, and show the trials counter. Update docs/engine-guide.md with a features section.

Not in this step: the web pages (6.5).
```

#### Done means

1. A planted predictive feature (synthetic data with a known relationship) is recovered with a significant IC; a random feature is not (tests).
2. `Label` columns are rejected by `SignalStrategy` with a clear error (test).
3. The notebook runs on your data and the report shows the trials counter.

#### Your checks

- Run the notebook; look at the quantile-return table for `rsi_stretch`: the extreme quantiles should differ from the middle ones if the feature has any edge, and the confidence intervals tell you whether to believe it.

#### If it fails

- Forward returns must start from the next bar's open (or first tradable price), never from the current close; the leakage-auditor checks this.

## Phase exit

```text
/phase-exit 3 — Run the exit procedure for Phase 3: clean-clone suite; leakage-auditor over the phase diff; demo script = notebooks/03-features.ipynb; retro; backlog groomed; tag phase-3.
```
