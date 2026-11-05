# Phase 1 demo: the market-data layer

What Phase 1 built, shown in about twenty minutes without reading code. Run everything in PowerShell from the repository folder, `C:\Users\<you>\Documents\AlgoTrading_app\FEFAT`, on `main` after the exit pull request is merged: `git switch main`, then `git pull --ff-only`, then `just setup` once, since the exit moved the Rust pin and the lockfiles. Actions 1 to 4 are the everyday commands, 5 to 7 the data layer on your own store, and 8 to 10 check what the exit fixed. No action prints a price: the commands print counts, dates, and summaries only.

1. **Check the tools.** Run `just doctor`.
   It prints the table of ten tools, each `OK` with its version, and ends with `All 10 tools OK on Windows (AMD64).` rustc and cargo now show `1.99.1`, the version the engine pins since the exit; the first `cargo` run in `engine/` installed it.

2. **Run every check.** Run `just check`.
   It ends with `OK` after the masterplan count (`P14: 9 steps`). On the way you see the data guard's line, `Data guard: git's index holds no market data outside fixtures/synthetic/ …`.

3. **Run every test.** Run `just test`.
   Three lines matter: `1052 passed` from pytest, `All 252 hook cases passed.` from the Claude Code guards, and `test result: ok. 8 passed` from the Rust tests. No line says `FAILED`.

4. **The source guide.** Run `uv run fefat data sources`.
   It lists 27 sources, each with what it offers, its cost, its terms, and the preset that reads its files (`available` for seven of them: Databento's CSV and DBN exports, Interactive Brokers, NinjaTrader 8, TradingView, Sierra Chart, and TradeStation).

5. **Your store's status.** Run `uv run fefat data status`.
   Five lines: `MES databento ohlcv-1m: 2019-05-06 to 2026-09-23, complete at 1-minute fidelity, last import 2026-10-13, quality clean through 2026-09-23`, the same shape for MNQ (twice: `databento`, clean, and `ninjatrader`, flagged, to 2026-09-18), MCL (clean), and MGC (flagged, four days without bars in 2014).

6. **The notebook.** Open `notebooks/01-market-data.ipynb` in VS Code, pick the `.venv` kernel (Python 3.12) at the top right, and click _Run All_. Each markdown cell says what its code cell should print; the ones to watch:
   - the catalog status repeats action 5;
   - the year of continuous MES 5-minute bars prints about 71,000 bars in a few seconds, no bar whose close is not `close_raw + adj_offset`, and four rolls in the week of each quarterly expiry;
   - the comparison with the vendor's bars prints `Differences: none.`;
   - the tick rebuild prints that it skips, since no trades file is in the store yet;
   - the NinjaTrader MNQ import prints the last week of MNQU2026 and a quality report flagged for the sessions its three refused contracts covered.
   If VS Code saved the notebook with its outputs, run `just strip-notebooks` before any commit.

7. **The data guide.** Open `docs/data-guide.md`: where your data is, which sources are suggested, how to import Databento files and your own exports, and how to read the status and quality reports. The import section now says what the exit changed in the store's rules: a second import of a file with another profile, contract, root, or time zone is refused, and a daily import warns that each bar is stored as its whole session.

8. **Exit check: a re-import with other arguments is refused, not passed over.** Run:

   ```text
   uv run fefat data import file "C:\Users\<you>\Documents\AlgoTrading_app\market_data\NT8_data\raw\MNQ 09-26.Last.txt" --profile ninjatrader --contract MNQU2026
   ```

   It stops with `fefat: Expected … to be imported as it was on 2026-10-20, import profile ninjatrader, got import profile ninjatrader, contract MNQU2026: a stored dataset never changes, so the first import stands.` Before the exit this printed `Nothing to import … it is imported already`, and a corrected time zone could never reach the store. Without `--contract` the command still says the file is imported already.

9. **Exit check: the day after Thanksgiving closes at 12:45 for metals and energy.** Run:

   ```text
   uv run python -c "import fefat as ff; from fefat.market.calendar import utc_text; bars = ff.market.load('MGC', '1h', '2022-11-25', '2022-11-25').collect(); print(bars.height, 'bars, last close', utc_text(bars['ts_close'].max()))"
   ```

   It prints `41 bars, last close 2022-11-25T18:45:00Z`: 12:45 Chicago time, where MGC's last bar of that Friday really closes. Before the exit the calendar closed the session an hour later, at 13:45, for every year before 2024, and the last hour was a row of empty bars.

10. **Exit check: a window without bars is refused.** Run:

    ```text
    uv run python -c "import fefat as ff; ff.market.load('MES', '5m', '2019-05-06', '2019-05-06')"
    ```

    It ends with `ValueError: Expected bars of MES from 2019-05-06 to 2019-05-06 in the store, got none.`: the dataset's first session has no front contract yet. Before the exit the same call returned an empty frame, and a notebook could compute over nothing without an error.

Afterwards, tag the phase as the exit pull request describes: `git tag phase-1`, then `git push origin phase-1`.
