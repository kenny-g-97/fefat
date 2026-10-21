# 06 — Claude Code setup

What step 0.4 installs in the repository so every later session works the same way. Feature names and locations were verified against the Claude Code docs on 2026-10-05 (URLs at the end); step 0.4 re-checks them against the version installed at the time.

## 1. `CLAUDE.md` (100–150 lines)

A short bootstrap `CLAUDE.md` exists since the repository preparation (2026-10-08) so that the sessions for steps 0.1–0.3 know the ground rules; step 0.4 replaces it with the full file, which holds what every session must know and nothing a hook enforces:

- **Repo map and commands:** the handful of `just` recipes (`setup`, `doctor`, `check`, `test`, `e2e`, `dev`, `up`), identical on Windows, CI, and macOS.
- **Workflow:** one masterplan step per session through `/step`; never commit to `main`; the builder merges; the step protocol lives in `docs/masterplan/05-build-process.md`.
- **Invariants, each linked to its ADR:** deterministic runs; no look-ahead; licensed data never in the repo; goldens change only with the builder's approval; tests are never weakened to pass; versions and runs are immutable.
- **Windows notes:** LF endings; `pathlib`; PowerShell and Git Bash both exist; private data through `FEFAT_DATA_DIR`.
- **Pointers:** architecture docs by path, including `08-code-design.md` for the dependency rule and the design rules; the `claude-api` skill for any Anthropic API code; which project skill to load per area (`software-design-principles` for all code, `backtest-expert` for engine, prop, results, and research code, `frontend-design` with `web/DESIGN.md` for the web app).
- **Not in it:** language conventions (rules), procedures (skills), architecture prose (docs).

## 2. Rules (`.claude/rules/*.md`, each with `paths:` frontmatter)

| Rule file | Paths | Content |
| --- | --- | --- |
| `engine.md` | `engine/**` | seeded randomness and an injected clock only; ordered collections wherever order affects output; integer money; every behaviour change comes with a scenario table; `unwrap`/`panic`/indexing lints; `08-code-design.md` §1 and §3.2: no I/O outside `fefat-data`, `fefat-py`, `fefat-cli`; enums for every state; `MarketDataReader` and `AccountModel` passed in; load `backtest-expert` |
| `python.md` | `python/**` | uv only; ruff and pyright; Polars first; no network in unit tests; Pydantic models at every boundary; `08-code-design.md` §3.1 and §3.3: names, fail-fast errors, frozen models, enums for states, ports injected, the SDK never imports the app |
| `web.md` | `web/**` | API types generated from OpenAPI; numbers come from the API, never recomputed in the client; every page works at 390 px; stable `data-testid`s; no remote images; `08-code-design.md` §3.4 and §5: load the `frontend-design` skill, build from `web/DESIGN.md` and extend it, zod for data the API does not type, no `any` or `as`, areas import only `ui/`, `api/`, `charts/`, `app/` |
| `database.md` | `python/fefat_app/src/fefat_app/database/**` | new migration files only, never edited; versioned rows are insert-only |
| `masterplan.md` | `docs/masterplan/**` | stable step IDs; finished steps are not rewritten; amendments are appended |

## 3. Skills (`.claude/skills/<name>/SKILL.md`)

| Skill | Invocation | Does |
| --- | --- | --- |
| `step` | `/step N.M`, or the builder's plain words ("plan the next step") | reads the step from its phase file, checks prerequisites in `PROGRESS.md`, creates or reuses the branch, loads the skills for the paths the step touches (`08-code-design.md`), runs plan mode if required, works, runs checks and reviewers, opens the PR, updates `PROGRESS.md` |
| `phase-kickoff` | `/phase-kickoff N` | the reconciliation procedure in `05-build-process.md` §6 |
| `phase-exit` | `/phase-exit N` | the exit procedure in `05-build-process.md` §6 |
| `verify` | model-invoked | tiered checks by changed area (Rust, Python, web, docs), with the UI recipe (Playwright at desktop and phone sizes, screenshots) in a supporting file |
| `engine-golden` | `paths: engine/**` | how to add scenarios, regenerate goldens with approval, and write the changelog entry |
| `prop-preset-refresh` | manual (P7) | re-read each firm's published rules from the sources in the preset, propose a new preset version with URL and date; never edit an existing version |
| `designing-architecture` | model-invoked; installed 2026-10-09 | the architecture workflow behind `08-code-design.md` §1, for any new module, package, crate, or seam |
| `software-design-principles` | model-invoked; installed 2026-10-09 | the design rules behind `08-code-design.md` §3; loaded for any code |
| `backtest-expert` | model-invoked; installed 2026-10-09 | backtest methodology, the red-flag checklist, and a standard-library evaluation script (`scripts/evaluate_backtest.py`, run through `uv run --no-project python`); loaded for engine, prop, results, and research steps |
| `apple-design` | model-invoked; installed 2026-10-10 | Apple's interface and motion principles translated for the web (response, direct manipulation, interruptible springs, spatial consistency, materials, typography, reduced motion, the eight design principles); the lens of the `design-reviewer` subagent (D-34) |

The three design skills were copied verbatim from the builder's `newskills/` folder on 2026-10-09 (only the example command in `backtest-expert` was changed to run through `uv`); the `frontend-design` skill comes from the plugin installed at user scope the same day (§7). The `apple-design` skill was placed in `.claude/skills/apple-design/` by the builder on 2026-10-10 and committed verbatim (D-34).

## 4. Subagents (`.claude/agents/<name>.md`), all read-only reviewers

| Subagent | Introduced | Role |
| --- | --- | --- |
| `step-reviewer` | P0 (step 0.4) | compares the diff with "Done means" and "Not in this step"; checks each acceptance item has a test that fails without the change; flags weakened or skipped tests |
| `engine-accuracy-reviewer` | P0 (step 0.4) | tries to refute fills, costs, accounting, rounding, and determinism; every finding carries a reproducing scenario |
| `leakage-auditor` | P0 (step 0.4) | as-of joins, bar labelling, cache keys, walk-forward splits; runs the truncation test |
| `ui-verifier` | P4 (step 4.3, `model: sonnet`) | drives the app at desktop and phone sizes and returns pass or fail per criterion with screenshots |
| `design-reviewer` | P0 (2026-10-10, D-34) | reviews every step that changes `web/` (from step 4.3) and the main pages at the exits of phases with UI through the `apple-design` skill; `web/DESIGN.md` wins where they differ |

## 5. Hooks (`.claude/settings.json`, scripts in `.claude/hooks/*.mjs`)

Hooks are Node scripts in exec form (`"command": "node", "args": [...]`) because `node.exe` is the one interpreter present on Windows, CI, and macOS, and because exec-form hooks cannot spawn `.cmd` shims on Windows. Matchers for shell tools are `Bash|PowerShell`.

- `PostToolUse` on `Edit|Write`: format that file (`rustfmt`, `ruff format`, `prettier`); never blocks.
- `PreToolUse` on `Edit|Write`: deny `.env*`, key files, and market-data extensions outside `fixtures/synthetic/`; return `ask` for golden files. Normalise backslashes before matching.
- `PreToolUse` on `Bash|PowerShell`: deny `--no-verify`, changes to `core.hooksPath`, force pushes, and `git push` to `main`.
- `SessionStart` (`startup|resume|compact`): print the current step, branch, and unproven acceptance items from `PROGRESS.md`.

As built in step 0.4: `format-on-edit.mjs`, `guard-file-paths.mjs` (matcher `Edit|Write|NotebookEdit`), `guard-shell-commands.mjs`, and `session-brief.mjs` (also on `clear`; it prints the step's Done means through `scripts/masterplan_step.py`), plus `reviewer-shell-commands.mjs`, which keeps the reviewers' shell read-only: it is registered for `Bash|PowerShell` next to the shell guard and acts only when the hook input's `agent_type` names an agent in `.claude/agents/`, because Claude Code does not run hooks declared in an agent's frontmatter (Phase 0 exit). The guards never answer `allow`, so the permission rules still decide everything a guard does not forbid, and they fail closed (`onFailure: "block"`, and `ask` on unreadable input). Prettier is not installed, so the formatter covers Rust and Python; web files wait until the Phase 4 kickoff chooses prettier or oxfmt. `scripts/test_hooks.py` is the hooks' smoke test, run by `just test`.

The real commit gate is the git `pre-commit` hook in `.githooks/` (set with `git config core.hooksPath .githooks`), which runs the same checks as CI, because Claude Code hooks do not see the builder's own commits. The `pre-push` hook beside it runs the same guard over each commit a push sends, as CI does over each commit of a pull request, since a file one commit adds and a later one removes passes both checks of the final tree (D-48). The file guard's list of market-data extensions is the commit guard's, and a test keeps the two equal.

## 6. Permissions (`.claude/settings.json`)

- `ask` rules for `git push`, `gh pr merge`, golden regeneration, and any `databento` download command.
- `deny` for reading `.env*` and the credential store.
- Every `Bash(...)` rule is paired with a `PowerShell(...)` twin; a `Bash` deny rule alone silently disables the PowerShell tool.
- Auto mode is the working mode; its classifier already blocks production-style actions. There is no command sandbox on native Windows, so the permission rules and hooks are the guardrails. The guards read each command line: what an allowed program does by itself (a Python script that calls git, for example) and a git alias set in a config file are outside their sight, so they catch mistakes in commands, not a program written to get around them (the security review of the Phase 0 exit).

## 7. Integrations

| Integration | Verdict | Install |
| --- | --- | --- |
| GitHub via `gh` | keep (already signed in) | none |
| Language-server plugins | keep; Claude sees type errors after each edit; installed at project scope on 2026-10-09 (step 0.4) | `/plugins` in the VS Code extension, or its bundled CLI: `claude plugin install rust-analyzer-lsp@anthropic-plugin-directory --scope project`, likewise `pyright-lsp` and `typescript-lsp`; each clone installs them once. Servers on PATH: `rustup component add rust-analyzer`, `pyright-langserver` from the uv environment, `npm install -g typescript-language-server typescript@6` (TypeScript 7 ships no `tsserver`) |
| Playwright | keep from P4: test runner in CI plus the agent-facing CLI for phone emulation and recordings | `pnpm add -D @playwright/test`; `npm install -g @playwright/cli@latest` then `playwright-cli install --skills` |
| `security-guidance` plugin | keep from P4 | `/plugin install security-guidance@claude-plugins-official` |
| Library-docs server (Context7) | add only if stale-API mistakes appear | `npx ctx7 setup --claude` |
| `frontend-design` plugin (`anthropic-plugin-directory`) | keep; installed 2026-10-09 at user scope; every step that touches `web/` loads its skill (D-28) | the plugin directory in the VS Code extension, or `/plugin install frontend-design@anthropic-plugin-directory` |
| `design` plugin (`design-critique`, `accessibility-review`, `ux-copy`, …) | keep; available since 2026-10-09; used at the exits of phases with UI and for copy reviews | the plugin directory |
| `ponytail` plugin (version 5.1.0, from the GitHub marketplace `DietrichGebert/ponytail`) | keep; installed 2026-10-09 at user scope; its `/ponytail-review` (`ponytail:ponytail-review`) reviews every step's branch before the pull request and every phase diff (D-32). Its hooks also switch on "ponytail mode", which steers all coding toward the smallest change, in every session and subagent; `/ponytail off`, or `PONYTAIL_DEFAULT_MODE=off`, turns that mode off and keeps the review | the plugin manager (`/plugins`): add the marketplace `DietrichGebert/ponytail`, then install `ponytail@ponytail` |
| Skip | GitHub MCP (gh suffices), Chrome DevTools MCP (overlaps Playwright), Databento and Modal servers (community only; licensed data stays out of agent context) | |

The standalone `claude` CLI is not installed, by choice (the VS Code extension is used); anything the docs show as a `claude` command is done from the extension.

The bundled `claude-api` skill is the reference for every Anthropic API call in Phase 8.

## 8. Facts verified on 2026-10-05 (Claude Code docs, `https://code.claude.com/docs/en/...`)

| Feature | Where configured | Page | Caveat |
| --- | --- | --- | --- |
| `CLAUDE.md` | repo root; loaded every session and re-read after compaction; `@path` imports | `memory`, `commands` | advisory; enforcement needs hooks or permission rules |
| Rules | `.claude/rules/*.md` with `paths:` globs | `memory` | `paths` is the only frontmatter field read |
| Skills | `.claude/skills/<name>/SKILL.md`; frontmatter `name`, `description`, `when_to_use`, `argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `effort`, `context`, `paths`, … | `skills` | a project skill named `verify` runs before each commit (v2.1.286+) |
| Subagents | `.claude/agents/<name>.md`; `name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `skills`, `hooks`, `memory`, `isolation` | `sub-agents` | background by default; `permissionMode` ignored under an auto-mode parent |
| Hooks | `hooks` in settings: event, `matcher`, handlers (`command`, `http`, `mcp_tool`, `prompt`, `agent`); JSON on stdin; exit 2 blocks | `hooks`, `hooks-guide` | hooks see only Claude's tool calls; Stop hooks are overridden after 8 continuations |
| Settings and modes | `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`; modes `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions` | `settings`, `permissions`, `permission-modes`, `auto-mode-config` | project settings load only from the launch directory; `defaultMode: "auto"` is ignored in project settings |
| MCP | `claude mcp add --transport <http or stdio> … --scope <local, project, or user>`; project scope writes `.mcp.json` | `mcp` | |
| Plan mode, checkpoints, worktrees | Shift+Tab or `/plan`; Esc Esc or `/rewind`; `claude --worktree <name>` | `permission-modes`, `checkpointing`, `worktrees` | checkpoints miss shell-made changes |
| Reviews | `/code-review <level> [--fix] [target]` with levels low, medium, high, max, or ultra; `/security-review` | `code-review`, `commands` | `ultra` runs in the cloud and is billed after three free runs |
| Headless and CI | `claude -p` with `--output-format`, `--allowedTools`, `--max-turns`, `--max-budget-usd`; `anthropics/claude-code-action@v1` | `headless`, `github-actions` | |
| Windows | no Bash sandbox natively; PowerShell is primary when its tool is on; hook `file_path` uses backslashes; exec-form hooks cannot spawn `.cmd` shims | `setup`, `sandboxing`, `tools-reference`, `hooks` | |

On this machine on 2026-10-05: the VS Code extension was 2.1.289; the standalone `claude` CLI was not on PATH on Windows (it is in WSL); `python` and `python3` were Microsoft Store stubs while `python3.12` ran (uv-managed); no `jq`, `pwsh`, `rustc`, or `just`.

### Re-verified on 2026-10-09 (VS Code extension 2.1.295, step 0.4)

Checked against the extension's bundled CLI (`resources/native-binary/claude.exe`) and settings schema, and the docs at code.claude.com. The table above still holds, with these differences:

1. The plugin marketplace on this PC is the built-in `anthropic-plugin-directory`, which serves the plugins of `anthropics/claude-plugins-official`, the id the docs use. In VS Code the plugin manager opens with `/plugins`. Committed `enabledPlugins` switches plugins on in every clone, but each machine still runs the install once.
2. A project skill named `verify` does not run by itself: Claude Code's commit instructions tell Claude to run it before each commit except docs-only and tests-only ones, so the skill must stay model-invocable.
3. A hook that exits 0 without output makes no decision, and the permission rules then apply; only `deny`, `ask`, `allow`, or `defer` decide. PostToolUse cannot block. Handlers gained `if`, `onFailure`, `shell`, and `asyncRewake`; SessionStart also matches `clear` and `fork`.
4. `MultiEdit` no longer exists; `NotebookEdit` is matched separately and sends `notebook_path`.
5. `Edit(...)` rules cover Write and NotebookEdit (there is no `Write(...)` rule); a `Read` deny also blocks writing that file, before any hook runs; `*` may appear anywhere in a Bash rule.
6. Subagent `model` also accepts `fable` and full model IDs, and a subagent can carry its own hooks.
7. `bypassPermissions` is ignored in project settings, like `auto`; the auto-mode classifier reads `autoMode` only from user or managed settings.

Confirmed unchanged: the locations and fields of skills, rules, subagents, hooks, and settings; `paths` on skills as well as rules; `${CLAUDE_PROJECT_DIR}` substituted in exec-form `args`; backslashed `file_path` on Windows; no Bash sandbox on native Windows; a `Bash` deny rule turning off the PowerShell tool unless a `PowerShell` rule exists; the Stop-hook cap of eight consecutive continuations.

On this machine on 2026-10-09: Node 24.18, uv 0.11.33, Rust 1.99.0 with `rust-analyzer`, `just` 1.58, `pyright-langserver` in the uv environment, `typescript-language-server` 6.0.2 with TypeScript 6.0.3 installed globally; no prettier. The standalone `claude` CLI is still not installed.

### Re-verified on 2026-10-11 (VS Code extension 2.1.296, Phase 0 exit)

1. Hooks declared in a subagent's frontmatter do not run, on 2.1.295 and on 2.1.296, although the docs list `hooks` among the subagent fields (item 6 above): a `step-reviewer` wrote a probe file through its shell. A hook registered in `.claude/settings.json` runs for subagents' tool calls as well, with the agent's name in `agent_type` and an `agent_id` in its input, and a change to the settings applies to the running session; the reviewers' guard is registered there now (§5).

On this machine on 2026-10-11: git 2.55.0, gh 2.97.0, Node 24.18.0, pnpm 12.10.1, uv 0.11.33, Python 3.12.13, Rust 1.99.0, `just` 1.58.0, MSVC linker 14.44.35207.

### Re-verified on 2026-10-21 (VS Code extension 2.1.304, Phase 1 exit)

1. The reviewers' guard holds on 2.1.304 (action 7 of `docs/demos/phase-0.md`, run by a `step-reviewer`): `printf probe > reviewer-probe.txt` was refused with `Reviewers are read-only: … writes to reviewer-probe.txt`, and `git status --short` ran. `just doctor` is refused inside a reviewer, since the allow-list names `just check` and `just test` only, as intended; the demo's action 8 runs it in the main session.

On this machine on 2026-10-21: git 2.55.0, gh 2.97.0, Node 24.18.0, pnpm 12.10.1, uv 0.11.33, Python 3.12.13, Rust 1.99.1 (the exit's upgrade step), `just` 1.58.0, MSVC linker 14.44.35207.
