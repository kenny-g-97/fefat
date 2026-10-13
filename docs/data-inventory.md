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
- The records are 56-byte OHLCV messages; the estimate divides the file size after the metadata header by 56, since a DBN v3 header carries no record count.
- Each product starts at its launch, not at the dataset's start: the first outrights in the metadata are MGCG1 (mapped from 2010-09-12), MCLF3 (2012-12-16), and MESH0 and MNQH0 (2019-04-14); the newest listings are MESZ7 and MNQZ7 (2026-09-06).
- `condition.json`: 5,113 and 5,114 dates `available`, and the same 32 dates `degraded` in both jobs: 2014-06-11, 2014-06-12, 2014-06-13, 2014-06-15, 2014-09-22, 2014-09-23, 2014-09-24, 2014-09-25, 2017-11-13, 2018-10-21, 2019-01-15, 2019-02-22, 2019-03-13, 2019-03-26, 2020-02-27, 2020-02-28, 2020-05-05, 2020-06-30, 2020-07-01, 2021-12-05, 2022-01-02, 2024-09-18, 2025-09-17, 2025-09-24, 2025-11-28, 2026-01-31, 2026-03-15, 2026-03-16, 2026-03-21, 2026-04-10, 2026-05-24, 2026-08-29. The newest `last_modified_date` is 2026-09-23, after the vendor's re-normalisation of the CME history on 2026-08-08.

## Not on this PC

- Nothing else from Databento (confirmed at the kickoff): no ES, NQ, CL, or GC; no trades, TBBO, 1-second bars, definitions, or statistics.
- No crypto archives and no platform exports yet; the IBKR, NinjaTrader, and TradingView files for step 1.10 are exported when that step runs.
