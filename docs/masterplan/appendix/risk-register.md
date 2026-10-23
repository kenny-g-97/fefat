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
| R7 | Prop replay cannot know how a strategy would have reacted to account state (for example re-entries after a forced cut), and imported trade logs may lack intrabar detail | Optimistic or pessimistic prop results | Replay notes on every result (trades after forced cuts counted); path fidelity shown; conservative treatment of `excursions` and `close-only` logs, tested never to pass what the full path fails; enrichment from stored market data | P7 |
| R8 | Look-ahead in features | Strategies that only work in backtests | Leak detector on save; `Label` type for forward returns; `leakage-auditor` | P3 |
| R9 | Agent harness mistakes (edited history, forced tool choice, refusals) | 400 errors, broken sessions | Append-only transcript; the `claude-api` skill as the reference; replay tests; refusal handling | P8 |
| R10 | Prompt injection through uploads | Agent acts on hostile instructions | No web tools; proposals for every write; untrusted-data labelling; injection tests | P8, P10 |
| R11 | Windows-specific breakage in Claude Code (hooks, paths, shells) | Lost sessions, blocked tools | Node-script hooks; PowerShell/Bash rule twins; hook smoke tests; CI on Linux as a second opinion | P0 |
| R12 | Packaging Python + Rust + web into installers | Product phase stalls | Desktop-ready backend from day one; packaging decision record; clean-machine tests | P14 |
| R13 | Local server reached from another device with weak auth | Unauthorised access to the PC | Localhost only until the phone item (D-53); Argon2 passwords; CSRF; rate limits; security review | P4, P13 |
| R14 | Phone usability (charts, editor, forms) | Phone pillar fails | Deferred with the phone item (D-53); when it returns, phone size becomes an acceptance check in every UI step, with agent-first editing and the `ui-verifier` | phone item |
| R15 | Cost blowups (Claude Code during the build; the in-app agent) | Budget overrun | Model hints; caps per turn/day/month; usage ledger; no multi-agent workflows by default | all |
| R16 | Data loss (SQLite file, artifacts) | Lost work | `fefat backup`, scheduled local backup, restore drill | P13 |
| R17 | Dependency churn (Polars, pyo3, Vite majors) | Build breaks | Lockfiles and toolchain pins; one upgrade step per phase exit | P0 |
| R18 | Plan drift over 134 steps | Steps no longer match the code | Kickoff reconciliation; amendments; `step-reviewer` | all |
| R19 | Platform data for customers cannot be licensed at an acceptable cost (CME futures: at least about $127k a year at 2026 fee levels; crypto: no priced redistribution licence found) | The commercial version ships without some platform products | Licence status per product in `docs/platform-data-licensing.md`; the pack builder refuses unlicensed products and internal-use datasets; managed sync with the customer's own vendor account as the fallback, then import-only; decided at the Phase 14 kickoff, before any build work | P14 |
| R20 | `main` is unprotected on GitHub's free plan (D-30) | A merge with failing checks or a direct push breaks `main` | Squash-only merging; the merge routine in `05-build-process.md` §8; Claude Code's hooks deny its own pushes to `main` and force pushes (0.4); CI on every pull request (0.6); upgrade to GitHub Pro if a bad merge ever happens | P0 |
| R20 | Imported data with wrong time zones, bar stamping, instrument specifications, or back-adjusted continuous prices | Wrong backtests on imported products | Import preview; calendar check that reports the detected offset; series type in the profile with warnings on continuous series; quality report; saved, tested presets | P1, P5 |
| R21 | Saved runs too large because every run stores trade paths | Disk use grows, especially for multi-day holds (a mark for every minute in a position) | Compressed paths, measured for intraday and multi-day runs in step 2.13; sweep trials keep paths only when saved as runs | P2 |
| R22 | Trade paths missing information a prop rule needs | Prop results silently wrong for every run saved after step 2.13 | Restart of tracking at every minute boundary and fill; the probe test in 2.13 (the questions prop rules ask, compact versus full path); the replay-versus-reference test in 7.3 | P2, P7 |
