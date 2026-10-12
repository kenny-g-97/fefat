# Phase 1 — Market data

**Goal.** One clean, documented, hash-pinned store on disk with correct session calendars, bars rebuilt and verified, continuous futures series built without look-ahead, and a quality report for every dataset, filled from the data sources you connect: vendor accounts and public archives through connectors (your own Databento account for futures, the free crypto archives), and files from any vendor or trading platform through import presets. FEFAT ships no market data (D-37); it ships the product catalog (specifications, calendars, roll rules, quality rules, a recommended source per product), the connectors and presets, a guide to well-known sources, and the sync that keeps each product current through your own sources.

**You get.** `ff.market.load("ES", "5m", "2024-01-01", "2024-12-31")` in a notebook returns correct bars; `fefat data sources` lists the suggested sources with their terms and which ones you have connected; `fefat data status` shows every catalog product with its coverage and quality; `fefat data sync` brings a product up to date through your connected sources, pricing any Databento download before pulling it; `fefat data import file` brings in your own files through saved profiles.

**Depends on.** Phase 0.

**Open decisions for the kickoff.** Which Databento files you already have (schemas, products, date ranges) and where they are; whether to buy one month of Standard now (`07-tools-and-costs.md` §3); which crypto venue (Binance by default; Kraken/Coinbase/Hyperliquid if you are US-based); the catalog product list (default ES, NQ, CL, GC and their micros; BTCUSDT and ETHUSDT perpetuals and spot); which sources the source guide names first (candidates in `BACKLOG.md`); and which import presets you need first (the platforms whose exports you use).

## Kickoff

```text
/phase-kickoff 1 — Read docs/masterplan/phases/P01-market-data.md, docs/masterplan/02-engine-and-data.md §1, docs/adr/0018-own-data-sources-no-shipped-data.md, and docs/masterplan/appendix/research-market-data.md. Ask me the open decisions above, inspect the Databento files I point you at (schemas, date ranges, sizes) without copying them anywhere, research the candidate sources for the source guide (what each offers, its cost, its terms for personal use; the backlog names them), reconcile the steps below with what exists in the repo after Phase 0 and with D-37, and open the kickoff PR with any step amendments, the source research as docs/masterplan/appendix/research-data-sources.md, and a data inventory under docs/data-inventory.md (paths and ranges only, no data).
```

## Steps

### 1.1 Canonical schemas, units, partitions, manifests, snapshot hashes

Depends on: 0.8 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

Every later component reads one layout. Decided once, documented in an ADR, enforced by Pydantic and Arrow schemas.

#### Prerequisites

- Phase 0 complete; the data inventory from the kickoff.

#### Prompt

```text
Masterplan step 1.1 — Canonical schemas, units, partitions, manifests, snapshot hashes.

Read docs/masterplan/02-engine-and-data.md §1.1–1.2 and docs/adr/. Define the canonical on-disk store in `python/fefat/src/fefat/market/schema.py`: Arrow schemas for trades, tbbo, bars (any timeframe), definitions, statistics, funding, and the partition layout `data/<provider>/<schema>/root=…/contract=…/date=…`. Prices are int64 in 1e-9 units; timestamps are int64 nanoseconds UTC with both ts_recv and ts_event; the engine clock is ts_recv. Write `python/fefat/src/fefat/market/store.py` with a `Store` class that resolves `FEFAT_DATA_DIR`, lists partitions, reads them lazily with Polars, writes them atomically (temp file then rename), and maintains `data/raw/MANIFEST.json` (sha256, size, vendor version, download date) for immutable raw files.

Define `Snapshot`: a content-hashed list of partition paths and hashes for a (root, schema, range) request, so a backtest can pin exactly what it read. Record the decisions as an ADR.

Tests use `fixtures/synthetic/` only. Not in this step: importers, bars, calendars.
```

#### Done means

1. Schemas round-trip: writing the synthetic fixtures through `Store` and reading them back yields identical frames (test).
2. A `Snapshot` for the same request is byte-identical across two runs, and changes when one partition's bytes change (test).
3. The ADR explains units, clock, and partitioning, and `02-engine-and-data.md` is consistent with it (amend the doc if the implementation deviated, with a note).

#### Your checks

- In a notebook: `from fefat.market import Store; Store().list_partitions()` prints the synthetic fixtures with their sizes.

#### If it fails

- If Polars refuses the int64 nanosecond timestamps as Datetime: keep raw int64 columns in the store and convert to Datetime only in views.

### 1.2 Instruments, contract identity, fee tables

Depends on: 1.1 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

A contract is identified correctly across decades, with its tick size, point value, expiry, and the fees a run should charge.

#### Prerequisites

- Step 1.1 merged.

#### Prompt

```text
Masterplan step 1.2 — Instruments, contract identity, fee tables.

Read docs/masterplan/02-engine-and-data.md §1.2. Implement `python/fefat/src/fefat/market/instruments.py`: an `Instrument` model (root, kind futures|perp|spot, tick size, point value, lot step, currency, calendar id, valid_from/valid_to) and a `Contract` model (root, expiry year-month, first/last trade date, raw symbols seen) resolved from Databento definition records by instrument_id per day, never from the raw symbol alone. Seed a static table for ES, NQ, CL, GC, MES, MNQ, MCL, MGC and for BTCUSDT/ETHUSDT perpetual and spot, with sources in comments.

Implement dated fee tables (`python/fefat/src/fefat/market/fees.py`): per-contract per-side futures fees for a generic retail broker and placeholders for prop-firm fee tables; crypto maker/taker basis points. A run config names one table.

Tests: resolution of a reused symbol (ESZ6 in 2016 and 2026) yields two different contracts from synthetic definition records; fee lookup by date picks the right version.

Not in this step: calendars, importers.
```

#### Done means

1. Tests for symbol reuse, metadata validity windows, and fee-by-date pass.
2. `ff.instruments.get("ES")` returns the model with tick size 0.25 and point value 50; `MES` has point value 5.
3. The static table documents its sources.

#### Your checks

- In a notebook: `ff.instruments.get("NQ").tick_size` prints `0.25`; `ff.fees.lookup("retail-default", "ES", date)` prints a per-side fee.

#### If it fails

- If Databento definitions are not in your inventory, the resolver must still work from the static table and flag "no definitions loaded"; buy or download definitions later (they are cheap).

### 1.3 Session calendar and trade date

Depends on: 1.2 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Trade dates, session opens and closes, holidays, and daylight-saving shifts are right, because every bar, roll, and prop rule depends on them.

#### Prerequisites

- Step 1.2 merged.

#### Prompt

```text
Masterplan step 1.3 — Session calendar and trade date.

Read docs/masterplan/02-engine-and-data.md §1.3 and the calendar pitfalls in docs/masterplan/appendix/research-market-data.md §5. Implement `python/fefat/src/fefat/market/calendar.py`: an explicit session table per product group (CME equity index, CME energy, CME metals, crypto 24x7, plus a generic calendar defined by a time zone, daily open and close, weekdays, and an optional holiday list, for products traders import in 1.10) giving, for each trade date, the open and close as UTC instants, built from IANA time zones (America/Chicago) and a holiday table (use exchange-calendars where it covers CME Globex, with an override file for the differences). Trade date is assigned by session membership, not clock arithmetic; holiday sessions fold into the next trade date as CME does.

Add `validate_calendar(store)` that compares the table with observed first and last prints per day in the data and reports mismatches.

Golden tests: a daylight-saving spring-forward week, a Sunday open, Thanksgiving week, Juneteenth 2026 (Thursday expiry), and a crypto UTC day; expected UTC instants hand-computed in the test file with the reasoning in comments.

Not in this step: bars, rolls.
```

#### Done means

1. Golden tests pass, with hand-computed expectations and reasoning in the test file.
2. `validate_calendar` reports zero mismatches on the synthetic fixtures and, when you run it on real data, lists any mismatch with the date and the observed times.
3. The session table is cached on disk and rebuilt when the holiday file changes.

#### Your checks

- In a notebook, run `validate_calendar` on one month of your real ES data and read the report: no mismatches, or mismatches you can explain (a half-day holiday, for example).

#### If it fails

- Mismatches on half-day sessions mean the holiday table lacks early closes; add them to the override file with a source link.

### 1.4 Crypto importer

Depends on: 1.1 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Free, complete history for the pairs you trade from the first source you connect, so the engine can be exercised on real data before any Databento spend.

#### Prerequisites

- Step 1.1 merged; the venue decision from the kickoff.

#### Prompt

```text
Masterplan step 1.4 — Crypto importer.

Read docs/masterplan/appendix/research-market-data.md §4. Implement `fefat data import binance` (CLI in python/fefat_app/src/fefat_app/cli.py calling python/fefat/src/fefat/market/importers/binance.py): download monthly archives from data.binance.vision for chosen symbols and ranges (spot klines down to 1s, USD-M perpetual klines, aggTrades, funding rates, open interest), verify the checksums, keep the zips under data/raw/ with manifest entries, and write canonical partitions (trades from aggTrades, bars, funding). Idempotent: re-running skips what exists; resumable after a network failure. Rate-limited and polite.

Design the importer around the `Provider` interface of `python/fefat/src/fefat/market/sources/` (`describe()`: what the source offers, its cost, and its terms; `fetch(symbol, schema, range)`; a cost preview where downloads cost money), which the Databento importer (1.6) and the source guide and sync (1.9) share, so Bybit, Kraken, and Hyperliquid can be added as providers later. Implement Binance now; if the kickoff established that you are US-based (Binance and Bybit block US users), implement Kraken's quarterly archive (OHLCVT bars and trades) as the first provider instead, and Binance second. Record the data terms (non-commercial) in the dataset metadata.

Tests run offline against two tiny committed sample archives generated by scripts/gen_fixtures.py in the provider's exact CSV layout.

Not in this step: Databento, bars from trades (1.5), the remaining venues.
```

#### Done means

1. Offline tests cover checksum verification, idempotent re-run, and resume.
2. A real run for one symbol-month of perpetual aggTrades plus klines plus funding completes and appears in `Store().list_partitions()` with manifest entries.
3. The dataset metadata records provider, range, and licence scope.

#### Your checks

- Run `fefat data import binance --symbol BTCUSDT --market um --from 2024-01 --to 2024-01` and then, in a notebook, load January 2024 1-minute bars and plot the close with Polars + a quick chart: it looks like BTC in January 2024.

#### If it fails

- 403 or geo-block: you are in a restricted region; implement the Kraken provider in this step instead (the Provider interface keeps it small) and record it in the PR.

#### Amendment

2026-10-12 (D-37): the crypto archive is the first source a trader connects, not platform data, and its `Provider` interface is the one seam for every source (1.6, 1.9).

### 1.5 Bar builder

Depends on: 1.3, 1.4 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

Bars of any timeframe are built from trades with one convention, and they match the vendor's own bars exactly, which proves the convention.

#### Prerequisites

- Steps 1.3 and 1.4 merged.

#### Prompt

```text
Masterplan step 1.5 — Bar builder.

Read docs/masterplan/02-engine-and-data.md §1.4. Implement `python/fefat/src/fefat/market/bars.py`: build bars of a given timeframe from trades using Polars, bucketing by ts_recv into [t, t+Δ) anchored at the session open from the calendar, storing sparse bars with ts_open and an explicit ts_close plus volume, trade count, and VWAP; and build a dense session-grid view with zero-volume bars flagged for signal use. Daily bars follow the trade date. Resampling from finer bars must give the same result as building from trades.

Tests: on synthetic fixtures, bars built from trades equal the fixture's 1-second and 1-minute bars; on real data, a `verify_bars(store, root, date)` command compares rebuilt 1-second and 1-minute bars with the vendor bars (Databento OHLCV or Binance klines) and reports differences.

Not in this step: rolls, continuous series.
```

#### Done means

1. Synthetic equality tests pass for 1-second, 1-minute, 5-minute, and daily bars.
2. `verify_bars` on one real Databento day and one real Binance day reports zero differences (or differences explained in the PR, such as the vendor's handling of the session open).
3. Building 5 years of 1-minute bars for one root from 1-second bars takes under a minute on this PC (timed in the PR).

#### Your checks

- In a notebook: build 5-minute ES bars for one day from your real trades and compare the day's high and low with your charting platform.

#### If it fails

- Off-by-one-bar differences usually mean a bar-open versus bar-close labelling mismatch; the convention is ts_open with an explicit ts_close, and the vendor's `ts_event` is the bar open.

### 1.6 Databento importer with cost preview

Depends on: 1.2 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

Your Databento account is one connected source among others: your existing files are imported, and any further download is priced before a cent is spent.

#### Prerequisites

- Step 1.2 merged; your Databento file inventory; a Databento API key if you will download (this step adds the `fefat secrets` command that stores it).

#### Prompt

```text
Masterplan step 1.6 — Databento importer with cost preview.

Read docs/masterplan/02-engine-and-data.md §1.1–1.2 and docs/masterplan/appendix/research-market-data.md §2. Implement `fefat data import databento`, as a `Provider` of `fefat.market.sources` (1.4): (a) `--from-files <folder>` ingests existing DBN (.dbn, .dbn.zst) and Databento CSV/Parquet exports with the official `databento` Python client, keeping the originals immutable under data/raw/ with manifest entries, and writing canonical partitions for trades, tbbo, ohlcv-1s/1m/1d, definitions, and statistics; (b) `--download` builds a request for a dataset/schema/symbols/range, calls `metadata.get_cost` and `get_record_count`, prints the cost and size, and proceeds only after an explicit `--yes` (the CLI must never download without it). Store the API key through the credential store, never in files or logs.

Support continuous symbology (`ES.v.0` etc.) for discovery only; stored data is always per contract, resolved by instrument_id. Assert ts_recv is non-decreasing within each file and record any violation.

The credential store does not exist yet: add `python/fefat_app/src/fefat_app/credentials.py` (a thin layer over `keyring`, backed by the Windows credential store) and a `fefat secrets set|get|list` CLI that never prints secret values; Phase 4 reuses this module unchanged.

Tests: offline, on a small DBN fixture generated with the dbn library in scripts/gen_fixtures.py; a test that the key never lands on disk in plaintext.

Not in this step: bars, rolls, live data.
```

#### Done means

1. Your existing files are imported; `Store().list_partitions()` shows them with manifest entries, and the PR lists what was imported (schemas and ranges, no data).
2. The cost preview prints dollars and megabytes for a sample request and refuses to download without `--yes` (test with a mocked client).
3. The API key never appears in logs, config, or the repo (grep in the PR).

#### Your checks

- Run `fefat data import databento --download --dataset GLBX.MDP3 --schema trades --symbols ES.v.0 --start 2025-01-02 --end 2025-01-03` without `--yes`: it prints a cost and stops.

#### If it fails

- DBN version mismatch on old files: the client upgrades on read; if it refuses, pin the `databento` package version noted in the error and record it in the manifest.

#### Amendment

2026-10-12 (D-37): Databento is one connector among the sources a trader connects with their own account; the importer implements the `Provider` interface of 1.4.

### 1.7 Rolls and forward-anchored continuous series

Depends on: 1.5, 1.6 · Plan mode: required · Reviews: step-reviewer, leakage-auditor, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Signals are computed on a continuous series that never uses tomorrow's information and never rewrites yesterday, while execution always happens on the real contract.

#### Prerequisites

- Steps 1.5 and 1.6 merged; at least two consecutive ES contracts in your data.

#### Prompt

```text
Masterplan step 1.7 — Rolls and forward-anchored continuous series.

Read docs/masterplan/02-engine-and-data.md §1.5 and docs/adr/ (the forward-anchoring decision). Implement `python/fefat/src/fefat/market/continuous.py`: a roll calendar per root computed from per-contract volume through session d−1 and effective at the open of session d (default rule: volume, no roll-back, forced before expiry; open-interest and calendar rules as options), and continuous signal bars that are forward-anchored: history never changes at a roll; the new contract is shifted to join the old series. Columns: close (and open/high/low) adjusted, close_raw, adj_offset, contract, roll_flag. Provide `to_raw_price(level, at)` for price-level signals and a back-adjusted view for display only.

Tests: (1) look-ahead: removing all data after date T does not change any roll decision or any adjusted value on or before T; (2) the roll dates for ES match Databento's ES.v.0 mapping on your real data within the documented convention (session open vs UTC midnight), with differences listed; (3) adjusted differences equal raw differences within a contract; (4) a position held across a roll (engine comes later) has the gap recorded for transfer.

Not in this step: the engine's roll handling (2.9), charts.
```

#### Done means

1. The look-ahead test and the within-contract difference test pass on synthetic data.
2. The ES.v.0 comparison on real data passes or lists explained differences.
3. The ADR is linked and the module docstring explains why forward anchoring was chosen.

#### Your checks

- In a notebook: plot one year of continuous ES close, `close_raw`, and `adj_offset`; the offset steps at roll dates and the adjusted series is continuous across them.

#### If it fails

- If roll dates differ from Databento by exactly one session, the comparison is using the wrong boundary (UTC midnight versus session open); the convention is session open, document the mapping.

### 1.8 Data-quality report and SDK data API

Depends on: 1.7 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

You can trust the data because every dataset has a report, and you can load anything with one call.

#### Prerequisites

- Step 1.7 merged.

#### Prompt

```text
Masterplan step 1.8 — Data-quality report and SDK data API.

Implement `python/fefat/src/fefat/market/quality.py`: per dataset and per day, gaps versus the calendar, duplicate records, out-of-session prints, non-monotonic ts_recv, zero or negative prices (except where allowed, e.g. CL in April 2020), bar-versus-tick reconciliation, and coverage by fidelity (tick, 1s, 1m) per day. Output a Parquet report plus a Markdown summary under data/reports/.

Implement the SDK data API in `python/fefat/src/fefat/market/api.py`: `ff.market.load(root_or_symbol, timeframe, start, end, continuous=True|False, fidelity="auto")` returning a Polars LazyFrame with the signal-bar schema, `ff.market.catalog()` listing datasets with coverage and quality status, and a `fefat data catalog` CLI. Document the API in the module docstring with examples.

Not in this step: the web catalog page (5.4).
```

#### Done means

1. The quality report on synthetic fixtures finds the planted anomalies (the generator plants a gap, a duplicate, and an out-of-session print) and nothing else.
2. `ff.market.load("ES", "5m", "2024-01-01", "2024-03-31")` returns bars with the documented columns in under 2 seconds warm.
3. `fefat data catalog` prints every dataset with its range, fidelity coverage, and quality status.

#### Your checks

- Run `fefat data catalog`; then in a notebook open the Markdown report for ES and read the coverage table: it matches what you bought.

#### If it fails

- Reports of "out-of-session prints" on real data often point at the calendar (holiday early closes); fix the override file, not the data.

### 1.9 Product catalog, data sources, and managed sync

Depends on: 1.8 · Plan mode: required · Reviews: step-reviewer, engine-accuracy-reviewer · Security: yes · Model hint: hard

#### Purpose

FEFAT ships know-how, not data: a catalog of curated products with their specifications, calendars, roll rules, and recommended sources; a guide to well-known data sources; and a sync that keeps each product complete, checked, and current through the sources the trader connects with their own accounts.

#### Prerequisites

- Step 1.8 merged; the catalog product list and the first sources from the kickoff; your Databento key stored with `fefat secrets` if futures data will be downloaded.

#### Prompt

```text
Masterplan step 1.9 — Product catalog, data sources, and managed sync.

Read docs/masterplan/02-engine-and-data.md §1.8, docs/masterplan/00-product-spec.md §2.5, and docs/adr/0018-own-data-sources-no-shipped-data.md. Implement the product catalog in `python/fefat/src/fefat/market/catalog/`: a versioned `catalog.yaml` listing the curated products (from the kickoff; by default ES, NQ, CL, GC and their micros, and BTCUSDT and ETHUSDT spot and perpetuals), each with its instrument specification, calendar, roll rule, schemas, history depth, update cadence, and the sources that can supply it, in order of recommendation. Implement the source guide in `fefat/market/sources/`: a registry of the known sources, connectors (1.4, 1.6) and file presets (1.10) alike, each describing what it offers, its cost, and the terms a trader accepts for personal use, written from docs/masterplan/appendix/research-market-data.md and the kickoff's research. `fefat data sources` prints the guide with each source's connection state; `fefat data connect <source>` stores a source's key through the credential store and checks it.

Add `fefat data status` (each catalog product's coverage, last update, quality, and the source it came from) and `fefat data sync [--product …] [--source …]`, which brings products up to date through the trader's connected sources (every Databento download shows the cost preview and needs `--yes`), rebuilds bars and continuous series for the new range, runs the quality report, and records the catalog version on the datasets. Datasets carry `origin: sync | import`, their `provider`, and the licence scope the source's terms give the trader; `ff.market.catalog()` shows them, and `ff.market.load` takes an optional `origin` or `provider` where several datasets cover a product. Adding a vendor later means adding one `Provider`; nothing in FEFAT ever serves data to another machine.

Tests: an offline end-to-end sync of a synthetic catalog product (fixtures stand in for vendor files); a re-sync is a no-op; an interrupted sync resumes; the cost-preview gate is respected; the source guide lists every registered provider and preset with its terms.

Not in this step: importing your own files (1.10), the web pages (Phase 5), the signed catalog updates of Phase 14.
```

#### Done means

1. `fefat data sync` on the synthetic product produces bars, continuous series, and a quality report, tagged `origin: sync` with its provider and the catalog version.
2. Re-running is a no-op, and an interrupted sync completes when re-run (tests).
3. `fefat data sources` lists every source with what it offers, its terms, and whether it is connected; `fefat data status` lists every catalog product with its coverage, last update, quality, and source.

#### Your checks

- Run `fefat data sources`, connect the crypto archive (no key needed), run `fefat data status`, sync one crypto product, then run status again: the product shows as up to date with a quality "pass".

#### If it fails

- A futures product shows a download cost you did not expect: stop; the sync must never download without your `--yes`. Shorten the history in the catalog or buy the month of Databento Standard first (`07-tools-and-costs.md` §3).

#### Amendment

2026-10-12 (D-37): FEFAT no longer provides "platform data" or plans to deliver data to customers; traders connect their own sources, and FEFAT provides the catalog, the connectors and presets, the source guide, and sync. The step was renamed from "Platform data catalog and managed updates"; `PlatformDataSource` and its hosted swap are gone, the `Provider` interface of 1.4 is the seam for every source, `source: platform | user` became `origin: sync | import` with a `provider`, and the commands lost the word platform.

### 1.10 Import your own market data

Depends on: 1.9 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: default

#### Purpose

Traders can bring data for any product — files from their own data vendor or trading platform — mapped into the same canonical store, validated, and used exactly like data a connector synced.

#### Prerequisites

- Step 1.9 merged; one of your own files to try (for example a CSV export of 1-minute bars from your charting platform).

#### Prompt

```text
Masterplan step 1.10 — Import your own market data.

Read docs/masterplan/02-engine-and-data.md §1.8. Implement `fefat data import file <path> --profile <name>`: a generic importer for bar and tick files (CSV, TSV, Parquet; zipped or gzipped) driven by import profiles of kind `market_data` — column mapping (timestamp; open, high, low, close, volume; or price, size, side), timestamp format and time zone, whether timestamps mark the bar open or the bar close, price scaling, the timeframe (ticks, or bars of any timeframe; bars coarser than 1 minute are accepted, and backtests on them fill at that coarser fidelity), the series type (per contract with contract codes, or a continuous series, unadjusted or back-adjusted; continuous series run as one synthetic contract with roll handling off and a warning on every run that uses them), and the instrument (an existing one, or a new specification with tick size, point value, currency, and calendar — one of the built-in calendars or the generic one from 1.3 — entered once and saved). Profiles are saved and reusable. Ship presets for common exports (Databento CSV, NinjaTrader, Sierra Chart, TradeStation, TradingView, plus those chosen at the kickoff), each an entry of the source guide (1.9), documented, and tested against a small synthetic sample in its exact layout. `--preview` prints the first rows as they would be stored and the problems detected, and writes nothing.

Imported data lands in the canonical store tagged `origin: import` with the preset as its provider, keeps the original file under `data/raw/user/` with a manifest entry, goes through bar building (for ticks), the calendar check, and the quality report, and is never uploaded anywhere. Where imported and synced data overlap, both are kept as separate datasets.

Tests: each preset imports its sample to the expected canonical frame; a sample with a wrong time zone or bar stamping is flagged by the calendar check with the offset it detected; a 5-minute bar file and a continuous back-adjusted futures file import with the right fidelity and warnings; a new instrument on the generic calendar loads; preview writes nothing; a re-import is idempotent.

Not in this step: the import wizard in the app (5.12), trade logs (Phase 7), alternative non-price data (Phase 10).
```

#### Done means

1. Every preset imports its synthetic sample, and the result equals the expected canonical frame (tests).
2. A sample with shifted time zones is flagged by the calendar check, with the offset it detected.
3. `ff.market.load("<new product>", "5m", start, end, origin="import")` works for a product with a new instrument specification.

#### Your checks

- Export a few days of 1-minute bars for any product from your charting platform, run `fefat data import file <file> --profile <closest preset> --preview`, read the preview, then import it and open its quality report.

#### If it fails

- Off-by-one-bar or off-by-hours timestamps are the usual problem: check whether your export stamps bars at the open or the close, and in which time zone, and set both in the profile; the calendar check tells you when they are wrong.

#### Amendment

2026-10-12 (D-37): the vocabulary changed (`origin: import` with a `provider` instead of `source: user`; synced data instead of platform data), and each preset is an entry of the source guide of 1.9.

### 1.11 Notebook demo and phase exit prep

Depends on: 1.10 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

A notebook you can rerun any time shows the whole data layer working on your real data, and documents how to use it.

#### Prerequisites

- Step 1.10 merged.

#### Prompt

```text
Masterplan step 1.11 — Notebook demo.

Write `notebooks/01-market-data.ipynb`: the source guide with your connected sources and the catalog status, load continuous ES 5-minute bars for a year, show the roll dates and the adj_offset steps, load one real day of ticks and rebuild its 1-minute bars, compare with the vendor bars, load BTCUSDT perpetual 1-minute bars with funding, load one dataset you imported yourself, and show the quality summary. Every cell has a one-line explanation; expected outputs are described in markdown cells (no data is committed; the notebook runs against FEFAT_DATA_DIR). Add `docs/data-guide.md` explaining the store layout, units, calendars, rolls, the source guide, how to connect a source and how sync keeps a product current, and how to import your own data (profiles and presets), written for you.

Not in this step: anything else.
```

#### Done means

1. The notebook runs top to bottom on your machine without edits.
2. `docs/data-guide.md` answers: where is my data, which sources are suggested and how do I connect one, how does sync keep a product current, how do I import my own data, how do I check quality.

#### Your checks

- Run the notebook. The vendor-bar comparison cell prints zero differences.

#### If it fails

- A cell fails on a missing dataset: the notebook should detect what is in the catalog and skip with a message; ask Claude Code to make it robust rather than editing paths by hand.

#### Amendment

2026-10-12 (D-37): the notebook and the data guide show the source guide and connected sources instead of platform data.

## Phase exit

```text
/phase-exit 1 — Run the exit procedure from docs/masterplan/05-build-process.md §6 for Phase 1: full suite from a clean clone; leakage-auditor and engine-accuracy-reviewer over the phase diff; /security-review (the importer handles a secret); demo script = notebooks/01-market-data.ipynb; retro of repeated corrections into CLAUDE.md or rules; backlog groomed; tag phase-1.
```
