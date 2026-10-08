# Decision log

Decisions made during planning (2026-10-05/06). Step 0.7 turns the ones marked **ADR** into records under `docs/adr/`. A decision is superseded by a new entry, never edited.

| ID | Decision | Why | Consequences |
| --- | --- | --- | --- |
| D-01 | Personal tool now; commercial version later also runs on the customer's own machine | Cost ($0/month), simplicity for a builder new to DevOps, privacy of strategy code | No multi-tenant infrastructure; workspaces and seams keep a thin cloud possible later |
| D-02 **ADR** | Local-first: FEFAT never hosts or ships market data | Hosting CME data for customers needs exchange licences (≈$21k–130k/yr); Databento licenses internal use only | Customers bring their own data and keys; the importer and data folder are per machine |
| D-03 **ADR** | Web UI (React) over a desktop-ready local backend; packaged with Tauri last | Same UI for browser, phone, and desktop window; packaging is the fiddliest part and is done once the app is stable | Backend is one process, SQLite, files, no Docker, configurable port |
| D-04 | Native Windows development | The product's primary platform is Windows; one environment; Tailscale and data already on this side | MSVC build tools needed; hooks as Node scripts; permission rules for PowerShell and Bash; CI also on Linux |
| D-05 **ADR** | Rust engine core, Python SDK, Polars for user code | Per-tick work in Rust; the builder works in Python; Polars gives speed and a safer expression API | PyO3/maturin wheels; Arrow zero-copy interchange |
| D-06 **ADR** | Two strategy kinds on one engine: signal strategies first, event strategies later | Signal strategies need no Python in the hot loop (fast, builder-generated); event strategies cover path-dependent logic | One `ExitPlan` in Rust serves both; parity tests between the two kinds |
| D-07 **ADR** | Decisions at bar close; fills on the finest data inside the bar; conservative defaults; every fill tagged with fidelity | "Quick and highly accurate" without tick-level strategy logic | Fill specification document; scenario tables; fidelity split in reports |
| D-08 **ADR** | Engine clock is Databento `ts_recv` | Databento buckets its bars on it; both tick and bar eras must share one clock | Ingest asserts ordering; NautilusTrader comparison uses the same convention |
| D-09 **ADR** | Continuous futures series are forward-anchored; execution on the actual contract | Back-adjustment rewrites history at each roll, invalidating caches and tripping the leak detector | `close`, `close_raw`, `adj_offset`, `contract` columns; back-adjusted series for display only |
| D-10 **ADR** | The reviewable truth is a plain-language fill spec, scenario tables, and a slow Python reference engine; Rust must match exactly | The builder will not review Rust; correctness must come from tests the builder can read | Differential tests with Hypothesis; `run.explain` replays through the reference |
| D-11 **ADR** | Deterministic, pinned, hashed runs; immutable versions | Reproducibility and version control of strategies and backtests | Run hash dedupes submissions; goldens change only with approval |
| D-12 **ADR** | Leak detector by prefix invariance, run on save | Look-ahead is the most common silent error in feature research | Features declare inputs and warm-up; alt data carries `available_at` |
| D-13 **ADR** | Prop rules as versioned data with sources and worked examples; exact mode plus fast replay that must agree | Rules change often; replay enables Monte Carlo at scale | Preset files with as-of dates; `replayable` flag; equivalence tests |
| D-14 **ADR** | In-app agent on the Messages API (Python), tools from one registry, proposals for consent, skills as files | Pure Python runs on Windows and macOS with the customer's own key; the Agent SDK has no Windows wheel; consent must be a product object, not a blocking callback | `AgentRuntime` seam; append-only transcript; no shell/file/web tools |
| D-15 | SQLite + Parquet + DuckDB for all persistence | Zero-setup single-file state is right for a desktop app; columnar files for data and results | Alembic batch mode; files under `FEFAT_HOME` |
| D-16 | Jobs in a local process pool; user code in subprocesses with limits | Crash containment and parallelism on 16 cores; no security boundary needed locally | Executor seam for a future container runner |
| D-17 | Phone access over Tailscale with its HTTPS certificate; web push from the local server | Free, private, installable PWA with notifications; no cloud | Works only while the PC is on; cloud sync is in the backlog |
| D-18 | Engine first, then the app; prop simulator before the in-app agent | Trustworthy notebook backtests early; the simulator is the most distinctive feature; Claude Code stands in as coding assistant meanwhile | Milestones: notebook backtest ~step 19; web MVP ~step 57 |
| D-19 | Masterplan as Markdown in the repo with a `/step` runner | Claude Code reads it directly; git tracks it | Step IDs are stable; kickoffs reconcile |
| D-20 | Machine-learning models on features deferred | Rule-based strategies first; the feature store and engine leave room | Backlog item with a sketch |
| D-21 | Test data policy: synthetic fixtures only in git; licensed data under `FEFAT_DATA_DIR` | Databento licence; repository hygiene | Commit guard, hook, CI job |
| D-22 | `just` as the task runner; project scripts in Python (through `uv run python`); Claude Code hooks as Node scripts; no shell scripts except the one-line git hook launcher | Same commands on Windows, CI, macOS; Node is the one interpreter present everywhere for hooks | `justfile` at the root |
| D-23 | Default agent model `claude-opus-5-5`; Sonnet 5.5 as cheap mode; caps per turn, day, month | Quality by default, cost under control | Price table in config; usage ledger |

Open decisions, by the phase kickoff that settles them: data purchase (P1), fill defaults sign-off (P2), primary phone (P4), first prop plans (P7), agent model and monthly cap (P8), holdout period (P11), shell and signing choices (P14).
