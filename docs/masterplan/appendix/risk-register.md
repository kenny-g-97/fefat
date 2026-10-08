# Risk register

Reviewed at every phase exit. "Owner" is the phase where the mitigation is built.

| # | Risk | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| R1 | Fills too optimistic or pessimistic (1-second era, limit orders) | Backtests mislead; prop results wrong | Conservative defaults; fidelity split and `fidelity_check`; reruns at +1 tick; real-fill reconciliation when exports exist | P2, P13 |
| R2 | Rust nobody reviews | Silent numeric errors | Python reference and scenarios as the specification; differential, property, and mutation tests; no-panic, no-unsafe lints; `engine-accuracy-reviewer` | P2 |
| R3 | Prop rules change or are ambiguous | Simulations of the wrong rules | Dated presets with sources and firm examples; `draft`/`stale` status on results; refresh skill | P7 |
| R4 | Overfitting in research | False confidence | Trial ledger, locked holdout, deflated Sharpe, PBO, walk-forward default for prop inputs | P11 |
| R5 | Calendar and roll errors | Wrong trade dates, wrong contracts | Explicit session table validated against data; roll decisions tested against `ES.v.0` | P1 |
| R6 | Vendor data shifts (Databento re-normalised CME history in 2026) | Irreproducible runs | Immutable raw files with manifests; snapshot hashes pinned by runs | P1 |
| R7 | Replay used outside its validity | Wrong prop results | `replayable` flag blocks replay; exact mode fallback; equivalence tests | P7 |
| R8 | Look-ahead in features | Strategies that only work in backtests | Leak detector on save; `Label` type for forward returns; `leakage-auditor` | P3 |
| R9 | Agent harness mistakes (edited history, forced tool choice, refusals) | 400 errors, broken sessions | Append-only transcript; the `claude-api` skill as the reference; replay tests; refusal handling | P8 |
| R10 | Prompt injection through uploads | Agent acts on hostile instructions | No web tools; proposals for every write; untrusted-data labelling; injection tests | P8, P10 |
| R11 | Windows-specific breakage in Claude Code (hooks, paths, shells) | Lost sessions, blocked tools | Node-script hooks; PowerShell/Bash rule twins; hook smoke tests; CI on Linux as a second opinion | P0 |
| R12 | Packaging Python + Rust + web into installers | Product phase stalls | Desktop-ready backend from day one; packaging decision record; clean-machine tests | P14 |
| R13 | Local server exposed on Tailscale with weak auth | Unauthorised access to the PC | Localhost by default; Argon2 passwords; CSRF; rate limits; security review | P4, P13 |
| R14 | Phone usability (charts, editor, forms) | Phone pillar fails | Phone size as an acceptance check in every UI step; agent-first editing; `ui-verifier` | P5–P12 |
| R15 | Cost blowups (Claude Code during the build; the in-app agent) | Budget overrun | Model hints; caps per turn/day/month; usage ledger; no multi-agent workflows by default | all |
| R16 | Data loss (SQLite file, artifacts) | Lost work | `fefat backup`, scheduled local backup, restore drill | P13 |
| R17 | Dependency churn (Polars, pyo3, Vite majors) | Build breaks | Lockfiles and toolchain pins; one upgrade step per phase exit | P0 |
| R18 | Plan drift over 128 steps | Steps no longer match the code | Kickoff reconciliation; amendments; `step-reviewer` | all |
