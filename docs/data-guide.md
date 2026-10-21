# Your market data

How FEFAT keeps your market data, where it comes from, how you bring it in, and how you check it, written for you as the trader using FEFAT on this PC. `notebooks/01-market-data.ipynb` runs every part of it on your own data. The design behind it is in `docs/masterplan/02-engine-and-data.md` §1 and `docs/adr/0019-canonical-market-data-store.md`.

FEFAT ships no market data (D-37). You buy or export the files, FEFAT imports them into a store on your machine, and nothing is uploaded anywhere. FEFAT connects to no data source yet (D-38): every dataset comes from a file you import.

## Where your data is

FEFAT keeps two folders, both outside the repository:

| Folder | Default on Windows | Holds |
| --- | --- | --- |
| `FEFAT_HOME` | `%LOCALAPPDATA%\FEFAT` | your saved import profiles (`profiles\`) and caches FEFAT can rebuild (`cache\`, such as the session tables) |
| `FEFAT_DATA_DIR` | `%LOCALAPPDATA%\FEFAT\data` | the market data, the original files, the quality reports, and the products your imports added |

On macOS `FEFAT_HOME` is `~/Library/Application Support/FEFAT`. To keep the data on a bigger drive, move the data folder there and set `FEFAT_DATA_DIR` to its absolute path, for example with `setx FEFAT_DATA_DIR "D:\FEFAT\data"` in a terminal, then restart VS Code so that the notebooks see it. The folder's files refer to each other by relative paths, so it moves whole. Prefer an NTFS drive: on exFAT or a network drive, a power cut during a write can leave a file half replaced.

Inside the data folder:

```text
databento\ohlcv-1m\root=MES\dataset.json                     what the dataset's files share
databento\ohlcv-1m\root=MES\contract=MESZ2026\month=2026-09\part.parquet
ninjatrader\ohlcv-1m\root=MNQ\...                            a dataset you imported through a preset
raw\MANIFEST.json                                            each original file, with its size and SHA-256
raw\databento\<batch job>\                                   a Databento download, unchanged
raw\user\<SHA-256>\<file name>                               each export you imported, unchanged
reports\<provider>\<root>\quality.md                         the quality report, beside days.parquet and findings.parquet
instruments\<root>.json                                      a product FEFAT did not know, added by your import
```

- The first folder is the **provider**, the importer or preset the data came through: `databento`, `ninjatrader`, `tradingview`, and so on. Data of one product from two providers makes two datasets, and both are kept.
- Then comes the **schema**, `trades` or bars such as `ohlcv-1m`, then the product (`root=`) and the contract (`contract=`).
- Ticks and 1-second bars are kept in a file per trade date (`date=`), 1-minute bars in a file per month (`month=`), and coarser bars in one file per contract.
- `dataset.json` holds what a dataset's files share: the unit of its volumes (one contract), its origin (`import`), the licence scope of its source, and its series (dated contracts, or one continuous series).

Leave the folder to FEFAT: the imports and the quality reports do all the writing, each file is checked against its schema whenever it is read, and the originals under `raw\` never change. None of it enters git: the commit guard refuses market data outside `fixtures/synthetic/` (D-21).

`fefat data status` shows what the store holds now, and `docs/data-inventory.md` records the files bought for this PC, where they came from, and what each import did.

## Units and the columns of a load

The store keeps Databento's units, whatever a file's source:

- **Prices** are whole numbers of billionths of the price as the exchange quotes it: 6,850.25 is stored as 6850250000000. Divide by `1e9` for points, as the notebook's `readable` does.
- **Times** are whole numbers of nanoseconds since 1970-01-01, in UTC. `pl.from_epoch("ts_open", time_unit="ns")` turns them into Polars datetimes, and `.dt.replace_time_zone("UTC").dt.convert_time_zone("America/Chicago")` shows them in Chicago time.
- **Volumes** count the dataset's unit, one contract for futures.

`ff.market.load(root_or_symbol, timeframe, start, end)` returns a lazy Polars frame, which `.collect()` reads, with the same columns in every mode, `ff.market.SIGNAL_BAR_COLUMNS`:

| Column | Holds |
| --- | --- |
| `ts_open`, `ts_close` | the bar's bucket, from `ts_open` up to but not including `ts_close`; a strategy may use a bar from its `ts_close` on |
| `trade_date` | the trade date of the bar's session |
| `instrument_id` | the contract's id: the file's own, or, where an export has none or holds a continuous series, one FEFAT gives the contract |
| `open`, `high`, `low`, `close` | the bar's prices, adjusted on a continuous series |
| `volume`, `trade_count` | what traded in the bar; `trade_count` is empty where the source gives none |
| `vwap` | the volume-weighted average price, empty where the source gives none, as on Databento's bars |
| `contract` | the contract the bar belongs to, such as `MESZ2026` |
| `close_raw` | the contract's own close, the price orders fill at |
| `adj_offset` | what was added to the contract's prices: `close` is `close_raw + adj_offset` |
| `roll_flag` | true on the first bar of each new front contract |
| `zero_volume` | true on a bar without trades, priced at the close before it |

```python
import fefat as ff

ff.market.load("MES", "5m", "2025-09-23", "2026-09-23").collect()  # continuous, from the recommended source
ff.market.load("MESZ2026", "1m", "2026-09-01", "2026-09-22").collect()  # one contract
ff.market.load("MES", "1d", "2026-09-01", "2026-09-22", continuous=False).collect()  # each contract's own bars
ff.market.load("MNQ", "5m", "2026-09-11", "2026-09-18", continuous=False, provider="ninjatrader").collect()
```

- The timeframe is a count and a unit, `s`, `m`, `h`, or `d`: `1s`, `5m`, `1h`, `1d`. It cannot be finer than the data. `fidelity="auto"`, the default, builds the bars from the finest data the store holds (trades, then 1-second, then 1-minute bars), and `fidelity="1m"` names the data to build them from.
- A load reads one dataset: beside years of 1-minute bars, a trades file of a few months makes `fidelity="auto"` read those months alone, so name `fidelity="1m"` for the years, as the notebook does.
- Start and end are trade dates, written as dates or as text such as `2026-09-23`.
- The bars lie on a dense grid: a row for every bucket of every session, outside halts, so a bucket without trades is a row flagged `zero_volume`. A daily bar is the whole session, from its open to its close.
- The buckets of a session the data has not finished are held back until later data completes it.

## Calendars and trade dates

Each product follows a session calendar: the exchange's hours in its time zone, and its holidays. A CME session runs from 17:00 Chicago on the evening before its trade date to 16:00 Chicago on it, so Sunday evening's trading belongs to Monday. FEFAT dates every bar and tick by the session it falls in, never by its day in UTC or on your clock.

- **Holidays** are of three kinds: a full close, on which no session ends; a halt day, which trades until the exchange halts it during the day, at 12:00 Chicago for equity index, and whose trading belongs to the next trade date; and an early close of the trade date. A weekend or a halt folds into the next session, as CME dates it.
- **Halts**: equity index futures halted daily from 15:15 to 15:30 Chicago until June 2021, and the bars leave halts out.
- **The break**: a print received in the hour between a close and the next open keeps the trade date of the session it follows.
- **Built-in calendars**: `cme-equity-index` (ES, NQ, MES, MNQ), `cme-energy` (CL, MCL), `cme-metals` (GC, MGC), and `crypto-24x7`, UTC days for crypto. A product you import on other hours gets a calendar of its own: a time zone, a daily open and close, and the weekdays it trades, without holidays.
- **Session tables** for 2010 to 2030 are built once per calendar and kept in `<FEFAT_HOME>\cache\calendar\`; deleting the cache only costs a rebuild.

Every import compares its records with the calendar, each trade date's first and last bar with its session. An import whose records all run early or late, by whole or half hours or by one bar, is refused with that offset, as the section on your own exports explains.

## Rolls and continuous series

A futures product is many contracts, one per expiry month. `load` splices them into one continuous series unless you ask for `continuous=False` or name a contract:

- **The front contract** of a session is decided at its open from each contract's volume in the session before: the contract that traded the most leads. The front only moves forward, never back to an earlier month, and a contract is dropped at the open of its last trade date, for MES and MNQ the third Friday of the expiry month. The fronts come from the 1-minute bars of the dataset's whole history, so a window's fronts never depend on where it starts.
- **Prices are forward-anchored.** The series starts at the dataset's first contract with an `adj_offset` of 0. At each roll the gap is the new contract's close minus the old one's in the last bar both traded in before the roll, and `adj_offset` falls by that gap: the new contract's prices are shifted to join the old series, so the adjusted series has no jump, and history never changes when a later roll happens. `close_raw` jumps by the gap, and `roll_flag` marks the new front's first bar.
- **Orders fill at the contract's own prices**, `close_raw`, never at adjusted ones; a level of the adjusted series converts back by subtracting `adj_offset`.
- **A dataset that lacks a contract** cannot splice across the hole: `load` refuses the roll whose two contracts never traded in one bar, as with your NinjaTrader MNQ export, which lacks MNQZ2020. Load such a dataset with `continuous=False`.

A file you import as one continuous series, such as a platform's continuous contract, is stored as the synthetic contract `<root>-CONTINUOUS`, which never rolls: every load of it warns that roll handling is off, and a back-adjusted one has no `close_raw` at all, since its old prices were never traded.

## Which sources, and where to get their files

`fefat data sources` prints the source guide FEFAT ships: 27 well-known sources of market data, researched on 2026-10-12. For each it gives

- what the source offers, and what it costs;
- the terms you accept for personal use, with the page they are on;
- whether a desktop app on your machine may use your own account or files: "check the terms yourself" for every source until one confirms in writing, and "forbidden" for dxFeed's retail keys;
- the licence scope your data from it comes under, which FEFAT copies into every dataset imported from it;
- its presets, the importers that read its files.

Prices and terms change, so check a source's own pages before you buy. The research behind the guide is in `docs/masterplan/appendix/research-data-sources.md`.

The catalog recommends, best first: Databento for all four of its products, then FirstRate Data; Kibot for MES, MNQ, and MGC; Portara / CQG Data Factory for MES; and Massive and Interactive Brokers for all four. `fefat data status` names a product's first recommended source while your store lacks it. A source without a preset still works, through a profile of your own (below).

Where each preset's files come from:

| Preset | Where the file comes from | Mind |
| --- | --- | --- |
| `databento` | a batch download from Databento's portal: dataset `GLBX.MDP3`, schema `ohlcv-1m` or `trades`, symbols by parent such as `MES.FUT` (every contract of the product), symbology out as instrument ID, encoding DBN, and no split, so that the job is one file | Set the split to none: Databento's API splits a job into a file per day by default, and the import refuses a job of several DBN files, whose rows could share a partition it does not merge yet. Download the whole job folder: the `.dbn` or `.dbn.zst` file with `metadata.json`, `manifest.json`, and `condition.json`. A job downloads again for 30 days at no charge. |
| `databento-csv` | the same download with encoding CSV, of 1-minute bars, also without a split | Times are UTC. Copy the preset into a profile of your own for Databento's CSV of trades or of other bars. |
| `ninjatrader` | NinjaTrader 8's Historical Data window, Export: interval type Minute, data type Last, one instrument at a time | Files are named like `MNQ 09-26.Last.txt`. Times are always UTC, each bar stamped at its close. Only history NinjaTrader has downloaded can be exported. |
| `tradingview` | the chart's menu, Download chart data, time format UNIX timestamp | Put the Volume indicator on the chart first, and scroll back until the bars you want are loaded; exporting needs a paid plan, which sets how much history loads. The file's name, such as `CME_MINI_ESH2026, 1.csv`, names the contract. |
| `sierra-chart` | Edit, Export Intraday Data to Text File, of a 1-minute intraday file | Times are always UTC. A bar export (Export Bar Data to Text File) is in the chart's time zone instead: set the chart to UTC, or give `--time-zone`. |
| `tradestation` | the Data window's Save, as a text file | Times are in the chart's time zone, which each import names with `--time-zone`, each bar stamped at its close. The layout rests on a community sample, so check the preview against your file. |
| `ibkr` | bars you pull through the TWS API (`reqHistoricalData`, 1 min, TRADES) and save as CSV with the columns `date,open,high,low,close,volume,average,barCount` | Times are in the time zone of your TWS login, which each import names with `--time-zone`. Name the file after its contract, such as `ESH2026-1min.csv`, or give `--contract`. |

## Importing Databento files

```text
fefat data import databento "D:\Downloads\GLBX-20260923-KYNG8TXEXQ"
fefat data quality MES
```

Give the import the batch job's folder, or a single `.dbn` or `.dbn.zst` file. It

1. checks each file's SHA-256 against the vendor's `manifest.json`, and refuses a file that differs, printing both hashes;
2. copies the originals to `raw\databento\<batch job>\`, unchanged, and lists them in `raw\MANIFEST.json`;
3. names each record's contract, such as `MESZ2026`, from the file's symbology, sets calendar spreads and strategy symbols aside, and dates each bar by its session;
4. writes each contract's bars into the store, and prints what it wrote and what it set aside.

A second run of the same folder imports nothing and says so. A later download with rows of a contract's month that the store already holds is refused rather than merged, so until FEFAT merges overlapping files (`docs/masterplan/BACKLOG.md`), a purchase can only add months the store lacks. After an import, write the product's quality report with `fefat data quality <root>`: a file import writes it by itself, a Databento import does not. Record each purchase in `docs/data-inventory.md`, as the files on this PC are.

To check your bars against ticks, buy trades that span at least one whole session the 1-minute bars also cover. A file's first and last sessions are partial, since a download from midnight UTC starts and ends inside one, so the notebook compares only the sessions between. The quality report still rebuilds those two sessions, and lists their bars as differences until it learns to leave them out (`docs/masterplan/BACKLOG.md`).

## Importing your own exports

An export from your platform comes in through an import profile, a YAML description of a file layout: its delimiter and header, the columns that hold the time and the prices, how times are written and in which time zone, whether a bar's time marks its open or its close, the prices' scale, the timeframe (ticks, or bars of any timeframe), and whether the file holds dated contracts or one continuous series. FEFAT ships the presets above, one per export.

1. **Pick the profile.** `fefat data profiles` lists the presets and your saved profiles, and `fefat data profiles ninjatrader` prints one as YAML.
2. **Preview.** `fefat data import file "D:\Exports\MNQ 09-26.Last.txt" --profile ninjatrader --preview` prints the first records as they would be stored and every problem found, and writes nothing.
3. **Import.** Run the same command without `--preview`. It keeps the original as `raw\user\<SHA-256>\<file name>`, writes the records as the dataset `<provider>\<schema>\root=<root>`, such as `ninjatrader\ohlcv-1m\root=MNQ`, and writes the product's quality report. A second import of the same file changes nothing; one with another profile, contract, root, or time zone is refused, since a stored dataset never changes: the first import stands.

What the file does not say, the import names:

- `--contract MNQZ2026`: the file's contract, where its name does not give it.
- `--time-zone America/New_York`: the time zone of the file's times, where the profile leaves it to each import, as `ibkr` and `tradestation` do.
- `--root ES`: the product of a continuous series or a perpetual.

**A profile of your own.** For a layout no preset reads, such as 5-minute bars, ticks, or a source without a preset, copy the closest preset from `python/fefat/src/fefat/market/importers/presets/` into a file of your own; each preset's comments describe its layout. Give it a `name` of its own, since the presets' names are taken, and change what differs. Keep its `provider` for the same platform's files; for another source, name a provider of your own and add a `licence_scope` line with the terms its data comes under. Import with `--profile` and the file's path. Once an import with it has written, the profile is saved in `<FEFAT_HOME>\profiles\`, and later imports name it alone.

**A product FEFAT does not know** needs an `instrument:` block in the profile: its `root`, its `kind` (`futures`, `perpetual`, or `spot`), `tick_size`, `point_value`, `currency`, `calendar` (a built-in calendar's id, or hours of its own: `time_zone`, `opens_at`, `closes_at`, `opens_on_previous_day`, and `weekdays`), and `first_trade_date`, before which no record is imported. A futures product also needs its `last_trade_rule`, how its contracts end: `{kind: third-friday}`, `{kind: business-days-before-the-25th, business_days: 3}`, or `{kind: third-last-business-day}`. The first import saves it as `<FEFAT_DATA_DIR>\instruments\<root>.json`, and `ff.market.load` reads the product from then on.

**When an import is refused,** the preview and the import name each problem with the first row that shows it:

- _its records run 6 hours late against the calendar ...; check the time zone of the file's times_: the times are in another zone than the profile says. Give `--time-zone`, or fix the profile's `time_zone`.
- _its records run 1 minute early ...; check whether the file stamps each bar at its open or its close_: the profile's `stamp` names the wrong end of the bar.
- _the calendar could not check the file's time zone and bar stamping_, a warning: a file of regular hours only, a thin file, or a calendar without breaks fits its sessions whatever its offset, so compare a few bars with your platform's chart.
- _each daily bar is stored as its calendar session, open to close_, a warning on every daily import: the calendar cannot tell a session's daily bar from a UTC day's or a regular-hours one, whose prices come from outside the session, so compare one bar's open and close with your platform's session settings.
- prices off the tick, volumes that are not whole lots, records before the product's first trade date, two bars in one bucket, or bars spaced as another timeframe: the profile reads the wrong columns or timeframe, or the file holds bad records.

An offset can also come from bad bars rather than a wrong profile: three contracts of your NinjaTrader MNQ export were refused, as early by a minute or by hours, for spurious bars in NinjaTrader's own history, while the rest of the export imported with the same preset (`docs/masterplan/BACKLOG.md`). Compare a refused contract with another source before you change the profile.

Two warnings come with every load of some imports: bars coarser than a minute warn that backtests on them fill at that coarser fidelity, and a continuous series that its roll handling is off. Where several providers hold a product, `load` reads the first of them among the presets of the catalog's recommended sources, so `databento` before `ibkr` for MES; name another with `provider=`, such as `provider="ninjatrader"`. When none of them is such a preset, as with two platform exports, or for a product outside the catalog, `load` refuses to choose until you name one.

## Checking coverage and quality

```text
fefat data status                       each catalog product: its datasets, coverage, last import, and quality
fefat data catalog                      each dataset in the store: contracts, trade dates, fidelity, and quality
fefat data quality MES                  write MES's quality report; every product's without a root
fefat data verify-bars MES 2026-09-22   rebuild a trade date's bars from finer data and compare them
```

A status line reads:

```text
MES databento ohlcv-1m: 2019-05-06 to 2026-09-23, complete at 1-minute fidelity, last import 2026-10-13, quality clean through 2026-09-23
```

- the product, the provider, and the schema, then the first and last trade dates the dataset holds;
- its coverage: `complete` when it starts by the first trade date of the product's history in the catalog, `partial` when it starts later (the line gives the history's start), `missing` when the store holds none of the product (the line names its first recommended source), and `not in the catalog` for a product the catalog does not list;
- its fidelity: tick, or the timeframe of its bars;
- the last day a file that fed it was imported;
- its quality: `clean` when the report found nothing, `flagged` when it found something (read the report), `unchecked` before a first report (run `fefat data quality`), and `stale` when a clean report checked fewer trade dates than the data now holds (run it again).

**The quality report.** `fefat data quality` writes `<FEFAT_DATA_DIR>\reports\<provider>\<root>\quality.md` for you to read, beside `days.parquet`, a row per session, and `findings.parquet`, a row per finding. It prints each product's summary and the report's path, and exits with 1 when any product is flagged. The report has six sections:

1. **Coverage by month**: the sessions, those with records, the days at each fidelity, the findings, and the days the vendor flagged. A month with fewer days than sessions has gaps.
2. **Findings**, each with its trade date, kind, schema, contract, and count. The kinds are `gap`, a session without records; `duplicates`; `out-of-session`, records outside their session and its break; `clock-decreases`, times running backwards between stored rows; `non-positive-prices`, at zero or below, CL's of 2020-04-20 and 21 allowed; and `bar-differences`, bars that differ from those rebuilt from finer data.
3. **Days the vendor flagged**: the days Databento's `condition.json` marks as other than available, such as `degraded`; a gap on such a day may be the vendor's.
4. **Prints in breaks and halts**: records received after a close or inside a halt, which keep their trade date and are not errors.
5. **Bars against finer data**: the trade dates whose bars were rebuilt from finer data and compared.
6. **Last session**: where the data ends; the buckets of an unfinished session are held back until later data completes it.

**Checking bars against finer data.** `fefat data verify-bars <root> <trade date>` rebuilds the trade date's bars from the finer data the store holds and compares them with the stored ones, provider by provider. Each line gives the bars compared and `no differences`, or lists each difference; `pending` where stored bars wait for finer data to rebuild them from, as the comparisons with ticks do until a trades file is imported; or `no ... stored to compare with`. One comparison always runs on the finest data present: resampled to 5-minute and then daily bars, it must give the daily bars made from it at once. The command exits with 0 when a comparison ran and found no differences.

**In a notebook,** `ff.market.catalog()` and `ff.market.product_status(ff.market.Store(paths.data_dir), paths.reports_dir)`, with `paths = resolve_paths(os.environ)` from `fefat.config`, return the same tables as Polars frames, and `notebooks/01-market-data.ipynb` runs each check of this guide on your data.
