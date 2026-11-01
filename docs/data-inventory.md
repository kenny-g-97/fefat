# Data inventory

Where the market data on this PC is and what it holds: paths, schemas, and ranges only. No data enters the repository (D-21, D-37). Written at the Phase 1 kickoff (2026-10-12, D-38); step 1.6 imports these files, and a new purchase or export is added here with the same columns.

## Folders

- `FEFAT_DATA_DIR` is not set, so the store is the default `%LOCALAPPDATA%\FEFAT\data` (`fefat.config.resolve_paths`), which step 1.6's imports created.
- Vendor files bought before the plan sit in `C:\Users\kenji\Documents\AlgoTrading_app\market_data\`, a sibling of the repository folder and outside git. Step 1.6 copies them under `data/raw/` with manifest entries; the originals stay where they are.

## Databento batch downloads (2026-09-23)

Two batch jobs on the dataset `GLBX.MDP3`, schema `ohlcv-1m`, parent symbology in (`<ROOT>.FUT`, every child of the product: outrights, calendar spreads, and strategy symbols), `instrument_id` out, encoding DBN version 3, uncompressed, no symbol mapping applied (the mapping is in the DBN metadata), `pretty_px` and `pretty_ts` off. Each folder holds the DBN file and three sidecars: `metadata.json` (the query), `manifest.json` (file names, sizes, and the vendor's SHA-256), and `condition.json` (one row per date, `available` or `degraded`, with the vendor's `last_modified_date`).

| Folder | Job | Parents | File | Size | Range (UTC) | Records (estimate) | Child symbols in the metadata |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `market_data\MCL_MGC_MES\` | `GLBX-20260923-KYNG8TXEXQ` | `MCL.FUT`, `MGC.FUT`, `MES.FUT` | `glbx-mdp3-20100606-20260922.ohlcv-1m.dbn` | 873,270,512 bytes | 2010-06-06 00:00 to 2026-09-23 00:00 | 15.6 million | 1,913: MCL 101 outrights, 885 spreads, 31 strategies; MGC 60 outrights, 664 spreads; MES 35 outrights, 132 spreads; 5 `UD` strategies |
| `market_data\MNQ\` | `GLBX-20260923-KF6FGGLH79` | `MNQ.FUT` | `glbx-mdp3-20100606-20260923.ohlcv-1m.dbn` | 222,496,208 bytes | 2010-06-06 00:00 to 2026-09-23 15:20 | 4.0 million | 167: MNQ 35 outrights, 132 spreads |

- The SHA-256 of each file is in its folder's `manifest.json`; step 1.6 verifies it before importing.
- Imported by step 1.6 on 2026-10-13 with `fefat data import databento <folder>`: MNQ 34 contracts with bars (MNQM2019 to MNQU2027; MNQZ2027, listed on 2026-09-06, has none), MES 34 (MESM2019 to MESU2027), MCL 84 (MCLQ2021 to MCLZ2029), and MGC 106 (MGCZ2010 to MGCM2028), with 1,291 spread and strategy symbols set aside; the originals stay in their folders.
- Step 1.5 added the bar column `vwap` (D-43) to the 3,690 imported partitions on 2026-10-14, in place and with your approval: null, since the vendor's bars carry none, each partition written again through `Store.write_partition`; the originals and `data/raw/` stayed as they were. A store copied from before that date gets the column by importing the files again, since the importer now writes it. `fefat data verify-bars <root> <date>` checks the bars against bars rebuilt from finer data, which waits for a trades file (`docs/masterplan/BACKLOG.md`).
- The records are 56-byte OHLCV messages; the estimate divides the file size after the metadata header by 56, since a DBN v3 header carries no record count.
- Each product starts at its launch, not at the dataset's start: the first outrights in the metadata are MGCG1 (mapped from 2010-09-12), MCLF3 (2012-12-16), and MESH0 and MNQH0 (2019-04-14); the newest listings are MESZ7 and MNQZ7 (2026-09-06).
- `condition.json`: 5,113 and 5,114 dates `available`, and the same 32 dates `degraded` in both jobs: 2014-06-11, 2014-06-12, 2014-06-13, 2014-06-15, 2014-09-22, 2014-09-23, 2014-09-24, 2014-09-25, 2017-11-13, 2018-10-21, 2019-01-15, 2019-02-22, 2019-03-13, 2019-03-26, 2020-02-27, 2020-02-28, 2020-05-05, 2020-06-30, 2020-07-01, 2021-12-05, 2022-01-02, 2024-09-18, 2025-09-17, 2025-09-24, 2025-11-28, 2026-01-31, 2026-03-15, 2026-03-16, 2026-03-21, 2026-04-10, 2026-05-24, 2026-08-29. The newest `last_modified_date` is 2026-09-23, after the vendor's re-normalisation of the CME history on 2026-08-08.

## Databento symbology (2026-10-15)

The vendor's continuous mapping `MES.v.0`, which you fetched once from the free `symbology.resolve` endpoint for step 1.7's roll check: dataset `GLBX.MDP3`, `stype_in` continuous, `stype_out` instrument_id, from 2019-05-05 to 2026-09-24.

| File | Size | Holds |
| --- | --- | --- |
| `market_data\databento-symbology\MES.v.0.json` | 1,765 bytes | 31 intervals from 2019-05-03 to 2026-09-24, one front contract each |

- Filed in the store as `raw/databento/symbology/GLBX.MDP3-MES.v.0.json`, with its SHA-256 in the raw manifest, where `fefat.market.continuous_check` reads it; the original stays in its folder.

## Quality reports (2026-10-15)

`fefat data quality` writes each product's report under `data/reports/databento/<root>/` (`days.parquet`, `findings.parquet`, and `quality.md`, step 1.8), and `fefat data catalog` lists each dataset with its quality.

| Root | Trade dates | Sessions | Contracts | Quality |
| --- | --- | --- | --- | --- |
| MES | 2019-05-06 to 2026-09-23 | 1,861 | 34 | clean |
| MNQ | 2019-05-06 to 2026-09-23 | 1,861 | 34 | clean |
| MCL | 2021-07-12 to 2026-09-23 | 1,308 | 84 | clean |
| MGC | 2010-10-04 to 2026-09-23 | 4,021 | 106 | flagged: no 1-minute bars on 2014-09-23, 24, and 25, inside the vendor's degraded days, and 2014-12-31 |

- Each file ends inside the session of trade date 2026-09-23, so its last session's buckets after the end are held back: 1,260 one-minute buckets for MES, MCL, and MGC, whose files end at 00:00 UTC, and 340 for MNQ, whose file ends at 15:20 UTC.

## Catalog metadata (2026-10-16)

Step 1.9 added each dataset's `origin` and `licence_scope` to its `dataset.json`, and each raw file's `imported_on` and `roots` to `raw/MANIFEST.json`. Your store's four `dataset.json` files and its raw manifest gained them in place on 2026-10-16, with your approval, written through the store's own models after a copy of the five files was taken; the partitions and the raw files stayed as they were. The import dates are those of the raw copies under `raw/`.

| File | Added |
| --- | --- |
| `databento/ohlcv-1m/root=<MES, MNQ, MCL, MGC>/dataset.json` | `origin` import, and `licence_scope` from Databento's entry in the source guide |
| The DBN file of `GLBX-20260923-KYNG8TXEXQ` | `imported_on` 2026-10-13, `roots` MCL, MES, and MGC |
| The DBN file of `GLBX-20260923-KF6FGGLH79` | `imported_on` 2026-10-13, `roots` MNQ |
| The six sidecars of both jobs | `imported_on` 2026-10-13, no roots |
| `symbology/GLBX.MDP3-MES.v.0.json` | `imported_on` 2026-10-15, no roots |

- `fefat data status` reads each product complete at 1-minute fidelity from its launch to 2026-09-23, last imported on 2026-10-13: MES, MNQ, and MCL clean, and MGC flagged.
- A store copied from before that date is refused until it gets the same keys (`docs/masterplan/BACKLOG.md`, upgrading a store's metadata).

## NinjaTrader 8 export (2026-10-20)

Your NinjaTrader 8 export of MNQ minute bars (Historical Data window, Export, interval Minute, data type Last), one `.txt` file per contract in `C:\Users\kenji\Documents\AlgoTrading_app\market_data\NT8_data\raw\`: 30 files of 1.8 to 5.4 MB, 139 MB in all, named `MNQ MM-YY.Last.txt` from `MNQ 03-20` to `MNQ 12-25`, exported on 2026-10-13.

- Imported by step 1.10 on 2026-10-20 with `fefat data import file <file> --profile ninjatrader`, one file at a time: 27 contracts into `ninjatrader/ohlcv-1m/root=MNQ`, each original kept under `raw/user/<sha256>/`. Three files were refused for spurious bars in NinjaTrader's history, under a wrong cause (`BACKLOG.md`, bars in a break that no offset explains): `MNQ 12-20.Last.txt` (a corrupt week, 2020-10-18 to 10-23), `MNQ 03-24.Last.txt` (extra bars in the hour before the 2024-03-10 open), and `MNQ 03-25.Last.txt` (a bar in the minute before the 2025-03-09 open).
- `fefat data status` reads MNQ from `ninjatrader` as 2019-05-06 to 2026-09-18, complete at 1-minute fidelity, quality flagged: 175 sessions without records, where the three refused contracts were the front month. `load("MNQ", …)` reads Databento's MNQ first, the catalog's recommended source.

## Interactive Brokers ticks and bars (2026-10-31)

Sessions of MNQZ2026 pulled from your TWS with `C:\Users\kenji\Documents\Trading\Data\ibkr\pull_mnq_ticks.py` (`reqHistoricalTicks`, TRADES, about 1,000 prints a request, 12 s apart), one CSV of ticks and one of 1-minute bars per session, imported with the `ibkr-ticks` profile beside the script and the `ibkr` preset with `--time-zone UTC`, for step 2.16's check of the tick engine (D-67).

- 2026-09-21: 976,389 prints, equal to the trade count of IBKR's bars, imported on 2026-11-01 into `ibkr/trades/root=MNQ` and `ibkr/ohlcv-1m/root=MNQ`, quality clean; `fefat data verify-bars MNQ 2026-09-21` rebuilds 1,379 bars from the ticks with no differences. Against Databento's bars, 14 minutes differ in volume (0.8 % less over the session, blocks at 09:05 and 09:55 Chicago) and 10 in a price, and IBKR's bar of the closing minute is empty while its ticks hold the 789 lots Databento shows.
- 2026-09-22 and 09-23: still to pull; the 09-22 pull reached 09:43 Chicago when TWS logged off, and the puller resumes. A session's file is imported only once it is complete, since a trade date's first import stands.
- IBKR stamps prints to the second, gives no aggressor side (`N`), and filters block and spread trades; its Time and Sales goes back three years, an expired contract two years after its expiry, and a session takes about 3.2 hours to pull.

## Not on this PC

- Nothing else from Databento (confirmed at the kickoff): no ES, NQ, CL, or GC; no trades, TBBO, 1-second bars, definitions, or statistics.
- No crypto archives; no TradingView, Sierra Chart, or TradeStation export yet (the NinjaTrader export and the IBKR sessions are above).
