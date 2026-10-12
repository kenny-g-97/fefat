# ADR-0019: One canonical market-data store: units, clocks, schemas, layout, and snapshots

Decision log: [D-40](../masterplan/DECISIONS.md), 2026-10-12

## Context

Every Phase 1 step after 1.1 reads or writes market data: the importers (1.6, 1.10), the bar builder (1.5), the continuous series (1.7), the load API and the quality report (1.8), and from Phase 2 the engine's cache builder. They need one layout, decided once. Databento ships integer prices in 1e-9 units, integer nanosecond timestamps, and two clocks per record; platform exports arrive in other units. Databento re-normalised its CME history in August 2026, so a vendor file can change under the same name, and a run must pin exactly what it read (ADR-0009). The Phase 0 exit reviews asked for three things before the store was defined: a trade date on every bar, because a date taken from `ts_open` puts the first hour of a CME session on the wrong day; the unit of each dataset's sizes, because the BTC fixture's size counts lots of 0.001 BTC; and the vendor's reference time on settlement statistics beside the time they were received.

## Decision

- **Units.** Prices are int64 counts of 1e-9 of the quote currency and timestamps int64 nanoseconds since the Unix epoch in UTC, stored as integers; views convert them.
- **Clocks.** Records keep `ts_recv`, the engine's clock (ADR-0006), and `ts_event`, the venue's time. Bars carry `ts_open`, `ts_close`, and the `trade_date` of their session. Statistics also carry `ts_ref`, the vendor's reference time, while `ts_recv` says when a value became usable.
- **Schemas.** Six, as Polars schemas whose types are Arrow's, with columns in a fixed order and in the vendor's spelling: trades; TBBO, which is trades with the best bid and ask just before them; bars of any timeframe (`ohlcv-1s`, `ohlcv-1m`, `ohlcv-5m`, `ohlcv-1d`), where `trade_count` is null for a vendor's bars without counts; definitions; statistics; and funding. A file whose columns differ in name, type, or order is refused on read and on write.
- **Layout.** `<provider>/<schema>/root=<root>/contract=<contract>/`, then `date=<trade date>/part.parquet` for trades, TBBO, and bars finer than a minute; `month=<month of the trade dates>/part.parquet` for one-minute bars; and `part.parquet` alone for coarser bars, definitions, statistics, and funding. Files are Parquet with zstd. A `dataset.json` in each `root=` folder holds what all its partitions share, for now the unit of sizes and volumes (1 contract, 0.001 BTC). A path is read only if it parses back to the same partition, so a misplaced or misspelled file fails instead of being read.
- **Writes** go to a temporary file beside the target, which then replaces the target in one step, so a reader never sees half a file.
- **Raw files.** Vendor originals stay under `raw/`, beside the providers, and never change. `raw/MANIFEST.json` lists each with its path, size, SHA-256, provider, vendor version, download date, and the vendor's batch job id and published SHA-256. Recording a file whose bytes or details changed is refused, so a corrected download arrives as a new file.
- **Snapshots.** A request names a dataset (provider, schema, root) and a range of trade dates. It selects the partitions whose key touches the range, and every partition without a key. Its snapshot lists each selected partition's path (written with `/`), size, and SHA-256, sorted by path, and hashes their `sha256sum` listing, one `<sha256>  <path>` line per partition, which any language can reproduce. Runs pin snapshot hashes.
- **Folder.** `Store` takes its folder: `resolve_paths(os.environ).data_dir` in the app and notebooks, a temporary folder in tests, and the repository's `fixtures/` (provider `synthetic`) for the fixtures.

## Consequences

- The importers write only through `Store`, so every stored file has its schema, its place, and its dataset's metadata.
- The step that first stores TBBO, definitions, statistics, or funding (1.6 or later) may add columns to that schema, since nothing is stored in it yet, and records them in `02-engine-and-data.md` §1.1. Changing a column of a schema with stored data needs a new decision.
- The bar builder (1.5) adds `vwap` to the bar schema and regenerates the fixtures with their manifest.
- pyarrow stays a development tool (D-39): Polars reads and writes the files.
- The one-step replace is atomic on one NTFS or POSIX volume, not on exFAT or network drives; a `FEFAT_DATA_DIR` there loses that guarantee.
- A snapshot reads every file it pins to hash it, and a request selects every partition without a key whatever its dates; both wait in `BACKLOG.md`.
- Phase 2's cache builder reads these files, and the run key includes the snapshot hash.

## How we would know it is wrong

If the same request over the same files gave two different snapshot hashes, on one machine or on Windows and Linux; if a component had to read market data without going through `Store`; or if importing real files needed a column or a partitioning that this layout cannot hold without rewriting stored data.

## Status

Accepted; recorded in step 1.1.
