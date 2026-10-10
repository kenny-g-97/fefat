# 08 — Code design: how the design skills shape FEFAT

Written 2026-10-09, before step 0.2 scaffolds the repository, by applying four skills to the plan: the three project skills installed under `.claude/skills/` (`designing-architecture`, `software-design-principles`, `backtest-expert`) and the `frontend-design` plugin skill. The decisions are D-27, D-28, and D-29 in `DECISIONS.md`. Step 0.4 turns §3 and §5 into `.claude/rules/*.md`, and the `step` skill loads the matching skills for each area it touches.

| Area | Skills a session loads | What they decide |
| --- | --- | --- |
| Any new module, crate, package, or seam | `designing-architecture` | the pattern, the dependency rule, the folder layout (§1, §2) |
| Any code: `engine/`, `python/`, `web/`, `scripts/` | `software-design-principles` | names, fail-fast errors, types for states, injected dependencies, small units (§3) |
| Engine, results, research, prop, agent analysis steps | `backtest-expert` | what a trustworthy backtest must show and how FEFAT reports it (§4) |
| Any step that touches `web/` | `frontend-design` | the visual design, built from `web/DESIGN.md` (§5) |

## 1. The architecture decision

The `designing-architecture` workflow, applied to FEFAT.

### 1.1 Requirements and constraints

- Local-first: one process on the trader's PC, SQLite and files, no Docker, packaged as a desktop app later (D-01, D-03, D-15).
- The SDK is the product: anything the app does, a notebook does with `import fefat as ff` (`01-architecture.md` §1).
- Deterministic, pinned, reproducible runs; immutable versions (D-11).
- Three languages with hard boundaries: Rust engine, Python SDK and server, TypeScript web app; Arrow between Rust and Python, OpenAPI between Python and TypeScript.
- One builder plus Claude Code; the builder reads Python and notebooks, not Rust or React.
- Size when complete: medium to large (roughly 20k lines of Rust, 40k of Python, 40k of TypeScript, plus tests), built over 134 steps by many short sessions. The structure must make each session land code in a predictable place.

### 1.2 Options considered

1. **Layered monolith per package** (the plan as first written): folders by technical layer (`server/`, `db/`, `jobs/`) with the seams of `01-architecture.md` §10 named in prose.
2. **Modular monolith with ports and adapters**: the Python SDK is the domain and application core; `fefat_app` is a ring of adapters (HTTP, SQLite, process pool, subprocess, keyring, web push, Anthropic API) around thin application services; the engine crates expose their data access as a trait that the memory-mapped cache implements; the web app is organised by product area. The seams become `Protocol`s and traits with a module of their own.
3. **Event-driven or service-based**: processes talking over queues or HTTP. Rejected outright: FEFAT is one process on one machine, and the plan's job runner already gives the asynchrony it needs.

### 1.3 Trade-offs

| Criterion | 1. Layered | 2. Ports and adapters | 3. Services |
| --- | --- | --- | --- |
| Complexity for a solo builder | low | low to medium: a `ports.py`, a `container.py`, one folder per adapter | high |
| Testability without files, databases, or the network | partial | high: every port has an in-memory implementation | high |
| Fit with the seams already planned (`01` §10) | named in prose only | the seams are the ports | over-built |
| Fit with desktop packaging (one process) | good | good | poor |
| Predictable place for new code | by layer | by area and by port | by service |
| Risk of generic buckets (`utils`, `common`) | high | low, when names are checked | medium |

### 1.4 Decision

Option 2: a **modular monolith with ports and adapters**, where the SDK is the core. In one sentence: _domain and application logic live in `fefat` and the engine crates; everything that touches the outside world (HTTP, SQLite, processes, files, keychains, Anthropic's API, vendors) is an adapter behind a named port._

The **dependency rule** (arrows point inward; nothing on the right imports anything on the left):

```text
web  →  fefat_app.http  →  fefat_app.services  →  fefat (SDK)  →  fefat_engine (Rust)
                                   ↑                      ↑
                 adapters implement ports           fefat.market.importers are the
                 (fefat_app.ports)                  SDK's only network and vendor edge

engine crates:  fefat-py, fefat-cli  →  fefat-engine, fefat-prop, fefat-metrics, fefat-data  →  fefat-core
                fefat-core defines the MarketDataReader trait; fefat-data implements it over mmap,
                tests implement it in memory; no engine crate but fefat-data touches the file system
```

- `fefat` never imports `fefat_app`; `fefat_app.services` never imports FastAPI or SQLAlchemy; routers in `fefat_app.http` hold no business logic; the web client recomputes no number the API provides.
- Ports are `typing.Protocol`s in `python/fefat_app/src/fefat_app/ports.py`: `Executor`, `Dispatcher`, `BlobStore`, `AgentRuntime`, `PlatformDataSource`, `CredentialStore`, `Licence`. Adapters are built once from `config.toml` in `python/fefat_app/src/fefat_app/container.py` and reach services through FastAPI dependencies; no service instantiates an adapter.
- In Rust, `fefat-core` holds the shared vocabulary (newtypes, orders, fills, errors, calendar) and the `MarketDataReader` trait (bars, seconds, ticks, and the offsets between levels); `fefat-engine`, `fefat-prop`, and `fefat-metrics` are pure computation over it; `fefat-data` is the only crate with `unsafe` and the only one that opens files; `fefat-py` and `fefat-cli` wire the two together.

### 1.5 Enforcement

| Rule | Checked by |
| --- | --- |
| Python import directions (SDK never imports the app; services never import web or database frameworks) | `import-linter` contracts in `pyproject.toml`, run by `just check` from step 0.2 on |
| Rust crate directions (no engine crate depends on `fefat-data` except `fefat-py` and `fefat-cli`) | the Cargo workspace graph, plus a test that reads `cargo metadata` and asserts it |
| Web areas import only `ui/`, `api/`, `charts/`, and `app/`, never each other | an import-boundary lint in `just check` from step 4.3 on — `eslint-plugin-boundaries`, or oxlint's `no-restricted-imports` patterns, since create-vite 9 scaffolds with oxlint; chosen at the Phase 4 kickoff |
| Numbers shown in the UI equal the SDK's | contract tests per UI step (`05-build-process.md` §4) |
| Names, errors, state types, injection, size (§3) | `.claude/rules/*.md` plus the `step-reviewer` subagent |

### 1.6 Validation against the skill's checklist

- Matches project size and complexity: a monolith for one process; ports only where the plan already needed a seam.
- Aligns with team skills: the builder reads the Python core and the plain-language specs; the adapters are small and conventional.
- Supports current requirements: nothing in the first release needs more than one process.
- Allows anticipated growth: cloud sync, containers, Managed Agents, and the hosted data service each replace one adapter (`01-architecture.md` §10).
- Dependencies flow inward: the rule above, enforced in `just check`.
- Clear boundaries: three languages with typed contracts; one folder per adapter; one folder per web area.
- Testing strategy is feasible: every port has an in-memory implementation; engine tests run on in-memory tapes; the reference engine remains the oracle (D-10).
- Trade-offs documented: this section and D-27.

## 2. What changed in the layout and names

`01-architecture.md` §3 is the layout; this is the list of changes against the plan as first written, with the reason.

| Before | After | Why |
| --- | --- | --- |
| `python/fefat/data/` and `ff.data.load(...)` | `python/fefat/src/fefat/market/` and `ff.market.load(...)` | `data` is a generic name; the package holds market data (platform data, imported data, calendars, bars, rolls). The CLI keeps `fefat data …` because that is what the trader calls it. |
| `fefat/ta/`, `ff.ta.atr(14)` | `fefat/indicators/`, `ff.indicators.atr(14)` | no abbreviations; the plan already calls them indicators |
| `fefat/ref/engine.py`, `fefat/ref/prop.py` | `fefat/reference/engine.py`, `fefat/reference/prop.py` | no abbreviations; it is the reference implementation (D-10) |
| `fefat_app/server/` | `fefat_app/http/` | names the adapter by what it is: the HTTP ring |
| business logic in routers | `fefat_app/services/<area>.py` | one application-service module per area (`runs`, `strategies`, `features`, `prop`, `imports`, `studies`, `agent_sessions`), where use cases orchestrate the SDK, the repositories, and the jobs |
| seams named in prose | `fefat_app/ports.py` and `fefat_app/container.py` | injected dependencies instead of adapters created inside methods |
| `fefat_app/exec_runner.py`, `Executor.run(ExecSpec) -> ExecResult` | `fefat_app/executor.py`, `Executor.run(ExecutionSpec) -> ExecutionResult` | no abbreviations |
| `fefat_app/db/`, rule file `db.md` | `fefat_app/database/`, rule file `database.md` | no abbreviations |
| `fefat_app/secrets.py` | `fefat_app/credentials.py` | the seam is the credential store |
| engine reads the cache directly | `MarketDataReader` trait in `fefat-core`, implemented by `fefat-data` and by in-memory tapes in tests | engine tests and the differential suite never touch the file system |
| `web/src/components/…` | `web/src/app/` (shell, router, providers), `web/src/areas/<area>/` (`lab`, `strategies`, `runs`, `prop`, `agent`, `data`, `settings`: routes, components, hooks per area), `web/src/ui/` (design-system primitives and tokens), `web/src/charts/`, `web/src/api/` (generated client and query hooks) | feature-based layout, named by product area; `areas` because `features` is a FEFAT domain word |

Schema column names that mirror a vendor's (`ts_recv`, `ts_event`, `ohlcv`) keep the vendor's spelling: they are an external contract, not our identifiers.

## 3. Design rules, by language

The `software-design-principles` skill, adapted to a numeric engine, a Polars SDK, and a React client. These become `.claude/rules/engine.md`, `python.md`, and `web.md` in step 0.4; the `step-reviewer` checks them.

### 3.1 Everywhere

- **Names reveal intent** and come from the glossary in `00-product-spec.md` §7. Never `data`, `utils`, `helpers`, `common`, `shared`, `misc`, `manager`, `handler`, `processor`, `info`, `item` as a module, class, or variable name. No abbreviations in identifiers, except these domain and protocol terms: `pnl`, `atr`, `rsi`, `ema`, `sma`, `vwap`, `ohlcv`, `id`, `api`, `http`, `utc`, `csv`, `json`, `sql`.
- **Fail fast.** No fallback chains (`a or b or "unknown"`, `x ?? y ?? z`). Parse and validate at every boundary (Pydantic, serde, zod) and stop with an error that says _Expected …, got …, context …_. Defaults exist only where the product defines one (a fill model's conservative default is a documented rule, not a fallback), and every applied default is visible in the run's record.
- **Illegal states are unrepresentable.** Status and kind fields are enums or tagged unions, never free strings or combinations of optional fields: job and run status, order state, proposal status, prop account stage, fidelity, path fidelity, dataset source, strategy kind. A state transition is a function from one variant to another.
- **Wrap primitives that carry meaning.** Prices, quantities, money, timestamps, timeframes, instrument identities, and version numbers are newtypes or value models, not bare integers and strings.
- **Inject dependencies.** Anything that touches the outside world arrives through a constructor, a function parameter, or a FastAPI dependency; nothing creates an adapter inside a method. Pure functions stay pure.
- **Immutable by default.** Values are not mutated after construction: Pydantic models are frozen, Polars and Arrow frames are immutable, Rust borrows are shared unless a `mut` is local and short, TypeScript objects are `readonly` and functions return new values. Versioned rows are insert-only (D-11).
- **Small units.** Functions under about 40 lines, nesting at most three levels, early returns instead of `else`, modules under about 400 lines. The engine loop and the reference engine may exceed the function limit when a scenario table documents each branch; nothing else may.
- **Tell, don't ask.** A computation lives with the data it uses: P&L on the ledger and the trade, drawdown on the equity series, rule checks on the account state. The web client never recomputes a number the API returns.
- **Comments.** No narrative comments; names and small functions carry the meaning. Allowed: documentation comments on public APIs (rustdoc, docstrings, TSDoc), a citation of a spec rule, scenario, or ADR (`// S-fill-012`, `# ADR-0007`), and the `// SAFETY:` note clippy requires on every `unsafe` block.
- **YAGNI.** Build what the step asks for; extras go to `BACKLOG.md`. The only abstractions built ahead of use are the named ports.

### 3.2 Rust (`engine/`)

Newtypes for `Price`, `Qty`, `Money`, `Ts` with checked arithmetic; enums for every order, position, and account state; `thiserror` errors with the expected and actual values; `unwrap_used`, `expect_used`, `panic`, `indexing_slicing`, and `undocumented_unsafe_blocks` denied in core crates; ordered collections wherever order affects output; traits for ports (`MarketDataReader`, `AccountModel`) passed in by the caller, generics in hot loops and `dyn` elsewhere; no I/O outside `fefat-data`, `fefat-py`, and `fefat-cli`; no wall clock and no unseeded randomness anywhere.

### 3.3 Python (`python/`, `scripts/`)

`uv` only; ruff and pyright (strict for `fefat_app`, basic for `fefat`); frozen Pydantic models at every boundary and `StrEnum` plus discriminated unions for states; `typing.Protocol` for ports; Polars expressions over loops; `pathlib` paths; no network in unit tests; exceptions carry the expected value, the actual value, and the identifying context (instrument, run id, file name); the reference engine stays readable by a non-programmer (D-10), which is why it may be longer than the limits above.

### 3.4 TypeScript (`web/`)

`strict`; no `any`, no `as` assertions, no `@ts-ignore` or `@ts-expect-error` without a one-line reason and reviewer approval; API types generated from OpenAPI, with zod schemas for everything the API does not type (URL search parameters, local storage, SSE payloads, imported files); discriminated unions for view state; `readonly` props; components under about 150 lines, hooks named after what they load or do; stable `data-testid`s; no number recomputed in the client.

## 4. Backtest methodology: what the `backtest-expert` skill adds

The skill's core — find strategies that break the least, spend most of the time trying to break them, seek plateaus not peaks, demand sample size and out-of-sample proof — is already the spine of the plan: scenario tables as the specification and conservative fill defaults (D-07, D-10), the leak detector (D-12), tick-based slippage and P&L at +1 tick (`02-engine-and-data.md` §7), year and fidelity-era breakdowns, deflated Sharpe, PBO, a locked holdout, walk-forward, day-block bootstrap, trial counting, and cost and parameter stress (`02` §9, Phase 11). The review found five additions worth making; the first is written into step 2.11 now, and the others are pulled into their steps at the phase kickoffs (they are listed in `BACKLOG.md` with their target step):

1. **A robustness verdict on every run** (step 2.11, shown in 5.7): the skill's five dimensions — sample size (30 / 100 / 200 trades), expectancy, risk (drawdown, profit factor), robustness (years and regimes covered, number of parameters), execution realism (were friction and worst-case fills tested) — as a small table with a plain verdict (deploy-grade evidence, refine, abandon) and the red flags that fired. The script that ships with the skill (`.claude/skills/backtest-expert/scripts/evaluate_backtest.py`, standard library only) is the first implementation to port.
2. **A one-sentence hypothesis on every strategy** (steps 5.2 and 5.5, used by the agent in 8.8): the edge in the trader's words, required before the first run, shown at the top of every result.
3. **A stress profile as one click** (steps 5.6 and 11.6): slippage at 1.5× and 2×, worst-case fills (one tick against on every entry and exit), commissions at 1.5×, entry timing shifted by one bar, run as a batch next to the base run.
4. **Regime breakdown** (steps 2.11 and 11.4): results by volatility tercile and by trend state of the instrument itself, next to the year breakdown; the equity-market numbers in the skill (VIX bands, market-cap slippage tables) do not transfer to futures and crypto and are not used.
5. **A record of abandoned ideas** (step 5.5, backlog until then): a strategy can be marked abandoned with the breaking point and the lesson, following the skill's case-study framework, so the library keeps the failures too.

## 5. Frontend design: how the `frontend-design` skill is used

Decision D-28: every screen is designed with the `frontend-design` skill, from one design system that step 4.3 creates and later steps extend. Without this, each UI step would produce the generic defaults the skill warns about (cream backgrounds, identical rounded cards, eyebrow labels, arrows on every button), and FEFAT would look like a template rather than a trading research tool.

1. **The design brief** is collected at the Phase 4 kickoff: who uses it (you now, traders later), the job (a research terminal: dense numbers, charts, long desk sessions, one-thumb use on the phone), what you like and dislike in the tools you use today, light or dark as the default, and any reference you want followed exactly. The brief's own words always win over the skill's defaults.
2. **Step 4.3 writes `web/DESIGN.md`** with the skill's two-pass process: a compact token system (palette as four to six named hex values, typefaces and their roles with a type scale, layout concept with alignment rules, principles that say what makes FEFAT's screens its own), then a review of that plan against the generic defaults, recording what was changed and why. The tokens become the Tailwind theme and CSS variables; shadcn/ui components are themed from them, never left at their defaults; charts (Lightweight Charts, ECharts) take their colours from the same tokens.
3. **Every later UI step** loads the skill (the `step` skill does this whenever a step touches `web/`), reads `web/DESIGN.md`, builds with the tokens, and adds any new pattern to the file, so the system stays one system. Copy follows the skill's writing rules: plain verbs, sentence case, actions named the same from button to toast, errors that say what happened and what to do, empty states that invite the next action.
4. **The quality floor** is unchanged and checked by `ui-verifier`: every page works at 390 px without horizontal scroll, keyboard focus is visible, reduced motion is respected, contrast passes, one deliberate motion at most per screen.
5. **Phase exits of UI phases** (P4, P5, P6, P7, P8, P12) run the `design-critique` and `accessibility-review` skills from the installed `design` plugin over the main pages; findings become steps or backlog items.
6. **The design review** (D-34): the `design-reviewer` subagent reviews every UI step's diff and screenshots, and the main pages at the exits of UI phases, through the `apple-design` skill: feedback on press, interruptible motion that starts from the current value, enter and exit along the same path, materials and depth, tracking and leading by size, reduced motion and transparency, and Apple's eight design principles. It reviews and never builds: the `frontend-design` skill and `web/DESIGN.md` decide the look, the brief's own words win over both skills, and a conflict becomes a proposed edit to `web/DESIGN.md`, not a finding.

## 6. Deliberately not adopted

- Object calisthenics taken literally (ten-line methods, one dot per line, two instance variables, no getters): a fill loop, a Polars expression chain, and a Pydantic model would all violate them for no gain. The adapted limits are in §3.1.
- "No comments" taken literally: public API documentation and spec, scenario, and ADR citations are kept, and clippy requires `SAFETY` comments.
- TypeScript-only tooling (zod, branded types) outside `web/`; Python and Rust have their own equivalents named above.
- Dependency injection ceremony in `scripts/`: project scripts are small, standard-library programs run through `uv run python`; they follow the naming and fail-fast rules and nothing more.
- The skill's equity-market calibration numbers (market-cap slippage tiers, VIX regimes, "deploy" thresholds as universal truths): FEFAT measures slippage in ticks per instrument, defines regimes from the instrument itself, and shows evidence rather than a verdict alone.
- Microservices, event sourcing, CQRS: nothing in the product needs them; the jobs table and the events stream give what asynchrony the app needs.
