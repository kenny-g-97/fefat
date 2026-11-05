# Phase 2 demo: the backtest engine

What Phase 2 built, shown in about forty minutes without reading code. Run everything in PowerShell from the repository folder, `C:\Users\<you>\Documents\AlgoTrading_app\FEFAT`, on `main` after the exit pull request is merged: `git switch main`, then `git pull --ff-only`, then `just setup` once, since the exit moved the lockfiles. Actions 1 to 3 are the everyday commands, 4 and 5 the engine on your own MES data, 6 to 8 the validation reports, and 9 to 12 check what the exit changed. Only action 5 prints prices of your data, on your screen, as it is meant to; nothing it prints is committed.

1. **Check the tools.** Run `just doctor`.
   It prints the table of eleven tools, each `OK` with its version, and ends with `All 11 tools OK on Windows (AMD64).` `cargo-mutants 27.1.0` is the tool Phase 2 added.

2. **Run every check.** Run `just check`.
   It ends with `OK` after the masterplan checker. If it stops at `ruff check` on a file under `.agents\`, that folder belongs to another tool, not to FEFAT, and the exit ran the same checks with `uv run ruff check . --extend-exclude .agents,.codex` and the lines after it one by one.

3. **Run every test.** Run `just test`; it takes about ten minutes.
   Three lines matter: `2017 passed` from pytest, `All 273 hook cases passed.` from the Claude Code guards, and the `test result: ok.` lines of the Rust tests, 267 in all. No line says `FAILED`. On the way the four differential tests print how many generated tapes and templates went through both engines, each with its seed.

4. **The engine tutorial.** Open `notebooks/02-engine-tutorial.ipynb` in VS Code, pick the `.venv` kernel (Python 3.12) at the top right, and click _Run All_. Each markdown cell says what its code cell should print; the ones to watch:
   - the setup prints `MES from databento: 2021-09-24 to 2026-09-23`;
   - the run prints `Ran in … s` and `Fidelity 1m: 1,257 trade dates from 2021-09-24 to 2026-09-23`: about 9.5 s on this PC with the engine's cache built. A second _Run All_ reads the saved run back at once; for a fresh timing, delete the folder the cell prints first;
   - the report shows the fidelity eras, 7,753 trades, the metrics, the robustness verdict, and why there is no fidelity check: every trade date ran at one minute;
   - _One trade explained_ shows the first trade stopped out at a loss, one line per event with the rule behind it in brackets: the entry, its stop and target placed (F-OCO-02), the stop's fill on the 1-minute bar that reached it (F-STP-04) with its slippage, and the target cancelled (F-OCO-01). Since the exit the cell shows these lines as a display rather than printed text, so that a check that runs the notebook and keeps its printed text sees no price;
   - _Its path_ draws the trade's path in ticks from its entry and prints `The path of trade 1: 65 points`, then the points by kind;
   - _How much the fills depend on the data_ runs the generated year of 252 sessions with its fidelity check in about 11 s: `Baseline on trades: 1956 trades`, then the reruns at 1 second and at 1 minute, each two trades fewer;
   - _A few variants_ prints `Variants: 9 runs in …` (about 27 s) and shows their table.
   If VS Code saved the notebook with its outputs, run `just strip-notebooks` before any commit.

5. **Explain a trade of your choice.** Add a cell at the end of the tutorial and run:

   ```text
   run.explain(int(run.trades["entry_order"][1]))
   ```

   It prints the run's second trade replayed through the reference engine, FEFAT's slow, readable engine: every event with its rule, every fill with its rule, liquidity, and slippage in ticks, and on bars the open, high, low, and close of the bar that filled it. Had the two engines filled the trade differently, it would stop with `EnginesDisagreementError` instead.

6. **The tick check on your IBKR prints.** Run `just tick-check`; it takes about a minute and a half and prints `Checking MNQZ2026 on 3 ibkr sessions`, then `Wrote …\docs\validation\ibkr-tick-check.md`. `git diff` shows at most the replay's time changed. In the report:
   - the bars rebuilt from the prints equal IBKR's on 2026-09-21 and 09-22, and 2026-09-23 differs in its 20:59Z bar alone, where IBKR's Time and Sales holds one print more than its own bar, so that session runs on its bars;
   - the reference engine's fills equal the Rust engine's: 242, 224, and 236 on prints;
   - `None of the 1,976,277 prints sits at one of the 552 decisions' instants`, and no difference is `bar_boundary`: 97.5, 92.0, and 89.8 % of the three strategies' matched trades are alike on prints and on bars, and the rest are `bar_path`, `entry_bar_path`, or `stop_through`, none `unknown`;
   - every hash check reads `equal`.

7. **The cross-check against other engines.** Open `docs/validation/nautilus-comparison.md`: the three strategies on MES in August 2026 against NautilusTrader under both of its bar paths, and the market strategy on MNQ against your NinjaTrader 8 export, every differing fill with a class and none `unknown`. `just xcheck` runs it again in a few minutes, and `just xcheck-tests` runs the cross-check project's own tests, 39 of them, then its type check.

8. **The engine's speed.** Run `just bench`; it takes a few minutes. Compare its medians with `docs/validation/benchmarks.md`: about 0.8 s for the generated year with trade paths, 0.2 s without, and 0.85 s for 1,000 variants of its first month.

9. **Exit check: your prints sit at the end of their second.** Run:

   ```text
   uv run python -c "import os, polars as pl; from fefat.config import resolve_paths; folder = resolve_paths(os.environ).data_dir / 'ibkr' / 'trades' / 'root=MNQ' / 'contract=MNQZ2026'; [print(day, pl.scan_parquet(folder / f'date={day}' / 'part.parquet').select(prints=pl.len(), at_the_end=(pl.col('ts_recv') % 1_000_000_000 == 999_999_999).sum()).collect().row(0)) for day in ('2026-09-21', '2026-09-22', '2026-09-23')]"
   ```

   It prints `2026-09-21 (976389, 976389)`, `2026-09-22 (999888, 999888)`, and `2026-09-23 (1069604, 1069604)`: every print of each session is stored at its second's last nanosecond. Before the exit the second number was 0, and a print stamped 14:30:00 came before the decision at 14:30:00 although it may have arrived after it. Your first import of these files is kept under `%LOCALAPPDATA%\FEFAT\backup\phase-2-exit\`; once you are content, you may delete that folder.

10. **Exit check: what the engine's tests catch.** Open `docs/validation/mutation-testing.md`, then run `just mutants -f crates/fefat-engine/src/tick_run/fills.rs -j 4`, about two minutes. It ends with `37 mutants tested in …: 6 missed, 29 caught, 2 unviable`: cargo-mutants runs the engine's own Rust tests alone, and the report shows that each of those six fails a scenario table, which pytest runs through both engines.

11. **Exit check: a span of minutes past the clock's end never fires.** Run:

    ```text
    uv run pytest python/tests/test_rust_engine_scenarios.py -k "S-template-082 or S-template-083" -q
    ```

    It prints `4 passed`. Before the exit the Rust engine closed a position with `max_minutes: 200000000` at the next decision, and entered during a cooldown that long, since the minutes overflowed; the reference engine never did.

12. **Exit check: the reviewers are still read-only.** Start a new Claude Code session and type: _Run the step-reviewer subagent and ask it to run `printf probe`, then report what happened._
    The reviewer reports `Reviewers are read-only: "printf probe" is not on the read-only list.`: the hook knows the agent as a reviewer and checks its every command.

Afterwards, tag the phase as the exit pull request describes: `git tag phase-2`, then `git push origin phase-2`.
