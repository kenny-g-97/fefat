# The cross-check against NautilusTrader and NinjaTrader 8

Step 2.14 (`docs/masterplan/02-engine-and-data.md` §8 item 5, D-51, D-59) runs the same three strategies through FEFAT's engine and through NautilusTrader on MES in August 2026 (MESU2026, the front all month, from the store's Databento 1-minute bars), and the market strategy through NinjaTrader 8's Strategy Analyzer on the store's NinjaTrader import of MNQ 09-26, and explains every differing fill. The report is `docs/validation/nautilus-comparison.md`.

This folder is a uv project of its own, outside the workspace: `nautilus_trader` is a test-only dependency (LGPL, 113 MB on Windows), pinned at 1.231.0, the last 1.x release. The root `pyproject.toml` excludes the folder from the workspace, from `uv run pytest`, and from pyright; ruff lints it with the rest.

## Running it

```text
just xcheck      # slow: the real store, the month cut, four FEFAT runs, six Nautilus runs, the report
```

`just xcheck` runs `scripts/xcheck.py` in the workspace environment, which holds the compiled engine:

1. FEFAT's side: the three strategies on MES under the compatibility profile of the fill specification's §19 (touch fills, no slippage ticks, no latency, FEFAT's own bar path), and the market strategy on MNQ from the `ninjatrader` provider; each run's `trades`, `fills`, and signal frame, the 1-minute bars of the window, and `fefat.json` (versions, snapshot, profile, strategies) go under `<FEFAT_HOME>/workspaces/default/xcheck/<comparison>/fefat/`.
2. The month cut: MESU2026's records from 2026-07-30 to 2026-08-31 after the raw batch file's own metadata, as a zstd DBN file beside them, written once per raw file; the raw file is only read.
3. `uv run --project python/tests/external python -m fefat_xcheck nautilus <folder>`: NautilusTrader's side, under `<folder>/engine/`.
4. `… python -m fefat_xcheck report <xcheck folder> <draft>`: the comparison and the report, which exits 1 while any difference is `unknown`; the script copies the draft into `docs/validation/` only then.

Everything derived from licensed data stays under `FEFAT_HOME`; the report holds counts, rates, timestamps, and tick differences.

The project's own tests run on the synthetic Databento batch and on hand-made tables, with no real data and no skips. `just xcheck-tests` runs both lines, and since the Phase 2 exit the Cross-check tests workflow (`.github/workflows/xcheck-tests.yml`) runs it on Ubuntu for any change to this folder:

```text
uv run --directory python/tests/external pytest
uv run --directory python/tests/external pyright
```

## What the comparison does

- Trades are matched on the decision that entered them and their side, as `fefat.backtest.fidelity` matches a rerun's trades. A market fill is compared by its price alone, since its stamp is a convention of its own; every other fill by its price and its bar.
- Each engine's trade is held to a replay of its own documented rules on the 1-minute bars (`fefat_xcheck.replay`: the entry's fill, the rest of the entry's bar, every later bar, the flat-by). A pair both replays give is explained by a class naming where the two sets of rules part: `bar_boundary`, `bar_path`, `entry_bar_path`, `leg_released_through`, `gap_limit_clamped`, and `cascade`; a fill the rules do not give, or a difference no class names, is `unknown`, and the report exits 1 with one. The report explains each class with the rules behind it.
- The levels of the stop and the target come from the signal bar's close in every engine, so that an entry filled at another price leaves the exits comparable.
- Nautilus runs every strategy twice: with its default path (open, high, low, close) and with `bar_adaptive_high_low_ordering` (the extreme nearer the open first).

## NautilusTrader 1.231.0, as installed

Verified on this PC on 2026-10-31 (`inspect.signature` and runs on the synthetic batch):

- `DatabentoDataLoader().from_dbn_file(path, instrument_id=None, price_precision=None, as_legacy_cython=True, include_trades=False, use_exchange_as_venue=False, bars_timestamp_on_close=True, skip_on_error=False, expiration_overrides=None)`. Its Rust decoder reads zstd-compressed DBN only (an uncompressed `.dbn` fails with "Unknown frame descriptor"), maps each record's raw symbol through the file's symbology to `<symbol>.GLBX`, and needs `price_precision` without definition records. Passing `instrument_id` relabels every record of the file, whatever its symbol: the cut holds one symbol, and the loader keeps only the bars of the instrument.
- `BacktestEngine.add_venue(venue, oms_type, account_type, starting_balances, base_currency=None, …, fill_model=None, fee_model=None, latency_model=None, book_type=L1_MBP, …, reject_stop_orders=True, support_contingent_orders=True, …, bar_execution=True, bar_adaptive_high_low_ordering=False, trade_execution=True, …)`; `FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=None)`; `PerContractFeeModel(Money)`.
- `FuturesContract(instrument_id, raw_symbol, asset_class, currency, price_precision, price_increment, multiplier, lot_size, underlying, activation_ns, expiration_ns, ts_event, ts_init, …)`, built by hand from FEFAT's instrument table.
- `DataEngineConfig(time_bars_interval_type="left-open", time_bars_timestamp_on_close=True, time_bars_build_with_no_updates=True, time_bars_build_delay=0, …)`. A composite `…-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL` subscription builds 5-minute bars from the external 1-minute bars on a timer; with `time_bars_build_delay=1` (µs) the 1-minute bar stamped at the boundary joins the bar closing there, which then arrives 1 µs after the boundary (the comparison floors instants to the second); the bucket closing at the data's last bar is never built, since no timer fires after it.
- An order submitted from `on_bar` settles against the book the last 1-minute bar left: a market order fills at that bar's close (`bar_boundary`).
- `OrderFactory.bracket` takes market, limit, and touched entries only, so the strategy builds the order list itself as the factory does: the entry OTO to its legs, the stop-market and the limit OCO to each other, the legs `reduce_only`, the target not post-only; `reject_stop_orders=False` lets a stop through the market fill at once, as F-STP-05 fills it.
- Trades are rebuilt from the cache's filled orders: an entry's fill opens one, the fill of its leg, or of the flat-by's market order, closes it; the OMS is netting, so positions are not read.

## NinjaTrader 8: the runbook (D-59)

NinjaTrader cannot be driven from a script, so its side is a run you do and export; `just xcheck` reads the export when it finds one and writes the report's NinjaTrader 8 section, and says what to run until then.

1. Copy `python/tests/external/ninjatrader/FefatCrossCheck.cs` to `Documents\NinjaTrader 8\bin\Custom\Strategies\`, open the NinjaScript Editor, and compile (F5). On an error, delete the file and compile again: your other strategies keep running on the last good build.
2. Strategy Analyzer, strategy `FefatCrossCheck`: instrument **MNQ 09-26**, data series **Minute, 5**, trading hours **CME US Index Futures ETH** with Break at EOD on, period **2026-07-30 to 2026-08-31** (the strategy enters from its `Trade from` 2026-08-03; the earlier bars feed the previous close), order fill resolution **High, Minute, 1**, slippage **0**, fill limit orders on touch on, exit on session close **off**, time in force GTC, any commission (it is not compared), one contract. The strategy's defaults set these; check the Analyzer's panel shows them. Its parameters: stop and target 40 ticks, window 935 to 1530 and flat-by 1600 on the platform's clock, which is US Eastern on this PC (08:35 to 14:30 and 15:00 Chicago).
3. Run it. In the **Trades** tab, right-click, **Export**, and save the file as `%LOCALAPPDATA%\FEFAT\workspaces\default\xcheck\nt8\export\trades.csv` (the folder `just xcheck` made; any `.csv` there is read, the last by name).
4. `just xcheck` again. The report's NinjaTrader 8 section fills; `notebooks/checks/2.14.ipynb` shows the trades side by side.
5. Delete `FefatCrossCheck.cs` from `Custom\Strategies` and compile again when done.

The reader (`fefat_xcheck.nt8_export`) takes the export's times as the platform's clock, written day first without AM and PM (`03/08/2026 09:36:00`) or month first with them, and its numbers in either culture; a market entry stamped with bar N+1 (the builder's spec, H1) was decided at the close of bar N, one minute before. The stop and the target levels of each trade are the signal frame's, as the strategy sets them from the same close.
