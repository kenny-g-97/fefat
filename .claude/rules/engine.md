---
paths:
  - "engine/**"
---

# Engine rules (Rust)

From `docs/masterplan/08-code-design.md` §1 and §3.1–§3.2, and `docs/masterplan/02-engine-and-data.md` §4 and §8. Load the `backtest-expert` skill before changing fills, costs, accounting, metrics, or prop logic.

- **Determinism.** No wall clock and no unseeded randomness anywhere: time arrives through an injected clock, randomness through an explicit seed. One thread per run. Wherever order reaches output, use ordered collections (`BTreeMap`, sorted `Vec`), never hash-map iteration.
- **Integers for money.** Prices, quantities, money, and timestamps are newtypes (`Price`, `Qty`, `Money`, `Ts`) over `i64` with checked arithmetic: prices in 1e-9 units, money in micro-units of the account currency, time in nanoseconds since the Unix epoch, UTC. Floats appear only at the SDK boundary.
- **States are enums.** Order, position, account, and fidelity states are enums; a state transition is a function from one variant to another, never a combination of optional fields.
- **Errors.** `thiserror` types that carry the expected value, the actual value, and the context. Data anomalies become run-log warnings, fatal under `strict`.
- **Lints.** Core crates deny `unwrap_used`, `expect_used`, `panic`, `indexing_slicing`, and `undocumented_unsafe_blocks`; every `unsafe` block carries a `// SAFETY:` note. `fefat-data` is the only crate with `unsafe`.
- **Dependency rule.** No I/O outside `fefat-data`, `fefat-py`, and `fefat-cli`. `fefat-core` defines the `MarketDataReader` trait, `fefat-data` implements it over mmap, tests implement it in memory. `MarketDataReader` and `AccountModel` are passed in by the caller: generics in hot loops, `dyn` elsewhere. No engine crate depends on `fefat-data` except `fefat-py` and `fefat-cli`.
- **Scenarios are the specification.** Every behaviour change comes with scenario rows in `fixtures/scenarios/` (a hand-computable tape, the orders, the expected fills) that name the rule identifiers of `docs/spec/fill-semantics.md`; the Python reference engine must agree exactly. A test is never fixed by editing an expected value.
- **Goldens.** Golden runs and insta snapshots change only through the `engine-golden` skill: the builder's approval first, then `just regenerate-goldens`, then a changelog entry (and a fill-model version bump when fills change).
- **Small units.** Functions under about 40 lines, nesting at most three levels, early returns. The engine loop may be longer where a scenario table documents each branch.
- **Comments.** Rustdoc on public items, citations (`// S-fill-012`, `// F-MKT-01`, `// ADR-0007`), and `// SAFETY:` notes; no narrative comments.
- **Checks.** `just check` runs `cargo fmt --check` and `cargo clippy -D warnings`; `just test` runs `cargo test`. The toolchain is pinned in `engine/rust-toolchain.toml`; upgrades happen only in the upgrade step of a phase exit.
