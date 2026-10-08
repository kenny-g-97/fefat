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
