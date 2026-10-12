# 02 — Market data, engine, features, results, validation

This is the design of the quantitative core: the `fefat` SDK and the `fefat_engine` Rust extension. It was produced by a design review on 2026-10-05 and reconciled with the local-first decision. Normative details (exact fill rules) live in `docs/spec/fill-semantics.md`, written in step 2.1 and signed off by you.

## 1. Market data

### 1.1 Canonical store

- **Format:** Parquet with zstd, in Databento-native units: prices as `int64` in 1e-9 units, timestamps as `int64` nanoseconds UTC. Both `ts_recv` and `ts_event` are kept.
- **Clock:** the engine clock is `ts_recv` (Databento buckets its own bars on it, and its 1-second bars are the affordable history for older years, so both eras must share one clock). Ingest asserts `ts_recv` is non-decreasing within a file.
- **Partitioning:** `data/<provider>/<schema>/root=ES/contract=ESH4/date=2024-02-13/part.parquet` for ticks and 1-second bars (per trade date), per month for 1-minute bars, one file per contract for daily bars and statistics. Definitions and statistics keep their own schemas.
- **Raw files are immutable.** Vendor files (`.dbn.zst`, Binance zips) stay under `data/raw/` with a manifest (SHA-256, byte size, vendor version, download date). Databento re-normalised CME history in August 2026; the manifest is how a changed re-download is detected.
- **Snapshots.** A data snapshot is the list of partitions a run read, each with its content hash. Runs pin snapshot hashes, not "the data as of today".

### 1.2 Identity and metadata

- A contract is `(root, expiry year-month)`, resolved from Databento's `instrument_id` per day — never the raw symbol alone (ESZ6 was 2016 and is 2026 again).
- Instrument metadata (tick size, point value, lot step, currency, calendar id, fee table) is time-versioned (`valid_from`, `valid_to`).
- Fee tables are dated and named per broker or prop firm; a run config names one.

### 1.3 Calendar and trade date

- An explicit session table per product group: trade date, open and close as UTC instants, built from IANA time zones and a holiday table, and **validated against observed data** (first and last print of each day).
- Trade date comes from session membership, not from clock arithmetic. Holiday sessions fold into the next trade date the way CME does.
- Crypto uses a 24x7 calendar with UTC-day sessions and a funding event stream.
- A generic session calendar (time zone, daily open and close, weekdays, optional holiday list) covers products imported by traders that fit none of the built-in groups.

### 1.4 Bars

- Trades are bucketed by `ts_recv` into `[t, t+Δ)` anchored to the session open. Stored bars are sparse (printed only when trades occur) and carry `ts_open` and an explicit `ts_close`.
- **Signal bars** use a dense session grid with zero-volume bars flagged, so multi-timeframe and cross-instrument joins are exact.
- Daily bars follow the trade date and carry the official settlement (from the `statistics` schema) with its availability time.
- Bars rebuilt from trades must equal the vendor's 1-second and 1-minute bars; this is a test in step 1.5.

### 1.5 Rolls and continuous series

- Roll decisions are computed locally from per-contract volume through session d−1 and take effect at the open of session d. Default rule: volume, no roll-back, forced before expiry. Open-interest and calendar rules are options. Decisions are tested against Databento's `ES.v.0` mapping.
- Continuous signal bars are **forward-anchored**: history never changes when a roll happens; new contracts are shifted to join the old series. Columns: `close` (adjusted), `close_raw`, `adj_offset`, `contract`, `roll_flag`. Price-level signals convert to raw prices through `adj_offset`. Back-adjusted series exist for chart display only. (Reason: back-adjustment rewrites every past value at each roll, which invalidates feature caches and trips the leak detector on honest features.)
- Execution always uses the actual contract's raw prices, tick size, and point value. A position held across a roll is transferred by default (close old, open new at market, both legs costed, bracket levels shifted by the gap) or flattened by configuration.

### 1.6 Engine cache and mixed fidelity

- The engine does not read Parquet. `fefat-data` builds an uncompressed, memory-mapped Arrow IPC cache with up to three levels per contract-month (1-minute, 1-second, ticks) and row offsets for direct descent between levels; a product imported with only coarser bars (for example 5-minute or daily) has that one level, which is then its finest. Mapped pages are shared by every sweep thread and process. The cache is rebuildable and lives under `cache/`.
- The engine uses the finest level present for each day (TBBO preferred over trades for ticks) and records the fidelity era in every run. `fidelity_check` reruns the tick year at 1-second fidelity; the difference is the error bar quoted for older years.

### 1.7 Crypto

Same tables and the same engine. Binance USD-M perpetuals and spot from the free archive (1-second spot klines, 1-minute perpetual klines, aggTrades, funding, open interest), Bybit as a cross-check. Funding payments are events with timestamps. Maker/taker fees in basis points.

### 1.8 Data sources: connected accounts and imported files

FEFAT ships no market data (decision D-37, [ADR-0018](../adr/0018-own-data-sources-no-shipped-data.md)). Every dataset is fetched on the trader's machine through a source the trader connects, or imported from the trader's files; both land in the same canonical store and are used the same way. Every dataset carries its `origin` (`sync` or `import`), its `provider` (the connector or preset), and the licence scope the source's terms give the trader, and every run records the datasets it read.

- **The product catalog.** A versioned `catalog.yaml` (`python/fefat/src/fefat/market/catalog/`) lists the curated products — by default ES, NQ, CL, GC and their micros, and BTC and ETH spot and perpetuals — each with its instrument specification, calendar, roll rule, schemas, history depth, update cadence, and the sources that can supply it, in order of recommendation. `fefat data sync` keeps a product complete, checked, and current through the trader's connected sources: it runs the connectors (with the cost preview before any paid download), rebuilds bars and continuous series for the new range, and runs the quality report. The commercial version is the same code on the customer's machine with the customer's own accounts; Phase 14 adds signed updates of the catalog itself (specifications, calendars, roll rules, presets, the source guide), never of data.
- **The source guide.** `fefat.market.sources` registers the known sources, each with what it offers, what it costs, and the terms a trader accepts for personal use: connectors for vendor accounts and public archives (Databento for futures ticks, bars, definitions, and settlements, with the trader's own key; the crypto archives of Binance Vision, Bybit, Kraken, Coinbase, and Hyperliquid), and import presets for common exports (Databento CSV, NinjaTrader, Sierra Chart, TradeStation, TradingView, and the ones the Phase 1 kickoff adds from its research). Every connector implements one `Provider` interface (`describe()`, `fetch(symbol, schema, range)`, and a cost preview where downloads cost money), so adding a vendor is adding one provider. `fefat data sources` prints the guide with each source's connection state, and `fefat data connect <source>` stores a key through the credential store.
- **Your own data.** `fefat data import file` brings in bar and tick files (CSV, TSV, Parquet, zipped or gzipped) through saved import profiles: column mapping, timestamp format and time zone, whether timestamps mark the bar open or close, price scaling, the timeframe (ticks, or bars of any timeframe; bars coarser than 1 minute make backtests fill at that coarser fidelity, and reports say so), the series type (per contract with contract codes, or a continuous series, unadjusted or back-adjusted — continuous imports run as one synthetic contract with roll handling off and a warning on every run that uses them, since back-adjusted prices distort price levels), and the instrument (an existing one, or a new specification entered once, with an existing calendar or a simple custom session calendar). Presets are entries of the source guide. Imports go through the same bar building, calendar check, and quality report as synced data, keep the original file under `data/raw/user/`, and never leave the machine.
- **Overlaps.** When several datasets cover the same instrument and range (a synced one and an imported one, or two providers), all are kept as separate datasets; loads use the catalog's recommended source unless an origin or provider is named, and the catalog shows every one.

## 2. Strategies: two kinds on one engine

Both kinds are front ends to one engine `Strategy` trait and share one exit machinery (`ExitPlan`) in Rust.

### 2.1 Signal strategies (first release)

A `StrategySpec` JSON document (schema generated from the Rust types with `schemars`, shared by the builder form, the SDK, and the engine) plus a **signal frame** aligned to bar closes with columns:

- booleans `long_entry`, `short_entry`, `long_exit`, `short_exit`;
- optional numbers `entry_price`, `stop_price`, `target_price`, `trail_ref`, `size_mult`;
- optional boolean `wake` (bars where nothing can happen are skipped).

| Area | Covered in v1 |
| --- | --- |
| Entry | Market; limit or stop-market at a column price or an offset; time-to-live in bars; long/short stop pair as OCO; one position per strategy; opposite signal ignores, closes, or reverses |
| Exit | Stop (ticks, %, ATR multiple, column); up to 3 targets with fractions (ticks, ATR, R multiple, column), OCO with the stop; breakeven (at a profit threshold or after target N); trailing (distance, step, or indicator column; activation threshold; intrabar or bar-close updates); max bars or minutes; flat-by time; no overnight/weekend; signal exit |
| Filters | Entry windows by time zone and weekday; blackout column; max trades and max losses per day; daily loss stop and profit lock; cooldown after a loss; fresh signal required for re-entry |
| Sizing | Fixed units; fixed notional; risk per trade (currency or % of equity over stop distance); `size_mult` column. (Trade paths record prices and fills, so a run of any sizing can feed the prop simulator at any size.) |

Deferred to event strategies: scaling in, grids, multi-leg or multi-instrument coordination, portfolio logic, reactions to fills, stop-limit orders, account-aware logic.

### 2.2 Event strategies (Phase 9)

A Python class with `on_bar(ctx)`. Features are still precomputed and handed over once as Arrow, zero-copy. `ctx` is a Rust-backed object: `ctx.f.rsi` is the current value, `ctx.f.rsi[-3]` a past one; future rows cannot be indexed. Python never runs inside a bar: `on_bar` declares orders and exit plans at bar close, and the Rust `ExitPlan` executes them intrabar. A `wake` column lets the engine skip callbacks on bars with no setup and no live position. Signal strategies run with the interpreter detached and parallelise with threads; event strategies hold the GIL and parallelise with processes.

## 3. Fill and cost model

Orders decided at a bar close become active at close plus latency (default 100 ms). Buy side shown; sells mirror.

| Order | TBBO | Trades only | 1-second bars | 1-minute or coarser bars only |
| --- | --- | --- | --- | --- |
| Market | Ask of the first record at or after activation | First trade; +1 tick if seller-initiated or side unknown | Open of the first bar +1 tick | Same, flagged low fidelity |
| Stop-market at S | Triggers on a trade at or above S; fills at the next record's ask, never below S | max(S, trigger price) +1 tick | High at or above S triggers; max(S, open) +1 tick | Same |
| Limit at L | Fills at L when a trade prints below L or the ask reaches L | Trade below L | Low below L | Same |

**Conservative defaults** (configurable, shown on every report): limits need trade-through (touch and a volume-queue model are options); no price improvement; gaps fill at the gap price; no partial fills, with a warning when size exceeds displayed size. A bar is replayed as four pseudo-ticks (open, adverse extreme, favourable extreme, close), so a stop and a target inside one bar resolve to the stop; such fills are flagged `ambiguous` and counted. Every fill carries a fidelity tag.

**Costs:** futures pay per contract per side from a dated fee table; crypto pays maker/taker basis points (resting limits are maker) plus funding at funding timestamps. Slippage is a fixed number of extra ticks per order class. Every report includes a rerun at +1 tick, touch fills, and 1-second latency.

CME's own rule: a stop triggers when the market trades at or through the stop price ([CME](https://www.cmegroup.com/confluence/display/EPICSANDBOX/Order+Types+for+Futures+and+Options)).

## 4. Engine internals

- **Crates:** `fefat-core` (types, errors, calendar, orders and fills, and the `MarketDataReader` trait: 1-minute bars, 1-second bars, ticks, and the offsets between levels — the engine's port to market data), `fefat-data` (cache builder and memory-mapped reader implementing `MarketDataReader`; the only `unsafe`, for mmap, and the only engine crate that opens files), `fefat-engine` (`ExitPlan`, fill rules, loop, `TemplateStrategy`, `AccountModel`; pure computation over `fefat-core`, so its tests and the differential suite run on in-memory tapes), `fefat-prop`, `fefat-metrics`, and `fefat-py` and `fefat-cli` (spec in, artifacts out; they wire `fefat-data` into the engine and drive golden tests and benchmarks). The dependency rule and its enforcement: `08-code-design.md` §1.
- **Data and time:** prices, quantities, money, and timestamps are `i64` newtypes; market data is column slices. Local-time rules become UTC instants per trade date before the run.
- **Event order at equal time:** session and timer events, order activations, market events, then the bar-close decision. A bar `[t, t+Δ)` closes after every event before `t+Δ`.
- **Hierarchical replay:** 1-minute bar first, then 1-second bars, then ticks — descend only when a bar's range can reach a trigger level (a working order or a trailing update) or, while in a position, can make a new extreme of the trade path. Same fills, far less work. A "skip equals no-skip" test guards it.
- **Trade paths:** for every flat-to-flat trade, the loop records a compact path of the price the position is marked at — each new favourable extreme, each new adverse extreme since the last favourable extreme, and a mark at every minute boundary and at every fill, where the tracking restarts — with the trade's fidelity and a per-trade summary. With the fills, this lets the prop simulator recompute the position's profit and loss for any size, contract, and commission table without re-running (`03-prop-simulator.md` §4.2). Recording is a pure observer of the loop: fills never depend on it.
- **Determinism:** one thread per run; no wall clock; no hash-map iteration; integer ledger; seeded randomness only on request. Run key = BLAKE3(spec, signal-frame hash, data partition hashes, engine, fill-model, and artifact-schema versions). Reproducibility is defined from the stored signal frame, since float features can differ in the last bit across platforms.
- **Errors:** typed (`thiserror`); core crates lint against `unwrap`, `panic`, and unchecked indexing; data anomalies become run-log warnings, fatal under `strict`.
- **Accounts:** trait `AccountModel` (`pre_trade`, `on_fill`, `on_mark`, `on_time`, `trigger_levels`), implemented by `PlainAccount`. Prop accounts are not simulated inside the engine: the prop simulator replays saved runs' trades and trade paths afterwards (`03-prop-simulator.md` §4).
- **Targets on a 16-core/32-thread machine, warm cache, about 380M ticks behind a 5-year ES run (not yet measured):** a signal strategy under 3 s including trade-path recording (under 0.5 s for sweep trials, which skip paths); an event strategy under 15 s; 1,000 execution-parameter runs under 30 s, a few minutes when each run needs new features.
- **Sweeps:** `run_batch(specs)` runs Rayon threads over one mapped dataset; event strategies use a process pool.

## 5. Python boundary

- `maturin` with PyO3 `abi3-py312` gives one wheel per platform for CPython 3.12–3.14. Frames cross as Arrow through the PyCapsule interface (`pyo3-arrow`; Polars implements it), zero-copy both ways.
- Windows builds natively (MSVC) through `uv run maturin develop`; CI builds Windows and Linux wheels; a test requires identical artifact hashes on both.

```python
import fefat as ff, polars as pl

@ff.feature(params={"n": 14}, warmup=lambda n: 10 * n)
def rsi(bars: pl.LazyFrame, n: int) -> pl.Expr:
    d = pl.col("close").diff()
    up, dn = d.clip(lower_bound=0), (-d).clip(lower_bound=0)
    return (100 - 100 / (1 + up.ewm_mean(alpha=1/n) / dn.ewm_mean(alpha=1/n))).alias("rsi")

strat = ff.SignalStrategy(
    instrument="ES", timeframe="5m",
    features={"rsi": rsi(n=14), "atr": ff.indicators.atr(14)},
    long_entry=pl.col("rsi") < 30, short_entry=pl.col("rsi") > 70,
    execution=ff.Execution(
        entry=ff.Market(), stop=ff.Stop(atr=1.5),
        targets=[ff.Target(r=1, frac=0.5), ff.Target(r=2)],
        breakeven=ff.Breakeven(after_target=1),
        time=ff.TimeRules(windows=[("08:30", "14:30")], flat_by="15:05", tz="America/Chicago"),
        limits=ff.Limits(max_trades_per_day=3), sizing=ff.Fixed(1)))

run = ff.backtest(strat, start="2021-01-01", end="2025-12-31")
run.metrics; run.trades; run.equity("1d"); run.explain(trade_id=17)
```

`run.explain` replays one trade through the Python reference engine and prints each event.

## 6. Feature runtime

- **Contract:** a function of a bars `LazyFrame`, typed parameters, and declared inputs (dependencies, other instruments, higher timeframes) that returns named expressions on the same row grid and declares its warm-up. Extra inputs are joined as-of on `ts_close`, so only closed bars are visible.
- **Polars is the contract;** a pandas adapter is second-class (accepted on return, converted).
- **Indicators:** a small `fefat.indicators` (including session-aware ones such as anchored VWAP and opening range), golden-tested against TA-Lib.
- **Cache key:** code hash including dependencies, parameters, and input-partition hashes; computed per partition with warm-up overlap; chunked results must equal whole-range results.
- **Leak detector (on save):** recompute on data truncated at random and adversarial cuts (session ends, roll dates), truncating every input by availability time, and require identical values before the cut. A start-invariance check catches unbounded memory. An AST lint warns on negative shifts, back-fill, and centred windows. Catches: look-ahead shifts, full-sample normalisation, repainting pivots, wrong-direction joins, in-progress higher-timeframe bars. Misses: wrong availability timestamps and revised data; parameters chosen on the full sample; leaks in branches the cuts never reach.
- **Alternative data:** rows carry `event_time` and `available_at` plus a safety lag; backward as-of join on `available_at`; staleness exposed; vintages kept.
- **Analytics:** forward returns from the next bar's first tradable price; mean forward return by quantile with day-block bootstrap intervals; daily rank IC (mean, t-statistic, by year); IC decay by horizon; Spearman matrix with clustering; event studies and MAE/MFE distributions for boolean signals; the number of features and horizons tried shown beside every result. Forward-return columns are typed `Label` and rejected as strategy inputs.

## 7. Results model

Each run stores Parquet tables plus `run.json` (ids, hashes, versions, config, fidelity summary, warnings):

- `orders` and `fills` (fees, slippage against a reference price, fidelity, ambiguity flag);
- `trades`, one per flat-to-flat episode: net and gross P&L, R multiple and initial risk per unit, MAE and MFE in ticks, currency and R, maximum drawdown from peak, exit reason, contract, feature values at entry;
- `trade_paths`: each trade's compact price path (§4), which the prop simulator replays together with `fills`; run.json records the mix of path fidelities;
- equity: `equity_daily` always, bar-close equity for single runs; sweep trials keep metrics and a daily P&L vector, and get full artifacts, trade paths included, when saved as runs;
- `signals` (the exact frame used) and `log`.

Metrics: profit factor, expectancy (currency, ticks, R), win rate; maximum drawdown and duration, worst day, daily CVaR; Sharpe and Sortino on daily P&L, probabilistic and deflated Sharpe; MAE/MFE efficiency; breakdowns by exit reason, time of day, year, and fidelity era; P&L at +1 tick; best-day share and frequency of large daily losses for prop use. Currency and R are primary; percentages use a declared reference capital.

## 8. Validation strategy

1. **Scenarios:** at least 150 trader-readable cases (ticks or bars plus orders, with expected fills) in `fixtures/scenarios/` by the end of Phase 7 (added in steps 2.1, 2.7, 2.8, 2.9, 7.3, and 9.3), covering each order type at each fidelity, plus gaps, same-bar conflicts, daylight-saving days, rolls, negative CL prices, and funding. Scenario tables are the specification; a test is never fixed by editing an expected value.
2. **Differential:** Hypothesis generates tick paths, templates, and signals; the Rust engine must equal the Python reference exactly. Likewise skip equals no-skip, compact trade paths lose nothing a prop rule needs compared with a full tick-by-tick path, and prop replay of compact paths equals the Python reference machine fed with full paths.
3. **Invariants (proptest):** accounting identities; no fill before activation; stops never better than trigger, limits never worse than limit; long/short mirror symmetry; engine prefix-invariance; identical hashes across runs and operating systems.
4. **Data:** bars rebuilt from trades equal Databento's bars; the roll calendar matches `ES.v.0`.
5. **External engine:** NautilusTrader (test-only dependency, LGPL) on the same Databento month under a compatibility fill profile (last quote, touch, zero slippage); every differing fill must fall into a documented class.
6. **Real fills:** import broker or prop-platform exports, replay each order, compare simulated with actual slippage, calibrate defaults (when you have such exports).
7. **Test strength and speed:** mutation testing (`cargo-mutants`) on fill and prop crates with a 90% kill target; golden run snapshots whose change requires a fill-model version bump and your approval; benchmarks on a seeded synthetic dataset, with the local machine as the reference and a non-blocking CI job that warns on a 30% regression (shared runners are too noisy for a hard gate).

The `backtest-expert` skill (`.claude/skills/backtest-expert`) is loaded by every engine, prop, and research step: its methodology and red-flag checklist are the review lens for fills, costs, sample sizes, and robustness claims, and its five-dimension robustness summary is part of every run's metrics from step 2.11 (`08-code-design.md` §4).

## 9. Research tools

- Parameters are classed as feature (recomputed and cached), signal threshold (cheap: the signal frame is recomputed from cached features), or execution (free: the same signal frame); a study plans run specs to share work and calls `run_batch`.
- Grid and random search in-house; Bayesian search through Optuna's ask-and-tell interface in batches driven by the orchestrator.
- The sweep artifact is a metrics table plus a daily P&L matrix (parameter set × day). For strategies flat at each session end with unit sizing, walk-forward, PBO, and bootstrap come from that matrix without re-running; otherwise each window is re-run.
- Robustness: day-block bootstrap of drawdown and Sharpe; cost, latency, and parameter-neighbourhood reruns; random trade skipping. The bootstrap code is shared with the prop simulator.
- Minimum safeguards: an automatic trial count per strategy lineage feeding the deflated Sharpe ratio; a locked holdout with logged unlock; PBO from the sweep matrix; plateau-based selection; small-sample warnings; prop simulation fed by stitched out-of-sample trades by default.

## 10. Libraries (versions verified 2026-10-05)

- **Rust 1.99:** pyo3 0.29.3; pyo3-arrow 0.19.0 (pins arrow 59.x; stay on arrow and parquet 59.3); memmap2 0.9.11; rayon 1.12.0; serde 1.0.229; schemars 1.2.2; thiserror 2.0.21; blake3 1.8.7. Dev: proptest 1.11.0, insta 1.49.0, criterion 0.8.2, cargo-nextest 0.9.146, cargo-mutants 27.1.0.
- **Python 3.12** (wheel is abi3 from 3.12): maturin 1.15.0, polars 2.0.0 (since 2026-10-11, D-36; 1.44.2 when verified), pyarrow 25.0.1, numpy 2.5.3, pydantic 2.13.5, databento 0.87.0, exchange-calendars 4.13.2, TA-Lib 0.8.1 (for tests), optuna 5.0.0, arch 8.0.0, hypothesis 6.168.4, pytest 9.1.1; nautilus_trader 1.231.0 in a test-only environment.

Facts behind the design: Databento's OHLCV `ts_event` is the bar start based on `ts_recv` ([docs](https://databento.com/docs/schemas-and-data-formats/ohlcv)); continuous symbols rank on the previous day's volume or open interest ([docs](https://databento.com/microstructure/continuous-contract)); the `dbn` crate's trade `side` is the aggressor ([docs.rs](https://docs.rs/dbn/latest/dbn/record/struct.TradeMsg.html)); NautilusTrader uses `ts_recv` as event time and fills limits on aggressor-side trades ([docs](https://nautilustrader.io/docs/latest/concepts/backtesting/trade-execution)); PyO3 `abi3` wheels ([pyo3](https://pyo3.rs/latest/building-and-distribution.html)); `pyo3-arrow` works with Polars ([docs.rs](https://docs.rs/pyo3-arrow/latest/pyo3_arrow/)); arrow-rs zero-copy IPC over mmap ([docs](https://arrow.apache.org/rust/arrow_ipc/reader/struct.FileDecoder.html)); deflated Sharpe ([SSRN](https://papers.ssrn.com/abstract=2460551)); PBO ([SSRN](https://papers.ssrn.com/abstract=2326253)).
