# Phase 0 demo: the foundations

What Phase 0 built, shown in about fifteen minutes without reading code. Run everything in PowerShell (or Git Bash) from the repository folder, `C:\Users\<you>\Documents\FEFAT`, on `main` after the exit pull request is merged: `git switch main`, then `git pull --ff-only`. Actions 1 to 5 are the everyday commands; 6 to 8 check what the exit fixed.

1. **Check the tools.** Run `just doctor`.
   It prints a table of ten tools (git, gh, node, pnpm, uv, python 3.12, rustc, cargo, just, MSVC linker), each `OK` with its version, and ends with `All 10 tools OK on Windows (AMD64).` rustc and cargo show `1.99.0`, the version the engine pins.

2. **Install everything.** Run `just setup`.
   It ends with pnpm's `Done in …`, and no line says `error`. Then run `git config core.hooksPath`: it prints `.githooks`, which means the commit gate is switched on in this clone (setup now does this by itself).

3. **Run every check.** Run `just check`.
   It ends with `OK` after the masterplan count (`P14: 9 steps`). On the way you see the data guard's line `Data guard: git's index holds no market data outside fixtures/synthetic/, no secrets, no files over 25 MB, and no notebook outputs.`

4. **Run every test.** Run `just test`.
   Three lines matter: `152 passed` from pytest, `All 249 hook cases passed.` from the Claude Code guards, and `test result: ok. 8 passed` from the Rust tests. No line says `FAILED`.

5. **Call the engine from a notebook.** Open `notebooks/00-hello-engine.ipynb` in VS Code, pick the `.venv` kernel (Python 3.12) at the top right, and click _Run All_.
   The first code cell prints `EngineBuild(version='0.0.1', target_os='windows', target_arch='x86_64', profile=<BuildProfile.RELEASE: 'release'>)`; the last prints `130`, the number the markdown cell above it works out by hand. The notebook now runs on Polars 2.0.0: `uv run python -c "import polars; print(polars.__version__)"` prints `2.0.0`.
   If VS Code saved the notebook with its outputs, run `just strip-notebooks`: it lists `notebooks/00-hello-engine.ipynb` as cleared, so no output can reach a commit.

6. **Exit check: data under another name is refused.** Copy a fixture under a name that hides what it is, and try to commit it:

   ```text
   Copy-Item fixtures/synthetic/ohlcv-1m/root=ES/contract=ESH2026/month=2026-03/part.parquet notes-es.pq
   git add notes-es.pq
   git commit -m "try"
   ```

   The commit stops with `market data outside fixtures/synthetic/` and `Parquet data under another name`. Before this exit, a `.pq` file went straight in. Clean up with `git restore --staged notes-es.pq`, then delete `notes-es.pq`. If the commit went through instead, the commit gate was off in this clone: undo it with `git reset HEAD~1`, delete `notes-es.pq`, and run `just setup` again.

7. **Exit check: the reviewers really are read-only.** Start a new Claude Code session and type: _Run the step-reviewer subagent and ask it to run `printf probe > reviewer-probe.txt`, then report what happened._
   The reviewer reports that the command was refused with `Reviewers are read-only: ... writes to reviewer-probe.txt`, and no `reviewer-probe.txt` appears in the folder. During Phase 0 this write went through, because Claude Code ignored the guard where it was declared.

8. **Exit check: ordinary work still goes through.** In the same session, ask: _Run `git status` and `just doctor`._
   Both run without a refusal; only `git push` asks for your approval, as before.

Afterwards, tag the phase as the exit pull request describes: `git tag phase-0`, then `git push origin phase-0`.
