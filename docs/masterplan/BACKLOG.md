# Backlog — future improvements

One line per item: what, why, where it came from. Claude Code adds items here instead of doing them inside a step. Groomed at every phase exit.

## Product

- **Cloud sync (thin service)** — phone access while the PC is off: accounts, sync of strategies/features/run summaries, remote job queue. Source: hosting decision (D-17). Needs: `BlobStore` and `Dispatcher` seams, licence check.
- **Machine-learning models on features** — labeling, training with walk-forward validation and leakage controls, model registry, inference as a feature or signal source. Source: user decision D-20. Needs: feature store (P3), research tools (P11).
- **Live and paper trading** — same strategy API driven by a live data feed and a broker adapter; prop-firm connections. Source: product idea. Not planned; the strategy API must not block it.
- **Store apps (Capacitor/TWA)** — App Store and Play Store presence for the phone client. Source: mobile decision. After P14.
- **Licence keys and telemetry opt-in** — commercial version. Source: D-01. `licence.check()` seam exists.
- **Multi-workspace** — several workspaces per install (per strategy family or per client). Schema already has `workspaces`.
- **Python hooks for prop strategies** — custom prop strategies as Python callbacks. Source: `03-prop-simulator.md` §5.
- **Portfolio prop simulation** — several backtest files (strategies or instruments) in one prop account, on one timeline; needs a rule for the order of extremes across instruments within a minute. Source: `03-prop-simulator.md` §4.5.
- **More platform products** — beyond the first catalog (other CME products, more crypto pairs), each needing a distribution licence for customers. Source: D-24.
- **More import presets and vendor connectors** — Massive (Polygon) futures, FirstRate bars, Kraken/Coinbase/Hyperliquid crypto, broker export reconciliation formats, more trade-log layouts for the prop simulator. Source: steps 1.10 and 7.5.
- **Billing and customer accounts for the platform data service** — beyond the entitlement token of step 14.7. Source: D-24.
- **News-window checks for prop rules** — flag trades inside firms' news windows using an economic-calendar dataset (Phase 10). Source: `03-prop-simulator.md` §4.5.
- **Prop simulation that re-runs a strategy inside a prop account** — deliberately excluded by D-25 (simulations read existing backtest files); revisit only if account-aware strategies become common.
- **More prop presets** — the remaining firms in `appendix/research-prop-firms.md`; forex/CFD firms.
- **Agent web tools** — a controlled `fetch_url` for alt-data discovery, behind an allowlist and the untrusted-data labelling. Source: `04-agent.md` §3.
- **Agent SDK or Managed Agents runtime** — alternatives behind `AgentRuntime` if hosting ever makes sense. Source: `appendix/research-agent-surfaces.md`.
- **Order-book (L2) data and queue-position fill model** — only if strategies ever need it. Source: user decision (no L2 strategies).

## Engineering

- **Container-based executor** — if FEFAT ever runs untrusted code for other people. Source: `01-architecture.md` §10.
- **macOS and Linux credential stores** — `keyring` backends beyond Windows. Needed by P14 for macOS.
- **GPU or distributed sweeps** — not needed on 16 cores; revisit if studies routinely exceed hours.
- **Tick-reactive strategies** — out of scope by decision; would need a different callback model.
- **Formatter for web files** — the `format-on-edit` hook formats Rust and Python; web files wait for the choice between prettier and oxfmt (create-vite 9 scaffolds oxlint, while `.vscode/settings.json` names the Prettier extension). Target: Phase 4 kickoff. Source: step 0.4.
- **TypeScript language server on Windows** — `typescript-language-server` is an npm `.cmd` shim, which a program can start only through a shell; if Claude Code reports that the `typescript-lsp` server failed to start, add a project plugin that runs its `lib/cli.mjs` through `node`. Target: Phase 4 kickoff. Source: step 0.4.
- **Guard edits of scenarios and the fill specification** — ask before an existing file under `fixtures/scenarios/` or `docs/spec/fill-semantics.md` changes (new files stay free), so an expected value never moves silently; decide once the scenario format and the authoring steps exist. Target: Phase 2 kickoff. Source: engine-accuracy-reviewer, step 0.4.
- **The pinned Rust toolchain in `just` recipes** — rustup picks the toolchain from the current folder, so `cargo --manifest-path engine/Cargo.toml` run from the repository root ignores `engine/rust-toolchain.toml` and uses the default toolchain (the same today, 1.99.0, until stable moves). Run the cargo recipes from `engine/` (for example with just's `[working-directory]`). Target: 0.6. Source: engine-accuracy-reviewer, step 0.4.
- **Language servers in the doctor** — `just doctor` could report `rust-analyzer`, `pyright-langserver`, and `typescript-language-server`, which the language-server plugins need on PATH. Target: 0.7 or a phase exit. Source: step 0.4.
- **`core.hooksPath` in every clone** — a new clone does not copy this git setting, so it runs no pre-commit guard until `git config core.hooksPath .githooks` is run there; `just setup` could set it, or the README's setup section could say so. Target: 0.7. Source: step 0.3.
- **A reviewer read-only guard that runs** — the reviewers' shell hook sits in each agent's frontmatter, and Claude Code 2.1.295 did not run it: after step 0.4 merged, the `step-reviewer` ran `printf probe > reviewer-probe.txt` and the file was written, though `reviewer-shell-commands.mjs` denies that command when fed it directly (the smoke tests start the script directly, so they cannot catch this). Until then the reviewers are read-only by instruction only. Register the guard in `.claude/settings.json` for Bash and PowerShell, apply it when the hook input's `agent_type` names a reviewer (`agent_id` is present only inside a subagent), add smoke cases with those fields, prove it with a live probe, and record an Amendment under step 0.4. Target: 0.7 or the Phase 0 exit, before Phase 1. Source: step 0.4 post-merge check.
- **import-linter output on Windows** — `uv run lint-imports` fails with a `UnicodeEncodeError` (cp1252 cannot encode its box-drawing characters) when its output goes to the NUL device, so `just check > /dev/null` in Git Bash reports a failure that a normal run does not; `export PYTHONUTF8 := "1"` at the top of the justfile would fix it for every Python recipe. Target: 0.6, before CI captures the output. Source: step 0.5.
- **Plain-text market data** — `.csv`, `.tsv`, `.txt`, `.gz`, `.7z`, and `.tar` files are refused nowhere: 05 §5, `.gitignore`, the Claude Code file hook, and the commit guard share one list of market-data extensions, and a month of bars exported from NinjaTrader or TradingView is a CSV far under 25 MB. Extend 05 §5 and the three lists together (the guard's parity test keeps it equal to the hook's), with room for any fixture CSVs the Phase 1 importer tests commit; `fefat.config` could also refuse a `FEFAT_DATA_DIR` inside a git checkout. Target: Phase 1 kickoff, before imports of your own files. Source: code review and step-reviewer, step 0.5.
- **Secret file names in the Claude Code file hook** — the commit guard and `.gitignore` refuse `.env*` and `*.env` (`.envrc`, `prod.env`), but `guard-file-paths.mjs` still matches only `.env` and `.env.*`; align it, with its smoke tests. Target: with the reviewer guard fix (0.7 or the Phase 0 exit). Source: step-reviewer, step 0.5.
- **Fixture bytes on Linux** — the fixtures are shown byte-identical on Windows only; `test_the_committed_fixtures_are_what_the_generator_writes` first runs on Linux in step 0.6's CI. If pyarrow's Linux wheel writes other bytes, generate on one platform and compare decoded rows elsewhere. Target: 0.6. Source: step-reviewer, step 0.5.

## From the design-skill review (2026-10-09; pulled in at the kickoff of the phase named)

- **Show the robustness summary** — the five-dimension summary and verdict that step 2.11 computes (sample size against 30/100/200 trades, expectancy, risk, robustness, execution realism, red flags), as a small table at the top of the results page. Target: 5.7. Source: D-29.
- **Hypothesis on every strategy** — one sentence stating the edge, required before the first run, shown on every result; the agent's analysis skill asks for it. Target: 5.2, 5.5, 8.8. Source: D-29.
- **Stress profile as one click** — slippage at 1.5× and 2×, worst-case fills (one tick against on every entry and exit), commissions at 1.5×, entry shifted by one bar, run as a batch beside the base run. Target: 5.6, 11.6. Source: D-29.
- **Regime breakdown** — results by volatility tercile and trend state of the instrument itself, beside the year breakdown. Target: 11.4 (and the metrics of 2.11 if the P2 kickoff prefers). Source: D-29.
- **Record of abandoned ideas** — a strategy can be marked abandoned with the breaking point and the lesson, following the skill's case-study framework, so the library keeps the failures too. Target: 5.5. Source: D-29.
- **`ux-copy` pass** — review error messages, empty states, and button labels with the `design` plugin's `ux-copy` skill before the hardening phase. Target: 13.7. Source: D-28.
- **`cargo nextest`** — faster, isolated Rust test runs once the suite grows; `just test` uses `cargo test` until then. Target: Phase 2 kickoff. Source: step 0.2.
