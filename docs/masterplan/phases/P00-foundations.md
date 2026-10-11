# Phase 0 — Foundations

**Goal.** A repository, a toolchain, and a Claude Code setup that make every later step repeatable: one command to check, one to test, guards against committing secrets or licensed data, and a proof that Rust code can be called from a notebook on this PC.

**You get.** `just doctor`, `just check`, `just test` all green on Windows and in CI; a private GitHub repo with squash-only pull requests and a written merge routine; `/step`, `/phase-kickoff`, `/phase-exit` working; a notebook cell that calls a Rust function.

**Depends on.** Nothing. Steps 0.1–0.4 are pasted into Claude Code (0.4 is the step that creates the `/step` runner); 0.1–0.3 may commit straight to `main`; from 0.4 on, every step is a branch and a pull request. On this PC, bare `python` is a Microsoft Store stub: every command goes through `uv run python` (or `python3.12`).

**Open decisions for the kickoff.** None; this phase has no kickoff. Start with step 0.1.

## Steps

### 0.1 Install the toolchain and write the doctor script

Depends on: none · Plan mode: skip · Reviews: none · Security: no · Model hint: default

#### Purpose

Everything later compiles and runs on this PC. You end with a script that tells you, at any time, what is installed and what is missing.

#### Prerequisites

- Windows 11 with git, GitHub CLI (signed in), Node 24, uv, and VS Code with Claude Code (all present on 2026-10-05).
- Administrator rights for the C++ build tools installer.

#### Prompt

```text
Masterplan step 0.1 — Install the toolchain and write the doctor script.

Read docs/masterplan/07-tools-and-costs.md §1 and docs/masterplan/01-architecture.md §2. Guide me through installing what FEFAT needs on this Windows PC: Microsoft C++ Build Tools (Desktop development with C++), Rust via rustup (stable), pnpm via corepack, and `just`. For installers that need a GUI or administrator rights, tell me exactly what to click and wait for me to confirm; for everything else, run the commands yourself and verify the result. Use winget where it works.

Then write `scripts/doctor.py` (Python 3.12, standard library only) that reports the versions of git, gh, node, pnpm, uv, python, rustc, cargo, just, and the presence of the MSVC linker, each as OK or MISSING with the expected minimum, and exits non-zero if anything required is missing. Add a minimal `justfile` with a `doctor` recipe that runs it through `uv run --no-project python scripts/doctor.py`.

Constraints: no shell scripts (Python and just recipes only); the script must run from PowerShell and from Git Bash; pin nothing yet — step 0.2 adds the toolchain files.

Not in this step: the repository scaffold, git initialisation, CI, or any Rust or Python package.
```

#### Done means

1. `just doctor` prints every tool as OK, with versions, in both PowerShell and Git Bash.
2. `cargo --version`, `rustc --version`, `pnpm --version`, `just --version` work in a fresh terminal.
3. A one-line Rust program compiles and links (`cargo new` in a temp folder, `cargo run`), proving the MSVC toolchain works; the temp folder is deleted afterwards.

#### Your checks

- Open a new PowerShell window, run `just doctor`, and read the table: all OK.
- Run `cargo --version`. If it prints a version, Rust is ready.

#### If it fails

- `link.exe not found` or "linker not found": the C++ build tools workload is not installed; rerun the Visual Studio Installer and tick "Desktop development with C++".
- `just` not found after install: close and reopen the terminal (PATH changes need a new shell).
- If Claude Code loops on an installer, stop, do the install by hand, and resume with "the installer is done; continue".

#### Amendment

2026-10-08, while doing the step: three install commands in `07-tools-and-costs.md` §1 failed as written on this PC, and its table now shows the ones that worked — `winget install Microsoft.VisualStudio.2022.BuildTools` installs no C++ workload unless `--override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"` is passed; `corepack enable` needs administrator rights because Node lives in Program Files (`--install-directory "$env:APPDATA\npm"` avoids that); corepack 0.35 has no `corepack prepare` (`corepack install -g pnpm@latest` replaces it). `just` on Windows looks for `sh`, which PowerShell does not have on its PATH, so the `justfile` sets `windows-shell` to `cmd.exe` and every recipe line is a plain command that also runs under `sh`. The optional Claude Code CLI was not installed, by choice; the VS Code extension is used.

### 0.2 Scaffold the repository

Depends on: 0.1 · Plan mode: optional · Reviews: none · Security: no · Model hint: default

#### Purpose

The monorepo layout from `01-architecture.md` §3 exists, builds, and is pinned, so every later step lands in a known place.

#### Prerequisites

- Step 0.1 merged (tools installed).

#### Prompt

```text
Masterplan step 0.2 — Scaffold the repository.

Read docs/masterplan/01-architecture.md §3 and §11. Create the monorepo layout: a uv workspace at the root with packages `python/fefat` and `python/fefat_app` (empty modules with version strings), a Cargo workspace in `engine/` with the crates listed in §3 as empty library crates (plus `fefat-cli` as a binary), and a Vite + React + TypeScript app in `web/` created with pnpm. This folder is already a clone of the private GitHub repository `kenny-g-97/fefat`.

Pin everything: `.python-version` (3.12), `engine/rust-toolchain.toml` (the stable version installed), `packageManager` in `web/package.json`, lockfiles committed. The repository preparation already added `.gitattributes` (LF everywhere), `.editorconfig`, a `.gitignore` (build outputs, secrets, market-data file types except `fixtures/synthetic/`), `.vscode/` settings, and a bootstrap CLAUDE.md: keep them and extend them where the scaffold needs it (for example new build-output folders) rather than replacing them.

Extend the `justfile`: `setup` (uv sync, cargo fetch, pnpm install), `check` (ruff check + ruff format --check, pyright, cargo fmt --check, cargo clippy -D warnings, pnpm lint + typecheck), `test` (pytest, cargo nextest or cargo test, vitest), `dev` (placeholder until Phase 4). Every recipe must run on Windows and Linux and must invoke Python through uv, never a bare `python`.

Add a short "Getting started" section to the existing root README.md (`just setup`, `just doctor`, `just check`, `just test`); step 0.7 expands it. Keep the masterplan under docs/ untouched. Commit on main with a clear message.

Not in this step: any real code, CI, GitHub, Claude Code configuration, fixtures.
```

#### Done means

1. `just setup`, `just check`, and `just test` succeed on a clean clone (the test suites may be empty but must run).
2. `git ls-files` shows no build outputs and no data files; `git check-attr text eol -- README.md` reports `text: auto` and `eol: lf`.
3. Lockfiles (`uv.lock`, `engine/Cargo.lock`, `web/pnpm-lock.yaml`) are committed.

#### Your checks

- Run `just check` then `just test`: both end without errors.
- Open the folder in VS Code: the tree matches `01-architecture.md` §3.

#### If it fails

- `pyright` or `ruff` not found: they belong to the uv workspace's dev dependencies; ask Claude Code to add them and `just setup` again.
- Clippy warnings in generated code: acceptable only if the recipe excludes generated files explicitly.

#### Amendment

2026-10-08, repository preparation before step 0.1: this folder became a clone of the private repository `kenny-g-97/fefat`, and the preparation commit added `.gitattributes`, `.gitignore`, `.editorconfig`, `.vscode/settings.json`, `.vscode/extensions.json`, a bootstrap `CLAUDE.md`, and a short root README. The prompt now extends these files instead of creating them, and Done means 2 checks the attributes as git reports them for `text=auto eol=lf`.

2026-10-09: the layout in `01-architecture.md` §3 now uses the src layout for the two Python packages (`python/fefat/src/fefat/`, `python/fefat_app/src/fefat_app/`) and the names of D-27; `just check` also runs the import-linter contract that keeps `fefat` from importing `fefat_app` (`08-code-design.md` §1.5); `just test` runs `cargo test` until nextest is adopted (backlog). While doing the step: create-vite 9 scaffolds with oxlint rather than ESLint, so `pnpm lint` is oxlint and the import-boundary lint of step 4.3 is chosen at the Phase 4 kickoff; ruff 0.16 formats Python code blocks inside Markdown, so `*.md` is excluded from `ruff format` and the masterplan stays untouched; `.vscode/settings.json` points rust-analyzer at `engine/Cargo.toml` and Python at the workspace `.venv`.

### 0.3 Configure the GitHub repository for pull requests

Depends on: 0.2 · Plan mode: skip · Reviews: none · Security: no · Model hint: default

#### Purpose

Work happens on branches with pull requests from now on, merged one way only. GitHub's free plan cannot protect `main` on a private repository, so a written merge routine (`05-build-process.md` §8) and Claude Code's hooks (step 0.4) keep `main` clean instead.

#### Prerequisites

- GitHub CLI signed in (`gh auth status`).
- The private repository `kenny-g-97/fefat` exists and this folder is its clone (done on 2026-10-08); `main` is pushed (done on 2026-10-09).

#### Prompt

```text
Masterplan step 0.3 — Configure the GitHub repository for pull requests.

The private GitHub repository `kenny-g-97/fefat` already exists, this folder is its clone (remote `origin`), and `main` is pushed, so do not create a repository. Confirm with `gh repo view` that it is private (if it is not, stop and ask me) and that `origin/main` matches the local `main`. The account is on GitHub's free plan, which offers neither branch protection nor rulesets for private repositories (both APIs answer 403), so configure neither. Set the merge options with `gh repo edit`: squash merging only (merge commits and rebase merging off), and head branches deleted after merge.

Add a pull request template at `.github/pull_request_template.md` with the sections from docs/masterplan/05-build-process.md §8 (Summary, Done means with evidence per item, Deviations, Follow-ups, Progress row, Screenshots or recordings for UI), and push it to `main`, since GitHub only uses a template that is on the default branch.

Set `git config core.hooksPath .githooks` locally and create an empty `.githooks/pre-commit` placeholder (Python-invoking, executable bit irrelevant on Windows; document how it is run) that step 0.5 fills in.

Finally open one small test pull request from a branch `step/0.3-pull-requests`: a one-line pointer in the root README's Getting started section to the merge routine in 05-build-process.md §8. Leave it open; I merge it with that routine as my check.

Not in this step: CI workflows, hooks logic, Claude Code configuration.
```

#### Done means

1. `gh repo view` shows a private repository; `git remote -v` points at it; `origin/main` equals the local `main`.
2. `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed,deleteBranchOnMerge` shows squash merging only and branches deleted after merge.
3. The test pull request shows the template's sections, and `git config core.hooksPath` prints `.githooks`.

#### Your checks

- Open the repository on github.com: it is private, and under Settings → General → Pull Requests only "Allow squash merging" is ticked, with "Automatically delete head branches" ticked as well.
- Merge the test pull request with the commands in `05-build-process.md` §8. Afterwards `git log --oneline -3` shows its squash commit on top, and `gh pr list` shows no open pull request.

#### If it fails

- `gh repo edit` refuses a setting: set it by hand under Settings → General → Pull Requests and say so in the summary.
- The test pull request has an empty description: the template was not on `main` when it was opened; push `main`, then fill the description from the template or open the pull request again.

#### Amendment

2026-10-08: you created the private repository `kenny-g-97/fefat` on GitHub, and this folder became its clone during the repository preparation. The step no longer creates a repository; it confirms the repository is private, pushes `main`, and adds the protection, the pull request template, and the hook placeholder. Title updated to match.

2026-10-09: GitHub's free plan offers neither branch protection nor rulesets for private repositories — `gh api repos/kenny-g-97/fefat/branches/main/protection` and `.../rulesets` both returned 403 ("Upgrade to GitHub Pro or make this repository public to enable this feature") — and you chose to stay on the free plan (D-30). The step therefore sets squash-only merging instead of protection and ends with a test pull request that you merge with the routine now written in `05-build-process.md` §8; the template and the hook placeholder are unchanged, and Claude Code's hooks from step 0.4 deny its own pushes to `main` and force pushes. `main` was pushed on 2026-10-09. Title, purpose, prerequisites, prompt, done means, checks, and failure notes updated; the old note that rulesets work on the free plan was wrong for private repositories.

### 0.4 Configure Claude Code for this repository

Depends on: 0.3 · Plan mode: required · Reviews: step-reviewer · Security: no · Model hint: hard

#### Purpose

From here on every session behaves the same: `/step` runs a step under the protocol, hooks keep secrets and data out, rules apply per area, and reviewers exist.

#### Prerequisites

- Steps 0.1–0.3 merged.
- Read `docs/masterplan/06-claude-code-setup.md` yourself once; you will approve a plan.

#### Prompt

```text
Masterplan step 0.4 — Configure Claude Code for this repository.

Read docs/masterplan/06-claude-code-setup.md in full and docs/masterplan/05-build-process.md. First verify, against the Claude Code documentation for the version installed here (`claude --version` or the VS Code extension version), the exact file locations and frontmatter fields for skills, subagents, hooks, rules, and settings; note any difference from the doc in your plan.

Then replace the bootstrap CLAUDE.md with the full version (100–150 lines, content per §1), keeping its facts about this machine and its "Never" rules; create `.claude/rules/` (engine, python, web, database, masterplan) with `paths:` frontmatter; `.claude/settings.json` with the permission rules of §6 (every Bash rule with a PowerShell twin) and the hooks of §5 implemented as Node scripts under `.claude/hooks/` in exec form; the skills `step`, `phase-kickoff`, `phase-exit`, `verify`, and `engine-golden` under `.claude/skills/`, next to the three design skills already there (leave them as they are); and three read-only reviewer subagents under `.claude/agents/`: `step-reviewer`, `engine-accuracy-reviewer`, and `leakage-auditor`, with the roles described in §4 (the `ui-verifier` arrives with the Playwright harness in 4.3). The `step` skill must find a step by ID inside `docs/masterplan/phases/P*.md` (headings `### N.M Title`), check prerequisites in PROGRESS.md, create or reuse the branch `step/N.M-<slug>`, load the skills for the paths the step touches as docs/masterplan/08-code-design.md says (`software-design-principles` always; `backtest-expert` for engine, prop, results, and research steps; `frontend-design` with web/DESIGN.md for web/), follow the protocol in 05-build-process.md §2, run the reviewers named in the step's meta line, and finish by opening the PR and updating PROGRESS.md.

Add hook smoke tests under `scripts/test_hooks.py` that feed sample JSON to each hook script and assert allow/deny/ask decisions, and wire them into `just test` (through `uv run python`).

Install the language-server plugins listed in §7 if the plugin marketplace is available; otherwise note it.

Not in this step: the data-policy commit guard (0.5), CI (0.6), the `ui-verifier` (4.3).
```

#### Done means

1. `uv run python scripts/test_hooks.py` (via `just test`) passes: an edit to `.env` is denied, a write of `data/x.parquet` is denied, a write of `fixtures/synthetic/x.parquet` is allowed, a `git push --force` command is denied, a golden regeneration asks.
2. In a fresh session, `/step 0.5` prints the step's purpose and prerequisites and stops when asked to only preview (dry-run flag or equivalent).
3. `CLAUDE.md` is under 150 lines and links to the ADR folder and the masterplan.
4. The three reviewer subagents exist and each runs on a sample diff (the PR shows one invocation of each).
5. The PR lists which doc assumptions differed from the installed Claude Code version.

#### Your checks

- Open a new Claude Code session and type `/step 0.5`. It should describe step 0.5 and ask to proceed (say no for now).
- Ask Claude Code to "edit .env and add a key": it must refuse with the hook's message.

#### If it fails

- Hooks not firing: check `.claude/settings.json` is in the launch directory (open VS Code at the repo root) and that matchers read `Bash|PowerShell`.
- `/step` not found: skills load from `.claude/skills/<name>/SKILL.md`; the folder name must match.

#### Amendment

2026-10-08: a short bootstrap `CLAUDE.md` exists since the repository preparation, so this step replaces it with the full version and keeps its machine facts and "Never" rules.

2026-10-09: the rules list says `database` instead of `db` (D-27); the three design skills installed on 2026-10-09 stay in `.claude/skills/` untouched; the `step` skill loads skills per area (`08-code-design.md`).

2026-10-09, while doing the step: the installed Claude Code (2.1.295) differs from `06-claude-code-setup.md` §8 in seven points, now listed there under "Re-verified on 2026-10-09"; the most visible are the plugin marketplace id (`anthropic-plugin-directory` on this PC) and the `verify` skill, which runs through Claude's commit instructions rather than by itself. The step added `scripts/masterplan_step.py`, the one reader of the masterplan for `/step` and the session hook, which imports the patterns of `check_masterplan.py`, and a fifth hook that keeps the reviewer subagents read-only. Prettier is not installed, so the formatter hook covers Rust and Python, and web files wait for the Phase 4 kickoff's choice between prettier and oxfmt. A `Read` deny rule on `.env*` also blocks writes and fires before any hook, so in Your checks the refusal shows the permission message; `scripts/test_hooks.py` covers the hook's own message. The global TypeScript for the TypeScript language server is pinned to 6, because TypeScript 7 ships no `tsserver`.

2026-10-11, at the Phase 0 exit: the reviewers' shell guard never ran, because Claude Code (2.1.295 and 2.1.296) ignores hooks declared in an agent's frontmatter, and a `step-reviewer` wrote a probe file through its shell. `reviewer-shell-commands.mjs` is now registered in `.claude/settings.json` for Bash and PowerShell, acts only when the hook input's `agent_type` names an agent in `.claude/agents/`, and denied the same probe in a live run; the agents' frontmatter no longer declares it. `python/tests/test_claude_code_settings.py` checks that every hook script is registered for its event and tools, which the smoke tests cannot see, because they start each script directly.

### 0.5 Data policy, synthetic fixtures, commit guard

Depends on: 0.4 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

Licensed market data can never enter git by accident, and tests have realistic synthetic data to run on.

#### Prerequisites

- Step 0.4 merged.

#### Prompt

```text
Masterplan step 0.5 — Data policy, synthetic fixtures, commit guard.

Read docs/masterplan/05-build-process.md §5 and docs/masterplan/02-engine-and-data.md §1. Implement the test-data policy:

1. `scripts/gen_fixtures.py` generates synthetic market data under `fixtures/synthetic/`: a few CME-like sessions of trades with realistic tick sizes, gaps, and a daylight-saving boundary; the derived 1-second and 1-minute bars; a crypto-like 24x7 day; all with a seed and written in the canonical Parquet layout described in 02 §1.1 (prices as int64 1e-9, ns timestamps). Keep total size under 20 MB. Write `fixtures/synthetic/MANIFEST.json` listing each file with generator, seed, and SHA-256.
2. `scripts/guard_data.py` fails if any tracked or staged file has a market-data extension outside `fixtures/synthetic/`, exceeds 25 MB, or matches secret patterns (API keys, `.env`). Wire it into `.githooks/pre-commit` (git runs hooks through its own sh on Windows, so the hook is a one-line launcher that calls `uv run python scripts/guard_data.py`; this is the one permitted shell file in the repo) and into `just check`.
3. `FEFAT_DATA_DIR` handling: `python/fefat/src/fefat/config.py` resolves `FEFAT_HOME` and `FEFAT_DATA_DIR` with platformdirs defaults; document in CLAUDE.md that real data is referenced by path only.
4. Notebooks are committed without outputs, because outputs can contain licensed data: the guard rejects staged `.ipynb` files that contain outputs, and a `just strip-notebooks` recipe clears them (nbstripout as a dev dependency).

The `.gitignore` from the repository preparation already ignores market-data files; the guard exists for forced adds and for files the ignore rules miss.

Not in this step: the real importers (Phase 1), CI (0.6).
```

#### Done means

1. `scripts/gen_fixtures.py` is deterministic: running it twice produces identical hashes in the manifest.
2. Force-staging a file named `data/ES.parquet` (`git add -f`, since `.gitignore` already ignores it) makes `git commit` fail with a clear message; staging `fixtures/synthetic/x.parquet` listed in the manifest passes.
3. `just check` includes the guard and passes on the clean tree.
4. A staged notebook with outputs is refused; after `just strip-notebooks` it passes.

#### Your checks

- Copy any `.parquet` from `fixtures/synthetic/` to `data/test.parquet`, run `git add -f data/test.parquet` (the `-f` gets past `.gitignore`, so this tests the guard itself), and try to commit: the commit must be refused. Afterwards run `git restore --staged data/test.parquet` and delete the file.

#### If it fails

- The pre-commit hook does not run: `git config core.hooksPath` must print `.githooks`; under Git for Windows the `pre-commit` file starts with `#!/bin/sh` and calls `uv run python scripts/guard_data.py` (never bare `python`, which is a Store stub here).

#### Amendment

2026-10-08: `.gitignore` already ignores market-data files since the repository preparation, so the checks force-stage with `git add -f` to test the guard itself. Added item 4: notebooks are committed without outputs, because outputs can contain licensed data.

2026-10-09, while doing the step: the hook and `just check` run `uv run --no-project python scripts/guard_data.py`, because the guard uses only the standard library and a commit should not sync `.venv` (as the step 0.3 placeholder did). The guard reads git's index, which is what a commit takes, so after `just strip-notebooks` the notebook is staged again with `git add` before it passes (Done means 4). `fixtures/synthetic/` is itself the provider folder `synthetic` of the canonical layout, with 1-minute bars per month as `month=2026-03` and the crypto day as `root=BTC/contract=BTCUSDT-PERP`; step 1.1 fixes the official schema in its ADR. `fefat.config` is a frozen dataclass until the Phase 4 settings model brings Pydantic. The new dependencies are D-31; pyarrow is pinned at 26.0.0 because its version is written into every fixture.

### 0.6 CI on Windows and Linux

Depends on: 0.5 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Every pull request is checked on both operating systems, and the Rust extension wheel is built on both, so platform problems are caught early.

#### Prerequisites

- Step 0.5 merged.

#### Prompt

```text
Masterplan step 0.6 — CI on Windows and Linux.

Create `.github/workflows/ci.yml` that runs on pull requests and on pushes to main, with a matrix of windows-latest and ubuntu-latest: install the pinned toolchains (uv with .python-version, rustup from engine/rust-toolchain.toml, pnpm from packageManager), cache dependencies, run `just check` and `just test`, run `scripts/guard_data.py`, and build the `fefat_engine` wheel with maturin from `engine/crates/fefat-py` (an empty PyO3 module for now) as an artifact. Keep total runtime under 15 minutes by caching; no network calls in tests.

GitHub's free plan cannot require the check on `main` (step 0.3), so give the jobs names that say which system they run on: the merge routine in docs/masterplan/05-build-process.md §8 waits for them with `gh pr checks --watch`. Add a status badge to the README.

Not in this step: release workflows, macOS runners, deployment of anything.
```

#### Done means

1. The workflow passes on both runners for the PR that introduces it.
2. The wheel artifact for each platform is attached to the run and installs into a fresh venv (`uv pip install <wheel>` in the workflow, then `python -c "import fefat_engine"`).
3. `gh pr checks` on this step's pull request lists one passing check per system, as the merge routine in 05 §8 expects.

#### Your checks

- Open the PR on GitHub: two green checks (Windows, Ubuntu). Open the run and see the two wheel artifacts.

#### If it fails

- Windows runners lack `just`: install it in the workflow with the official action or `cargo install just` (cached).
- maturin cannot find Python on Windows: pass `--interpreter` with the uv-managed path, or build with `uv run maturin build`.

#### Amendment

2026-10-09: required status checks need branch protection, which GitHub's free plan does not offer for private repositories (step 0.3, D-30); the merge routine in `05-build-process.md` §8 waits for the checks instead, so the prompt and Done means 3 no longer set a required check.

### 0.7 Seed the decision records, progress, and backlog

Depends on: 0.4, 0.6 · Plan mode: skip · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

Decisions from planning become durable records, and the status table exists for the step runner to update.

#### Prerequisites

- Step 0.4 merged.

#### Prompt

```text
Masterplan step 0.7 — Seed the decision records, progress, and backlog.

Create `docs/adr/` with a template (`0000-template.md`: context, decision, consequences, how we would know it is wrong, status) and one ADR per decision marked ADR in docs/masterplan/DECISIONS.md, numbered in order, each a concise record that links back to the decision log. Superseded decisions (D-02 by D-24, the exact mode of D-13 by D-25) get the status "superseded by …" with a link to their successor. Do not invent decisions; where the log gives little rationale, keep the ADR short.

Verify that `docs/masterplan/PROGRESS.md` lists every step in every phase file (run `uv run python docs/masterplan/tools/check_masterplan.py`) and fix the table if a step is missing. Make sure the `step` skill updates the right row.

Expand the root README.md: what FEFAT is in three sentences, how to set up (`just setup`, `just doctor`), how to run checks, the CI badge from 0.6, and a pointer to docs/masterplan/README.md.

Not in this step: any code.
```

#### Done means

1. `docs/adr/` contains the template and one file per ADR-marked decision, each with all five sections.
2. `uv run python docs/masterplan/tools/check_masterplan.py` passes.
3. The root README renders on GitHub with the CI badge.

#### Your checks

- Open the ADR for D-24 (platform data and imports of your own data) and the one for D-25 (prop simulation from existing backtest files) and read them: they should match what you decided. The ADR for D-02 should show "superseded by" D-24.

#### If it fails

- If the checker reports a missing step, the PROGRESS table is out of date; let Claude Code regenerate the rows from the phase files.

### 0.8 Hello-world slice: Rust to Python to a notebook

Depends on: 0.6 · Plan mode: optional · Reviews: step-reviewer · Security: no · Model hint: default

#### Purpose

The whole chain works on this PC: a Rust function compiled with maturin, imported by the `fefat` package, called from a notebook. Every later engine step builds on this.

#### Prerequisites

- Steps 0.6 and 0.7 merged.

#### Prompt

```text
Masterplan step 0.8 — Hello-world slice from Rust through Python to a notebook.

In `engine/crates/fefat-core` add a pure function that computes a simple deterministic statistic over an int64 slice (for example the maximum drawdown of a cumulative sum), with unit tests and a proptest invariant. Expose it through `engine/crates/fefat-py` as `fefat_engine.max_drawdown(values: list[int]) -> int` and, in the same crate, a second function that accepts a PyArrow or Polars int64 array through the Arrow PyCapsule interface (pyo3-arrow) so zero-copy interchange is proven.

In `python/fefat`, add `fefat.engine_info()` returning the engine version and build info, and a thin wrapper `fefat.stats.max_drawdown` that accepts a Polars Series. Build with `uv run maturin develop --release`. Add a pytest that compares the Rust result with a pure-Python implementation on random inputs (hypothesis).

Add `notebooks/00-hello-engine.ipynb` that imports fefat, prints `engine_info()`, and runs `max_drawdown` on a Polars series, with the expected output in a markdown cell. Add a `just build-engine` recipe.

Not in this step: any engine logic beyond the demonstration function, data loading.
```

#### Done means

1. `just build-engine` then `just test` passes, including the hypothesis comparison test.
2. The Arrow path is zero-copy: the test asserts no conversion by comparing buffer addresses or by the pyo3-arrow API's documented behaviour, and the PR explains how.
3. CI builds and tests the real extension on both platforms.

#### Your checks

- Open `notebooks/00-hello-engine.ipynb` in VS Code, run all cells: the last cell prints a drawdown value equal to the one in the markdown cell.

#### If it fails

- `maturin develop` cannot find the venv: run it through `uv run` so the workspace environment is used.
- Import error `DLL load failed` on Windows: the wheel was built against a different Python; rebuild after `uv sync`.

## Phase exit

```text
Phase 0 exit. Run the phase-exit procedure from docs/masterplan/05-build-process.md §6: full `just check` and `just test` from a clean clone on this PC; CI green on both platforms; a short demo script for me (doctor, check, test, the hello notebook); turn any repeated correction from this phase into CLAUDE.md, rule, or skill edits; record the Claude Code version; tag `phase-0`. Open the exit PR with the demo script and the updated PROGRESS.md.
```
