# Phase 3 demo: the feature system

What Phase 3 built, shown in about thirty minutes without reading code. Run everything in PowerShell from the repository folder, `C:\Users\<you>\Documents\AlgoTrading_app\FEFAT`, on `main` after the exit pull request is merged: `git switch main`, then `git pull --ff-only`, then `just setup` once, since the exit moved the lockfiles. Actions 1 to 3 are the everyday commands, 4 to 6 the feature system on your own MES data, and 7 to 13 check what the exit changed. No action prints a price of your data: the notebooks print counts, dates, coefficients, and ticks.

What the exit changes on your PC: the feature cache under `%LOCALAPPDATA%\FEFAT\cache\features\` computes each feature again once, since its keys cover the SDK's code, which the exit changed; the versions in your library keep their numbers and hashes, since no feature's own code changed; nothing in your data store changes.

1. **Check the tools.** Run `just doctor`.
   It prints the table of eleven tools, each `OK` with its version, and ends with `All 11 tools OK on Windows (AMD64).`

2. **Run every check.** Run `just check`.
   It ends with `OK` after the masterplan checker, in under a minute. Since the exit it runs whole on this PC: ruff leaves out the untracked `.agents\` and `.codex\` folders, which belong to another tool, where every step of the phase ran the recipe's lines one by one.

3. **Run every test.** Run `just test`; it takes about eleven minutes.
   Three lines matter: `2670 passed` from pytest, `All 274 hook cases passed.` from the Claude Code guards, and the `test result: ok.` lines of the Rust tests, 267 in all. No line says `FAILED`.

4. **The features notebook.** Open `notebooks/03-features.ipynb` in VS Code, pick the `.venv` kernel (Python 3.12) at the top right, and click _Run All_; it takes a few seconds. Each markdown cell says what its code cell should print; the ones to watch, with what they printed on your store at the exit:
   - the setup prints `MES 5-minute bars from 2026-06-24 to 2026-09-23` and the hash of `close_location`, the feature the notebook writes;
   - the leak detector prints `PASSED`, `cuts: none of 76 fails` (a number or so either way, since its random cuts come from a new seed each time), the start check agreeing, and `lint: no finding`;
   - the combination `rsi_stretch` prints `17,868 bars, 0 of them without trades`, the two calls' times, about 1.0 s and 0.13 s, and `the second read the same values: True`: the second call read the feature cache;
   - the quantile table of `rsi_stretch` at 1, 5, and 20 bars, each quantile's mean in ticks with its interval, almost all of them crossing 0, then the same at 20 bars as a plot;
   - the information coefficient of `rsi_stretch` and of `close_location`, by horizon and by year: at one bar their t-statistics are -2.70 and -2.45, beyond 2 but not beyond the 2.64 the trials line asks once six feature-horizon pairs are examined, so neither is evidence of an edge;
   - the clusters: `close_location` and `rsi` together, correlating at 0.91, and `rsi_stretch` alone;
   - the event study of `oversold`, RSI under 30, for a long: 209 events, the mean and median return 1 to 20 bars after, and the excursions against and for the position;
   - the trials line: `3 features and 20 horizons examined, 26 feature-horizon pairs; a t-statistic beyond 3.10 either way keeps 5 % significance across them.`
   Run All writes into your FEFAT folder: the leak detector's report beside the versions of `close_location` and the features' values in the feature cache, which a second Run All reads. If VS Code saved the notebook with its outputs, run `just strip-notebooks` before any commit.

5. **A combination from your library in a backtest.** Open `notebooks/checks/3.07.ipynb` and click _Run All_. It builds `rsi_stretch`, prints its code and its description, validates it (`PASSED`, reading `rsi {'n': 14}`), saves `rsi` and `rsi_stretch` in your library, or finds the versions step 3.7's check saved, and runs a strategy of them on MES from 2026-09-09 to 09-23: `286 trades`, the versions the run names, and `PASSED`; then an identical run opens the first, the second time the shorter, and `PASSED` twice.

6. **The cache at work.** Run `uv run fefat cache features`.
   It prints a line for each folder of the feature cache: MES's 5-minute bars and each feature with its parameters, the partitions, the months they span, their size, and when they were last used. `uv run fefat cache features --prune` removes the partitions unused for 30 days.

7. **Exit check: a daily EMA(200) runs.** Run:

   ```text
   uv run pytest python/tests/test_backtest_run.py -k daily_ema -q
   ```

   It prints `1 passed`. Before the exit every run of a daily EMA(200) was refused with `Expected a trade date of cme-equity-index before 2010-01-04`: a run counts its features' warm-up back twice, and 2,600 sessions counted twice passed the session table's start in 2010. Now the warm-up stops a week after that start, and the average stays empty until it has its 2,600 bars.

8. **Exit check: what the leak detector now sees.** Run:

   ```text
   uv run pytest python/tests/test_features_validation.py -k "opening_windows or weekly_memory" -q
   ```

   It prints `2 passed`. Before the exit, a feature showing its opening half hour's high from the session's first bar passed every cut, since the cuts around a close keep each session whole or not at all; now each session's first bar is cut too. And an average over the week that declares no warm-up passed the start check, since the window's middle date opened its week; the check now also starts a session later.

9. **Exit check: the lint.** Run:

   ```text
   uv run pytest python/tests/test_features_lint.py -k "standard_library or another_name" -q
   ```

   It prints `2 passed`: a feature reading a database through `sqlite3` or a web page through `urlopen`, and one computing the labels under another name, now fail their validation.

10. **Exit check: no price in the leak report's words.** Open `notebooks/checks/3.04.ipynb` and click _Run All_.
    The first report's second line ends `differs, with the data after the cut against without it: a value against null`. Before the exit it printed the next bar's close there, a price of your data, which a session reading the output would have seen; the report still keeps both values for the app's feature page of step 6.4.

11. **Exit check: loads and runs the reviews fixed.** Run:

    ```text
    uv run pytest python/tests/test_market_api.py python/tests/test_backtest_run.py -k "no_one_minute_bars_decide or contract_run_reads_another" -q
    ```

    It prints `4 passed`. A load without a fidelity, and `compute`, again refuse a session that your trades hold after the last session your 1-minute bars decide a front for, where since step 3.2 they left it out without a word; and a backtest of one contract whose feature reads another instrument runs on a store holding that contract's trades alone.

12. **Exit check: `==` in a combination.** In a new notebook cell, run:

    ```text
    from fefat.features import combine
    close, high, opened = combine.column("close"), combine.column("high"), combine.column("open")
    (close == high) | (close > opened)
    ```

    It stops with `ValueError: Expected a term of a combination, got False: a bare flag is refused, since == and != compare terms as Python objects, not bar by bar`. Before the exit it gave a combination whose first condition was gone, so a candle closing at its high was never found.

13. **Exit check: the reviewers are still read-only.** Start a new Claude Code session and type: _Run the step-reviewer subagent and ask it to run `printf probe`, then report what happened._
    The reviewer reports `Reviewers are read-only: "printf probe" is not on the read-only list.`: the hook knows the agent as a reviewer and checks its every command.

Afterwards, tag the phase as the exit pull request describes: `git tag phase-3`, then `git push origin phase-3`.
