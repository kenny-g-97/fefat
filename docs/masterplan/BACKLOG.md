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
- **`core.hooksPath` in every clone** — a new clone does not copy this git setting, so it runs no pre-commit guard until `git config core.hooksPath .githooks` is run there; `just setup` could set it, or the README's setup section could say so. Target: 0.5 or 0.7. Source: step 0.3.

## From the design-skill review (2026-10-09; pulled in at the kickoff of the phase named)

- **Show the robustness summary** — the five-dimension summary and verdict that step 2.11 computes (sample size against 30/100/200 trades, expectancy, risk, robustness, execution realism, red flags), as a small table at the top of the results page. Target: 5.7. Source: D-29.
- **Hypothesis on every strategy** — one sentence stating the edge, required before the first run, shown on every result; the agent's analysis skill asks for it. Target: 5.2, 5.5, 8.8. Source: D-29.
- **Stress profile as one click** — slippage at 1.5× and 2×, worst-case fills (one tick against on every entry and exit), commissions at 1.5×, entry shifted by one bar, run as a batch beside the base run. Target: 5.6, 11.6. Source: D-29.
- **Regime breakdown** — results by volatility tercile and trend state of the instrument itself, beside the year breakdown. Target: 11.4 (and the metrics of 2.11 if the P2 kickoff prefers). Source: D-29.
- **Record of abandoned ideas** — a strategy can be marked abandoned with the breaking point and the lesson, following the skill's case-study framework, so the library keeps the failures too. Target: 5.5. Source: D-29.
- **`ux-copy` pass** — review error messages, empty states, and button labels with the `design` plugin's `ux-copy` skill before the hardening phase. Target: 13.7. Source: D-28.
- **`cargo nextest`** — faster, isolated Rust test runs once the suite grows; `just test` uses `cargo test` until then. Target: Phase 2 kickoff. Source: step 0.2.
