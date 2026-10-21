# Phase 1 — Market data

**Goal.** One clean, documented, hash-pinned store on disk with correct session calendars, bars rebuilt and verified, continuous futures series built without look-ahead, and a quality report for every dataset, filled from the files you feed it: Databento batch downloads and exports, and files from any vendor or trading platform through import presets (no connector and no sync in Phase 1, D-38). FEFAT ships no market data (D-37); it ships the product catalog (specifications, calendars, roll rules, quality rules, a recommended source per product), the import presets, and a guide to well-known sources.

**You get.** `ff.market.load("MES", "5m", "2024-01-01", "2024-12-31")` in a notebook returns correct bars; `fefat data import databento <folder>` and `fefat data import file <path> --profile <name>` bring in your files, and running them again imports nothing twice; `fefat data sources` lists the known sources with what they offer, their cost and terms, and the preset that reads their files; `fefat data status` shows every catalog product with its coverage and quality.

**Depends on.** Phase 0.

**Kickoff (2026-10-12, pull request #10, D-38).** Your data is two Databento batch downloads of 1-minute bars for every MCL, MGC, MES, and MNQ contract (`docs/data-inventory.md`); `FEFAT_DATA_DIR` keeps its default; no purchase is planned, and any later purchase arrives as files. No connector and no sync in Phase 1: step 1.4 is skipped, 1.6 is a file importer, and 1.9 keeps the catalog, the source guide, and `fefat data status`. The catalog is MES, MNQ, MCL, and MGC; the presets are Databento CSV, IBKR (TWS API bars), NinjaTrader, and TradingView first. The source research is `appendix/research-data-sources.md`. Conventions for every step of the phase: Polars 2 (D-36), so a frame a test compares or a run reads is sorted explicitly, never left in engine order; `Store` takes its folder as an argument, and an autouse fixture keeps `FEFAT_HOME` and `FEFAT_DATA_DIR` out of the tests; a new dependency goes in with `uv add` and a decision entry like D-31; real data is read by path and never enters the repository; fixtures change only through `scripts/gen_fixtures.py`, regenerated with their manifest. The commit guard's plain-text extensions and the per-commit guard arrive in their own `config/data-guard-text-and-push` pull request before step 1.10 (`BACKLOG.md`).

**Open decisions for the kickoff** (settled 2026-10-12, D-38)**.** Which Databento files you already have (schemas, products, date ranges) and where they are; whether to buy one month of Standard now (`07-tools-and-costs.md` §3); which crypto venue (Binance by default; Kraken/Coinbase/Hyperliquid if you are US-based); the catalog product list (default ES, NQ, CL, GC and their micros; BTCUSDT and ETHUSDT perpetuals and spot); which sources the source guide names first (candidates in `BACKLOG.md`); and which import presets you need first (the platforms whose exports you use).

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

- Phase 0 complete; the data inventory from the kickoff (`docs/data-inventory.md`).

#### Prompt

```text
Masterplan step 1.1 — Canonical schemas, units, partitions, manifests, snapshot hashes.

Read docs/masterplan/02-engine-and-data.md §1.1–1.2 and docs/adr/. Define the canonical on-disk store in `python/fefat/src/fefat/market/schema.py`: Arrow schemas for trades, tbbo, bars (any timeframe), definitions, statistics, funding, and the partition layout `data/<provider>/<schema>/root=…/contract=…/date=…`. Prices are int64 in 1e-9 units; timestamps are int64 nanoseconds UTC with both ts_recv and ts_event; the engine clock is ts_recv. Write `python/fefat/src/fefat/market/store.py` with a `Store` class that takes its folder (the app and notebooks pass `fefat.config.resolve_paths(os.environ).data_dir`), lists partitions, reads them lazily with Polars, writes them atomically (temp file then rename), and maintains `data/raw/MANIFEST.json` (sha256, size, vendor version and job id, download date) for immutable raw files.

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

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): `fefat.config.resolve_paths` exists since step 0.5, so `Store` takes its folder as an argument, and an autouse pytest fixture clears `FEFAT_HOME` and `FEFAT_DATA_DIR`, so that no test can read real data. The schemas start from the fixtures of step 0.5, which already follow the layout with `fixtures/synthetic/` as the provider folder `synthetic` (`scripts/gen_fixtures.py`: trades with `ts_recv`, `ts_event`, `instrument_id`, `price`, `size`, `side`, and `sequence`; bars with `ts_open`, `ts_close`, `instrument_id`, open, high, low, close, `volume`, and `trade_count`; 1-minute bars per `month=`, as `02-engine-and-data.md` §1.1 partitions them), and add what the Phase 0 exit reviews asked for: `trade_date` on every bar schema, assigned by the session table of 1.3 (a date taken from `ts_open` puts the first hour of a CME session on the wrong day); the size unit in each dataset's metadata (the BTC fixture's `size` is lots of 0.001 BTC); and, on settlement statistics, the vendor's reference time beside the receive time, which is the availability column. The raw manifest also records the vendor's job id and published hash, which the batch downloads on this PC carry in their `manifest.json`. Polars is 2.0.0 (D-36): every frame a test compares is sorted explicitly. The dependencies this step adds (`pydantic`, and `pyarrow` in the SDK if the writer needs it) get a decision entry like D-31.

2026-10-12, while doing the step: the schemas are Polars schemas, whose types are Arrow's, so the SDK reads and writes Parquet without pyarrow; pydantic joined the SDK (D-39), and the store's decisions are ADR-0019 (D-40). The code is split by job into `fefat.market.schema` (columns and units), `layout` (paths and requests), `snapshot`, `raw_manifest`, and `store`, rather than all in `schema.py`, to keep each module under the size limit. The tests point `FEFAT_HOME` and `FEFAT_DATA_DIR` into a temporary folder, before collection and again for each test, rather than clearing them, which would name the default folder where the real data lives. Since `Store` takes its folder, Your checks reads `Store(Path("fixtures")).list_partitions()` from the repository root, or `Store(Path("..") / "fixtures")` from `notebooks/`. The step's reviews added: reads keep the bars of a request's dates and leave definitions, statistics, and funding whole, for the load API (1.8) to cut at `ts_recv`; a snapshot also pins the dataset's `dataset.json` and its request, and `Store.read` reads exactly what a snapshot pinned; a bar outside its partition's trade date or month is refused; statistics keep `stat_flags`; and `ohlcv-1d` holds session bars, so the Databento importer (1.6) skips the vendor's UTC-day daily bars.

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

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): the files on this PC hold no definition records, but each Databento batch file carries its symbology in the DBN metadata: child raw symbol to `instrument_id` by date interval, 1,913 children for MCL, MGC, and MES and 167 for MNQ, outrights, calendar spreads, and strategy symbols alike, resolved from the parents `MCL.FUT`, `MGC.FUT`, `MES.FUT`, and `MNQ.FUT` (`docs/data-inventory.md`). The resolver builds contract identity from definition records where they exist, else from the DBN metadata mappings of the imported files, else from the static table, and records which; a reused symbol is still resolved by `instrument_id` and date. Spread and strategy symbols (`MCLF2-MCLG2`, `MCL:SA 03M F2`) are recognised and skipped at import (1.6) with a count, never stored as contracts. The static table carries each product's first trade date with its source: the data starts there, not at the dataset's 2010-06-06 start.

2026-10-13, while doing the step: the code is split by job into `fefat.market.instruments` (the specifications and the static table), `contracts` (identity), and `fees`, rather than all in `instruments.py`, to keep each module under the size limit. A contract records the source of its identity, and a definition answers only while its contract is alive. The placeholders for prop-firm fee tables became one sourced table, `prop-topstep`, from Topstep's published rate card, and the other firms' tables arrive with their rule sets; `retail-default` is priced as NinjaTrader's free plan, and tests check both against the all-in figures their sources publish. The tables start in 2026, when their sources were read, so a date before a table's first schedule is refused; how a run prices earlier years is decided with the engine's costs (2.9, `BACKLOG.md`). `ff.fees.lookup` returns a fee whose `per_contract_side` is the per-side fee of Your checks.

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

- In a notebook, run `validate_calendar` on one month each of your real MES, MCL, and MGC bars and read the reports: no mismatches, or mismatches you can explain (a half-day holiday, for example).

#### If it fails

- Mismatches on half-day sessions mean the holiday table lacks early closes; add them to the override file with a source link.

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): the real data on this PC is 1-minute bars (`docs/data-inventory.md`), so `validate_calendar` compares the table with the first and last bar of each day (`ts_open` of the first, `ts_close` of the last) as well as with prints where ticks exist, and Your checks cover the equity-index, energy, and metals calendars with MES, MCL, and MGC. From the Phase 0 exit reviews: the session close is the local close time (16:00 Chicago, or the early close the holiday table gives), never the open plus 23 hours, which `scripts/gen_fixtures.py` uses today and this step corrects, regenerating the fixtures with their manifest.

2026-10-13, while doing the step (D-41): the holiday table is CME's holiday rules written in code with a source on each, and the override file is the table `OVERRIDES` in `fefat.market.builtin_calendars`, rather than exchange-calendars, whose CME calendar gives a Monday holiday its own trade date and one set of hours to every group; Polars converts the local times, so no dependency was added and `tzdata` stays a development tool. The code is split by job into `fefat.market.calendar`, `builtin_calendars`, and `calendar_check`, and `validate_calendar` takes the cache folder beside the store (`resolve_paths(os.environ).cache_dir`, new here). A halt day's trading carries the next trade date in every year, the date CME Clearing used and Globex uses for Friday holidays since 2026-06-19; halt times never bound a session, so the table holds full closes, halt days, and early closes only, and an early close must fall inside its session. The rules are CME's 2024 to 2026 schedules, read from brokers' copies of its notices because cmegroup.com refuses scripted reads; the goldens add Christmas Eve 2025 and Good Friday 2026 to the five the prompt names. The real bars on this PC are DBN files that only step 1.6 imports, so the real-data half of Done means 2 and Your checks run at the end of 1.6, which lists the mismatches in its pull request and turns those a holiday explains into override rows. The fixtures' sessions now close at the local close, and their labels became `ESH2026` and `BTCUSDT-PERP` (`BACKLOG.md`); the ES files kept their bytes.

2026-10-21 (Phase 1 exit, D-50): since step 1.5 planted a print 400 ms after the 03-06 close in the fixtures, the fixture check reports that print as three explained mismatches rather than zero, and `test_market_calendar_check.py` asserts them. MGC's real bars of every year since 2010 settled the day after Thanksgiving for energy and metals, 12:45 through 2023 and 13:45 from 2024, as a rule with the brokers' notices of 2016, 2017, 2021, and 2022 as its source, in place of the 13:45 rule and its four override rows.

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

2026-10-12 (Phase 1 kickoff, D-38): skipped. No connector is built in Phase 1, since the data layer takes only the files you feed it, and no crypto files exist on this PC. The Binance Vision archive layout the kickoff researched (`appendix/research-data-sources.md`: spot klines without a header row and futures klines with one, spot timestamps in microseconds since 2025-01-01, an inclusive `close_time`, `.CHECKSUM` files) returns as an import preset of 1.10's kind when you feed such files, and the connector itself stays in `BACKLOG.md` with the `Provider` seam.

### 1.5 Bar builder

Depends on: 1.3 · Plan mode: optional · Reviews: step-reviewer, engine-accuracy-reviewer · Security: no · Model hint: default

#### Purpose

Bars of any timeframe are built from trades with one convention, and they match the vendor's own bars exactly, which proves the convention.

#### Prerequisites

- Step 1.3 merged.

#### Prompt

```text
Masterplan step 1.5 — Bar builder.

Read docs/masterplan/02-engine-and-data.md §1.4. Implement `python/fefat/src/fefat/market/bars.py`: build bars of a given timeframe from trades using Polars, bucketing by ts_recv into [t, t+Δ) anchored at the session open from the calendar, storing sparse bars with ts_open and an explicit ts_close plus volume, trade count, and VWAP; and build a dense session-grid view with zero-volume bars flagged for signal use. Daily bars follow the trade date. Resampling from finer bars must give the same result as building from trades.

Tests: on synthetic fixtures, bars built from trades equal the fixture's 1-second and 1-minute bars; on real data, a `verify_bars(store, root, date)` command compares rebuilt bars with the vendor's at every fidelity the data has (1-minute bars resampled to 5-minute and daily against the vendor's, and 1-second and 1-minute bars rebuilt from trades against Databento's or Binance's where trades exist) and reports differences.

Not in this step: rolls, continuous series.
```

#### Done means

1. Synthetic equality tests pass for 1-second, 1-minute, 5-minute, and daily bars.
2. `verify_bars` on one real day of each product on this PC reports zero differences at the fidelities the data has (or differences explained in the PR, such as the vendor's handling of the session open); the tick-level comparison runs the day a trades file is imported and is noted as pending until then.
3. Resampling the 16 years of real MES 1-minute bars to 5-minute bars takes under a minute on this PC, and building 1-minute bars from the synthetic 1-second bars, scaled to five years, projects under a minute (both timed in the PR).

#### Your checks

- In a notebook: build 5-minute MES bars for one day from your real 1-minute bars and compare the day's high and low with your charting platform.

#### If it fails

- Off-by-one-bar differences usually mean a bar-open versus bar-close labelling mismatch; the convention is ts_open with an explicit ts_close, and the vendor's `ts_event` is the bar open.

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): no trades or 1-second bars exist on this PC and 1.4 is skipped, so the step depends on 1.3 alone, verifies against the vendor at the fidelities the data has, and times what the data allows; the prompt, Done means 2 and 3, and Your checks were reworded. Bars carry `trade_date` (1.1). From the Phase 0 exit reviews: a bar whose close lies after the end of the data is held back and written only when later data completes it; and the fixtures gain a print received exactly on a second boundary, one in the last slot before the close, and one after the close, planted by `scripts/gen_fixtures.py` in this step.

2026-10-13 (step 1.3): the session tables hold no halt windows, so the hours a halt day leaves closed lie inside the next trade date's session: 12:00 to 17:00 CT on a Monday holiday for equity index, and from Friday noon to Sunday 17:00 after a Friday holiday (the session of Monday 2026-06-22 spans 95 hours, 42 of them traded). Before the dense session grid is built, give the calendar its halt windows and leave them out of the grid, so that indicators counting bars, exits counting minutes, and the prop rules never read closed hours as market time (`BACKLOG.md`).

2026-10-14, while doing the step (D-43): the bar convention, `vwap`, and the halt windows are D-43's. The halt times come from the real bars beside the schedules: CME's 2011 Labor Day schedule halts energy and metals at 12:15 and DTN's of 2022 at 13:30, and MES and MNQ have no bar from 15:15 to 15:29 Chicago until trade date 2021-06-25. Trade dating keeps instants inside halts, rather than refusing them as the backlog line proposed, since 11 of the vendor's MES and MNQ bars open at 15:29 on five days of 2020, a minute before the reopen. The print planted after a close keeps its trade date, so step 1.1's snapshot test now holds a read to the rows available before the next session's open, with that one print between the close and it. This PC holds no trades and no 1-second, 5-minute, or daily bars, so `verify_bars` on 2026-09-22 of MES, MNQ, MCL, and MGC reports the comparisons with trades and 1-second bars pending and those with 5-minute and daily bars not available; its resampling check finds no difference, there and over every trade date of the four products.

### 1.6 Databento file importer

Depends on: 1.2 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Your Databento files are imported, batch downloads and exports alike, and any later purchase arrives the same way: as files.

#### Prerequisites

- Step 1.2 merged; your Databento files (`docs/data-inventory.md`).

#### Prompt

```text
Masterplan step 1.6 — Databento file importer.

Read docs/masterplan/02-engine-and-data.md §1.1–1.2, docs/masterplan/appendix/research-market-data.md §2, and docs/data-inventory.md. Implement `fefat data import databento <folder-or-file>` (the CLI in python/fefat_app/src/fefat_app/cli.py calling python/fefat/src/fefat/market/importers/databento.py): it ingests a batch-download folder (the DBN file beside its metadata.json, manifest.json, and condition.json, as on this PC) and single DBN (.dbn, .dbn.zst), CSV, and Parquet exports, decoding DBN with the official `databento-dbn` library (the client's own decoder; the `databento` client and its network code are not needed without a connector). It verifies each file against the vendor's SHA-256 where manifest.json gives one, keeps the originals immutable under data/raw/ with manifest entries (job id, hash, DBN version, the newest last_modified_date of condition.json), stores the per-day conditions for the quality report (1.8), maps instrument_id to contracts through the DBN metadata or the definition records (1.2), skipping spreads with a count, and writes canonical partitions for trades, tbbo, ohlcv-1s/1m/1d, definitions, and statistics, streaming, so that an 873 MB file is never loaded whole. Idempotent: a re-run skips what the manifest already holds. Assert ts_recv is non-decreasing within each file and record any violation.

No network, no key, no download (D-38): a purchase happens on Databento's website and its files come through this command.

Tests: offline, on a small DBN batch folder (a DBN file plus the three JSON sidecars) written by scripts/gen_fixtures.py in the DBN layout under fixtures/synthetic/ with manifest entries; a re-run test; a wrong-hash test.

Not in this step: bars, rolls, downloads, the credential store.
```

#### Done means

1. Your existing files are imported; `Store().list_partitions()` shows them with manifest entries, and the PR lists what was imported (schemas, ranges, contracts per root, and the spreads skipped; no data).
2. A re-run of the same folder imports nothing and says so, and a file whose SHA-256 differs from the vendor's `manifest.json` is refused with both hashes (tests).
3. The per-day conditions of `condition.json` are stored, and the import summary lists the degraded days of `docs/data-inventory.md`.

#### Your checks

- Run `fefat data import databento <the MNQ folder>`, then `Store().list_partitions()` in a notebook: 35 MNQ contracts with 1-minute bars from 2019 to 2026 and the raw file in the manifest; run the command again: nothing to import.

#### If it fails

- DBN version mismatch on old files: the decoder upgrades on read; if it refuses, pin the `databento-dbn` version noted in the error and record it in the manifest.

#### Amendment

2026-10-12 (D-37): Databento is one connector among the sources a trader connects with their own account; the importer implements the `Provider` interface of 1.4.

2026-10-12 (Phase 1 kickoff, D-38): no connector in Phase 1, so the download, the cost preview, the `--yes` gate, the credential store, and `fefat secrets` left this step (`BACKLOG.md`, with the `Provider` seam), its title became "Databento file importer", and Security changed to no. Your files are two uncompressed DBN v3 batch downloads of 2026-09-23 (`docs/data-inventory.md`): `ohlcv-1m` for the parents `MCL.FUT`, `MGC.FUT`, and `MES.FUT` (873 MB, about 15.6 million records) and `MNQ.FUT` (222 MB, about 4.0 million), 2010-06-06 to 2026-09-23, symbols as `instrument_id` with the mapping in the DBN metadata, each beside its `metadata.json` (the query), `manifest.json` (the vendor's SHA-256 of every file), and `condition.json` (per-day `available` or `degraded`; 32 degraded days). The purpose, prerequisites, prompt, Done means, and Your checks were rewritten for them.

2026-10-13 (step 1.3): this step also builds on 1.3's session tables. The importer dates each bar by the session it falls in (`fefat.market.calendar`), but must not stop on a bar outside every session while the holiday rules of the years before 2024 are unchecked: it dates such a bar by the latest session that opened before it and counts these bars per day, so the import completes and the check reports them. Once your files are in, run `validate_calendar(Store(paths.data_dir), paths.cache_dir)` over the MES, MNQ, MCL, and MGC bars, the real-data half of 1.3's Done means 2 and its Your checks: list the mismatches in the pull request, and for each that a holiday explains add a row with its source to `OVERRIDES` in `fefat.market.builtin_calendars`, or give the hours validity windows where a whole era differs (`BACKLOG.md`).

2026-10-13, while doing the step: you chose DBN files only, so Databento's CSV and Parquet exports go through 1.10's Databento preset (`BACKLOG.md`). The decoder is `databento-dbn` 0.72.0, pinned exactly (D-42). The code is split by job into `fefat.market.importers.dbn` (reading), `canonical` (contracts and trade dates), `partition_buffers`, `file_writer`, `report`, and `databento` (the vendor's files), and the `fefat` command is `fefat_app.cli`. Databento's symbology maps six expired MNQ contracts until the end of the query, which named them a decade late, so the importer reads each file twice while streaming, first for the days each instrument has records, and cuts each interval to them before naming contracts (`BACKLOG.md` keeps the resolver's side); the definition-record path is not built, so a file without symbology is refused (`BACKLOG.md`). Every check that the first pass can make (records of the schema, a whole last record, symbology covering every record) refuses a file before anything is written, and a batch split into several DBN files is refused, since its files can share partitions. A single file is kept under `raw/databento/<its SHA-256>/`, since the vendor names files by dates and schema, not by product. The counts the step asks to record (clock decreases, records outside every session, unreliable `ts_recv`) are in the import's summary, which the pull request carries, and the quality report (1.8) keeps them (`BACKLOG.md`). Ticks and bars outside every session take the session before them and are counted, a print received just after the close among them; definitions and statistics are kept whole per contract; the vendor's daily bars are skipped; a file overlapping an imported partition is refused (`BACKLOG.md`). Your MNQ batch holds 35 outrights, of which 34 have bars: MNQZ2027, listed on 2026-09-06, has none yet. The calendar check of the real bars found, with sources, that CME Globex closed equity index, energy, and metals at 16:15 Chicago until trade date 2015-09-21 (calendars now hold former closes), that equity index trades in full on the Thursday before a Saturday Independence Day (2020-07-02 and 2026-07-02, refuting the early close 1.3's test read from a broker's 2026 schedule), and that energy and metals closed at 12:45 on the day after Thanksgiving in 2019, 2020, and 2023 (`OVERRIDES` rows); the calendar's models moved to `fefat.market.calendar_definition` to keep `calendar` under the size limit, and the mismatches left are listed in the pull request and in `BACKLOG.md`.

### 1.7 Rolls and forward-anchored continuous series

Depends on: 1.5, 1.6 · Plan mode: required · Reviews: step-reviewer, leakage-auditor, engine-accuracy-reviewer · Security: no · Model hint: hard

#### Purpose

Signals are computed on a continuous series that never uses tomorrow's information and never rewrites yesterday, while execution always happens on the real contract.

#### Prerequisites

- Steps 1.5 and 1.6 merged; at least two consecutive contracts of one catalog product in your data (every MES, MNQ, MCL, and MGC contract is on this PC).

#### Prompt

```text
Masterplan step 1.7 — Rolls and forward-anchored continuous series.

Read docs/masterplan/02-engine-and-data.md §1.5 and docs/adr/ (the forward-anchoring decision). Implement `python/fefat/src/fefat/market/continuous.py`: a roll calendar per root computed from per-contract volume through session d−1 and effective at the open of session d (default rule: volume, no roll-back, forced before expiry; open-interest and calendar rules as options), and continuous signal bars that are forward-anchored: history never changes at a roll; the new contract is shifted to join the old series. Columns: close (and open/high/low) adjusted, close_raw, adj_offset, contract, roll_flag. Provide `to_raw_price(level, at)` for price-level signals and a back-adjusted view for display only.

Tests: (1) look-ahead: removing all data after date T does not change any roll decision or any adjusted value on or before T; (2) the roll dates for MES match Databento's MES.v.0 mapping on your real data within the documented convention (session open vs UTC midnight), with differences listed, the mapping fetched once by you outside the app (Databento's symbology endpoint is free) and kept under FEFAT_DATA_DIR; (3) adjusted differences equal raw differences within a contract; (4) a position held across a roll (engine comes later) has the gap recorded for transfer.

Not in this step: the engine's roll handling (2.9), charts.
```

#### Done means

1. The look-ahead test and the within-contract difference test pass on synthetic data.
2. The MES.v.0 comparison on real data passes or lists explained differences.
3. The ADR is linked and the module docstring explains why forward anchoring was chosen.

#### Your checks

- In a notebook: plot one year of continuous MES close, `close_raw`, and `adj_offset`; the offset steps at roll dates and the adjusted series is continuous across them.

#### If it fails

- If roll dates differ from Databento by exactly one session, the comparison is using the wrong boundary (UTC midnight versus session open); the convention is session open, document the mapping.

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): the real contracts on this PC are MES, MNQ, MCL, and MGC 1-minute bars since each product's launch (`docs/data-inventory.md`), so the prerequisite, test 2, Done means 2, and Your checks name MES, with the `.v.0` mapping fetched once by you outside the app (no connector in Phase 1). The look-ahead test needs a second ES contract in the fixtures with overlapping sessions and a volume crossover (Phase 0 exit review): this step adds ESM6 to `scripts/gen_fixtures.py`, seeding each tape by contract rather than by root so that the two tapes differ, and regenerates the fixtures with their manifest.

2026-10-15, while doing the step (D-44): the code is split by job into `fefat.market.continuous` (the roll calendar, the continuous bars, and the chart view), `roll_decisions` (each session's decision and each roll's gap), `continuous_check` (the comparison with a vendor's mapping), and `last_trade_rules` (the last trade date of each product's contracts, which the forced roll needs and nothing in the store held), rather than all in `continuous.py`; `Store.scan_contracts` gives bars their contract. The calendar is a row per session rather than a list of roll dates: its rows run from the second session of the bars to the last opening by `received_until`, each front holding until the next session's open, so the engine reads the front of any instant; overlapping bars of a contract and a bar closing after the next open are refused, and only bars with trades count. The reviews moved the gap from each contract's last close before the roll, which can be days apart on a thin month, to the latest bar, the same open and close, both traded in, and `roll_flag` to the bar whose contract differs from the bar before it. On your bars every expired MES, MNQ, and MCL contract ends on its rule's date, and MES and MNQ roll 30 times each, MCL 63, and MGC 80, all on volume, MGC from August straight to December past the thin October contract. The check's chart is inline SVG, so the notebook needs no plotting dependency. Test 2 ran on the vendor's `MES.v.0` mapping, which you fetched on 2026-10-15 (`docs/data-inventory.md`): the fronts agree on 1,843 of 1,860 trade dates. The 17 that differ are each the session after one of the 17 rolls since September 2022, whose crossover came in a Monday session: the vendor's front changes on the Wednesday and ours at Tuesday's open. After the 13 earlier rolls, whose crossover came on a Friday, both change on Monday. No shift of dates fits both groups, so the difference is the vendor reacting a trading day later, not the boundary error of "If it fails".

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

1. The quality report on synthetic fixtures finds the planted anomalies (the test plants a gap, a duplicate, an out-of-session print, and a non-monotonic `ts_recv` in a temporary copy of the fixtures) and nothing else.
2. `ff.market.load("MES", "5m", "2024-01-01", "2024-03-31")` returns bars with the documented columns in under 2 seconds warm.
3. `fefat data catalog` prints every dataset with its range, fidelity coverage, and quality status.

#### Your checks

- Run `fefat data catalog`; then in a notebook open the Markdown report for MES and read the coverage table: it matches what you imported.

#### If it fails

- Reports of "out-of-session prints" on real data often point at the calendar (holiday early closes); fix the override file, not the data.

#### Amendment

2026-10-12 (Phase 1 kickoff, D-38): `scripts/gen_fixtures.py` plants no anomalies and the committed fixtures stay clean, so the test builds a temporary store from them, plants the anomalies, and expects the report to find exactly those (Done means 1 reworded). The report also lists the days the vendor flagged (the conditions 1.6 stores) and the bars held back as incomplete (1.5). Done means 2 and Your checks name MES, the product with the longest real history on this PC (`docs/data-inventory.md`).

2026-10-15, while doing the step (D-45): the code is split by job into `fefat.market.coverage` (what a dataset holds), `quality_checks` (the checks that read every record), `quality` (the report), `quality_report` (its tables, summary, and files), and `api` (`load` and `catalog`), and `fefat data quality [<root>]` writes the reports that `fefat data catalog` reads. `load` takes `continuous=None`: a futures root is spliced by default, a contract or a perpetual loads alone, and `continuous=True` for one of them is refused. The report also counts the prints inside halts and the vendor's condition of each session, and a day whose records hold a finding is not rebuilt from them, so that one wrong record is one finding. On your data on 2026-10-15, MES, MNQ, and MCL are clean, and MGC has four gaps in its 1-minute bars: 2014-09-23 to 25, inside the vendor's degraded days of 2014-09-22 to 25, and 2014-12-31, which step 1.6 found without prints; MES has 3 prints in the break and 6 inside the daily halt, all in 2020, and MGC 21 in the break, all in 2018, the bars steps 1.5 and 1.6 listed. MES's 5-minute bars of 2024's first quarter load in 1.2 s warm, and the four reports take 17 s.

### 1.9 Product catalog, source guide, and data status

Depends on: 1.8 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

FEFAT ships know-how, not data: a catalog of curated products with their specifications, calendars, roll rules, quality rules, and recommended sources; a guide to well-known data sources, with the preset that reads each source's files; and a status view of every catalog product's coverage and quality.

#### Prerequisites

- Step 1.8 merged; the catalog product list (D-38: MES, MNQ, MCL, MGC) and `docs/masterplan/appendix/research-data-sources.md`.

#### Prompt

```text
Masterplan step 1.9 — Product catalog, source guide, and data status.

Read docs/masterplan/02-engine-and-data.md §1.8, docs/masterplan/00-product-spec.md §2.5, docs/adr/0018-own-data-sources-no-shipped-data.md, and docs/masterplan/appendix/research-data-sources.md. Implement the product catalog in `python/fefat/src/fefat/market/catalog/`: a versioned `catalog.yaml` listing the curated products (D-38: MES, MNQ, MCL, and MGC; the others join when their files arrive), each with its instrument specification, calendar, roll rule, schemas, history depth, quality rules, and the sources that can supply it, in order of recommendation. Implement the source guide in `fefat/market/sources/`: a registry of the known sources, written from the research appendix, each describing what it offers, its cost, the terms a trader accepts for personal use, whether a desktop app may use the trader's own account or files, and the import preset (1.10) that reads its files; `fefat data sources` prints it. Add `fefat data status`: each catalog product's coverage per schema and fidelity, last import, quality verdict, and the provider it came from; a product with bars but no ticks reads "complete at 1-minute fidelity", not missing. Datasets carry `origin: import`, their `provider` (the importer or preset), and the licence scope the source's terms give the trader; `ff.market.catalog()` shows them, and `ff.market.load` takes an optional `provider` where several datasets cover a product. Nothing in FEFAT connects to a source or serves data to another machine; the origin value `sync` and the `Provider` seam are reserved for the connectors of a later phase (BACKLOG.md).

Tests: the catalog loads and validates (every product names an instrument of 1.2 and a calendar of 1.3); the source guide lists every registered source and preset with its terms; status on the synthetic store reports the fixtures' coverage and the quality verdicts of 1.8.

Not in this step: connectors, sync, and keys (deferred, D-38), importing your own files (1.10), the web pages (Phase 5), the signed catalog updates of Phase 14.
```

#### Done means

1. `catalog.yaml` validates: every product names an instrument of 1.2 and a calendar of 1.3, and `ff.market.catalog()` shows the catalog version and each dataset's origin, provider, and licence scope (test).
2. `fefat data sources` lists every registered source and preset with what it offers, its cost, its terms, and the preset that reads its files (test).
3. `fefat data status` lists every catalog product with its coverage per schema, last import, quality, and provider, and reads "complete at 1-minute fidelity" for the four products on this PC.

#### Your checks

- Run `fefat data sources` and read the Databento and NinjaTrader entries; run `fefat data status`: MES, MNQ, MCL, and MGC show their coverage from each product's launch to 2026-09 at 1-minute fidelity, each with a quality verdict.

#### If it fails

- A product shows less coverage than the inventory promises: the gap is in the import (1.6), not in the catalog; read the import summary's skipped symbols and degraded days before touching the catalog.

#### Amendment

2026-10-12 (D-37): FEFAT no longer provides "platform data" or plans to deliver data to customers; traders connect their own sources, and FEFAT provides the catalog, the connectors and presets, the source guide, and sync. The step was renamed from "Platform data catalog and managed updates"; `PlatformDataSource` and its hosted swap are gone, the `Provider` interface of 1.4 is the seam for every source, `source: platform | user` became `origin: sync | import` with a `provider`, and the commands lost the word platform.

2026-10-12 (Phase 1 kickoff, D-38): no connector and no sync in Phase 1, so the step keeps the catalog, the source guide, and `fefat data status`, and loses `fefat data connect`, `fefat data sync`, the keys, and the end-to-end sync tests, which stay in `BACKLOG.md` with the `Provider` seam; the title, the meta line (plan optional, step-reviewer, security no, default model), purpose, prerequisites, prompt, Done means, Your checks, and If it fails were rewritten. The catalog is MES, MNQ, MCL, and MGC, the products with data on this PC; the source guide is written from `appendix/research-data-sources.md`.

2026-10-16, while doing the step (D-47): the catalog holds no quality rules, since the only per-product rule is CL's negative prices of 2020-04-20 and 21, kept in `fefat.market.quality_checks`, and CL is not in the catalog; the field arrives with the first catalog product that needs one (`BACKLOG.md`). `load(provider=...)` chooses among a root's providers and refuses a root that several hold without it, since loading the catalog's recommended source waits for the second provider of 1.10. Each raw file's import date and roots live in the raw manifest rather than in `dataset.json`, which snapshots pin and later imports therefore leave as the first one wrote it, and a clean report checked to an earlier trade date than a dataset's last reads stale, while a flagged one stays flagged. The guide registers 27 of the research's sources and leaves out CCXT, a library over the venues' own data; Stooq, Nasdaq's CHRIS, and Yahoo Finance, daily only and dead or forbidding automated use; Tradovate and Rithmic, which export no bars; and the file conventions of Backtrader, Zipline, and QuantConnect Lean, which 1.10's generic profiles cover. Your store's four `dataset.json` files and its raw manifest gained the new keys in place on 2026-10-16, with your approval (`docs/data-inventory.md`).

### 1.10 Import your own market data

Depends on: 1.9 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: default

#### Purpose

Traders can bring data for any product — files from their own data vendor or trading platform — mapped into the same canonical store, validated, and used exactly like data a connector synced.

#### Prerequisites

- Step 1.9 merged; the `config/data-guard-text-and-push` pull request merged (the guard refuses plain-text data files outside `fixtures/synthetic/`); one of your own files to try (an IBKR, NinjaTrader, or TradingView export).

#### Prompt

```text
Masterplan step 1.10 — Import your own market data.

Read docs/masterplan/02-engine-and-data.md §1.8 and the export layouts in docs/masterplan/appendix/research-data-sources.md. Implement `fefat data import file <path> --profile <name>`: a generic importer for bar and tick files (CSV, TSV, Parquet; zipped or gzipped) driven by import profiles of kind `market_data` — column mapping (timestamp; open, high, low, close, volume; or price, size, side), timestamp format and time zone, whether timestamps mark the bar open or the bar close, price scaling, the timeframe (ticks, or bars of any timeframe; bars coarser than 1 minute are accepted, and backtests on them fill at that coarser fidelity), the series type (per contract with contract codes, or a continuous series, unadjusted or back-adjusted; continuous series run as one synthetic contract with roll handling off and a warning on every run that uses them), and the instrument (an existing one, or a new specification with tick size, point value, currency, and calendar — one of the built-in calendars or the generic one from 1.3 — entered once and saved). Profiles are saved and reusable. Ship presets for common exports, first the ones you use (D-38: Databento CSV, IBKR bars pulled through the TWS API and saved as CSV, NinjaTrader, TradingView), then Sierra Chart and TradeStation, each written from the layouts in the research appendix, an entry of the source guide (1.9), documented, and tested against a small synthetic sample in its exact layout, generated by scripts/gen_fixtures.py under fixtures/synthetic/. `--preview` prints the first rows as they would be stored and the problems detected, and writes nothing.

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

2026-10-12 (Phase 1 kickoff, D-38): the presets are Databento CSV, IBKR (bars pulled through the TWS API and saved as CSV: date, open, high, low, close, volume, average, barCount, in the TWS login's time zone), NinjaTrader, and TradingView first, then Sierra Chart and TradeStation, written from the export layouts the kickoff researched (`appendix/research-data-sources.md`: delimiter, header, timestamp format and time zone, open-or-close stamping, contract-code form); their samples come from `scripts/gen_fixtures.py` under `fixtures/synthetic/`, the only place the guard admits them. With no connector in Phase 1, this importer and 1.6 are the only way data enters the store, so the prompt and prerequisites were reworded, and the guard's plain-text extensions arrive first in their own `config/` pull request (`BACKLOG.md`).

2026-10-20, while doing the step (D-49): the importer is `fefat.market.importers.file_import`, with the profile model in `profiles` and the six presets as YAML files in `importers/presets/`, each named for the provider its datasets are stored under and taking the licence scope of its source in the guide, where all six now read `available`; a file is read in `tabular`, `profile_values`, `profile_contracts`, and `profile_records`. A bar takes the bucket of its session that its timestamp opens or closes, by the bar builder's rule (`fefat.market.bars.in_buckets`), a daily bar the session of the date it names, stamped with the date alone or at its session's close, and a tick its session's trade date. Rows that cannot be read, timestamps outside the session table, Databento records of another type than the profile's timeframe, prices off the tick, volumes that are no whole lot, records before the product's first trade date, two bars in one bucket, bars off their buckets or spaced as another timeframe, and an offset from the calendar refuse an import with their first row; the calendar check reports the offset (`fefat.market.calendar_offset`) in whole or half hours, the time zone, over the file or its part on one side of a daylight-saving change, or in one bar, the stamping, and where moving the records by an hour or a bar would show none, as for regular hours only, a thin file, or a calendar without breaks, the import warns that the calendar could not check their timing. A zone name after each time, as IBKR writes it, must give the instants of the import's zone, and a file that leaves no record is refused with the problems of its rows. A file holds one product: one contract named by the import, the file's name, or each row's symbol, dated by its run of rows, a spread's rows set aside; the root itself for a perpetual or a spot pair, a futures file that names no contract being refused; or a continuous series stored as `<root>-CONTINUOUS` with instrument id 1, which `dataset.json` marks and every load warns of, and which loads without a raw close when back-adjusted. A file's own instrument ids must pair one to one with its contracts. A new instrument is saved as `<FEFAT_DATA_DIR>/instruments/<root>.json`, with its first trade date from the profile and a calendar of its own where it gives hours (`Instrument.calendar` is a built-in id or a calendar); a trader's own profile is saved under `<FEFAT_HOME>/profiles/` once an import with it has written, and `fefat data profiles` lists them. `load` gains `origin=`, bars coarser than a minute as the finest data, with a warning on every load, and the catalog's recommended source where several providers hold a product (`fefat.market.dataset_choice`). The Databento preset reads 1-minute bars, so the tick path is tested with a trades profile written in the test. A preview writes nothing to the data folder or the profiles; it caches session tables in `FEFAT_HOME` as every reader does. No NinjaTrader, IBKR, or TradingView export of yours was on this PC when the step ran, so the samples stand in for it until Your checks.

### 1.11 Notebook demo and phase exit prep

Depends on: 1.10 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

A notebook you can rerun any time shows the whole data layer working on your real data, and documents how to use it.

#### Prerequisites

- Step 1.10 merged.

#### Prompt

```text
Masterplan step 1.11 — Notebook demo.

Write `notebooks/01-market-data.ipynb`: the source guide and the catalog status, load continuous MES 5-minute bars for a year, show the roll dates and the adj_offset steps, resample one real day of 1-minute bars to 5-minute and daily and compare with the vendor's (and rebuild 1-minute bars from ticks the day a trades file exists; the cell skips with a message otherwise), load one dataset you imported through a preset, and show the quality summary. Every cell has a one-line explanation; expected outputs are described in markdown cells (no data is committed; the notebook runs against FEFAT_DATA_DIR). Add `docs/data-guide.md` explaining the store layout, units, calendars, rolls, the source guide, how to import Databento files and your own exports (profiles and presets), and how to read the status and quality reports, written for you.

Not in this step: anything else.
```

#### Done means

1. The notebook runs top to bottom on your machine without edits.
2. `docs/data-guide.md` answers: where is my data, which sources are suggested and where do I get their files, how do I import Databento files and my own exports, how do I check coverage and quality.

#### Your checks

- Run the notebook. The vendor-bar comparison cell prints zero differences.

#### If it fails

- A cell fails on a missing dataset: the notebook should detect what is in the catalog and skip with a message; ask Claude Code to make it robust rather than editing paths by hand.

#### Amendment

2026-10-12 (D-37): the notebook and the data guide show the source guide and connected sources instead of platform data.

2026-10-12 (Phase 1 kickoff, D-38): no connected sources and no crypto data in Phase 1, so the notebook and the guide show the source guide, the catalog status, and the data of `docs/data-inventory.md` (MES for the continuous series; the tick cells skip until a trades file is imported); the prompt and Done means 2 were reworded.

## Phase exit

```text
/phase-exit 1 — Run the exit procedure from docs/masterplan/05-build-process.md §6 for Phase 1: full suite from a clean clone; leakage-auditor and engine-accuracy-reviewer over the phase diff; /security-review (the importers parse files you supply); demo script = notebooks/01-market-data.ipynb; retro of repeated corrections into CLAUDE.md or rules; backlog groomed; tag phase-1.
```
