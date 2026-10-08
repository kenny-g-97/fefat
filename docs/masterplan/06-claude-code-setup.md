# 06 — Claude Code setup

What step 0.4 installs in the repository so every later session works the same way. Feature names and locations were verified against the Claude Code docs on 2026-10-05 (URLs at the end); step 0.4 re-checks them against the version installed at the time.

## 1. `CLAUDE.md` (100–150 lines)

A short bootstrap `CLAUDE.md` exists since the repository preparation (2026-10-08) so that the sessions for steps 0.1–0.3 know the ground rules; step 0.4 replaces it with the full file, which holds what every session must know and nothing a hook enforces:

- **Repo map and commands:** the handful of `just` recipes (`setup`, `doctor`, `check`, `test`, `e2e`, `dev`, `up`), identical on Windows, CI, and macOS.
- **Workflow:** one masterplan step per session through `/step`; never commit to `main`; the builder merges; the step protocol lives in `docs/masterplan/05-build-process.md`.
- **Invariants, each linked to its ADR:** deterministic runs; no look-ahead; licensed data never in the repo; goldens change only with the builder's approval; tests are never weakened to pass; versions and runs are immutable.
- **Windows notes:** LF endings; `pathlib`; PowerShell and Git Bash both exist; private data through `FEFAT_DATA_DIR`.
- **Pointers:** architecture docs by path; the `claude-api` skill for any Anthropic API code.
- **Not in it:** language conventions (rules), procedures (skills), architecture prose (docs).

## 2. Rules (`.claude/rules/*.md`, each with `paths:` frontmatter)

| Rule file | Paths | Content |
| --- | --- | --- |
| `engine.md` | `engine/**` | seeded randomness and an injected clock only; ordered collections wherever order affects output; integer money; every behaviour change comes with a scenario table; `unwrap`/`panic`/indexing lints |
| `python.md` | `python/**` | uv only; ruff and pyright; Polars first; no network in unit tests; Pydantic models at every boundary |
| `web.md` | `web/**` | API types generated from OpenAPI; numbers come from the API, never recomputed in the client; every page works at 390 px; stable `data-testid`s; no remote images |
| `db.md` | `python/fefat_app/db/**` | new migration files only, never edited; versioned rows are insert-only |
| `masterplan.md` | `docs/masterplan/**` | stable step IDs; finished steps are not rewritten; amendments are appended |

## 3. Skills (`.claude/skills/<name>/SKILL.md`)

| Skill | Invocation | Does |
| --- | --- | --- |
| `step` | `/step N.M` | reads the step from its phase file, checks prerequisites in `PROGRESS.md`, creates or reuses the branch, runs plan mode if required, works, runs checks and reviewers, opens the PR, updates `PROGRESS.md` |
| `phase-kickoff` | `/phase-kickoff N` | the reconciliation procedure in `05-build-process.md` §6 |
| `phase-exit` | `/phase-exit N` | the exit procedure in `05-build-process.md` §6 |
| `verify` | model-invoked | tiered checks by changed area (Rust, Python, web, docs), with the UI recipe (Playwright at desktop and phone sizes, screenshots) in a supporting file |
| `engine-golden` | `paths: engine/**` | how to add scenarios, regenerate goldens with approval, and write the changelog entry |
| `prop-preset-refresh` | manual (P7) | re-read each firm's published rules from the sources in the preset, propose a new preset version with URL and date; never edit an existing version |

## 4. Subagents (`.claude/agents/<name>.md`), all read-only reviewers

| Subagent | Introduced | Role |
| --- | --- | --- |
| `step-reviewer` | P0 (step 0.4) | compares the diff with "Done means" and "Not in this step"; checks each acceptance item has a test that fails without the change; flags weakened or skipped tests |
| `engine-accuracy-reviewer` | P0 (step 0.4) | tries to refute fills, costs, accounting, rounding, and determinism; every finding carries a reproducing scenario |
| `leakage-auditor` | P0 (step 0.4) | as-of joins, bar labelling, cache keys, walk-forward splits; runs the truncation test |
| `ui-verifier` | P4 (step 4.3, `model: sonnet`) | drives the app at desktop and phone sizes and returns pass or fail per criterion with screenshots |

## 5. Hooks (`.claude/settings.json`, scripts in `.claude/hooks/*.mjs`)

Hooks are Node scripts in exec form (`"command": "node", "args": [...]`) because `node.exe` is the one interpreter present on Windows, CI, and macOS, and because exec-form hooks cannot spawn `.cmd` shims on Windows. Matchers for shell tools are `Bash|PowerShell`.

- `PostToolUse` on `Edit|Write`: format that file (`rustfmt`, `ruff format`, `prettier`); never blocks.
- `PreToolUse` on `Edit|Write`: deny `.env*`, key files, and market-data extensions outside `fixtures/synthetic/`; return `ask` for golden files. Normalise backslashes before matching.
- `PreToolUse` on `Bash|PowerShell`: deny `--no-verify`, changes to `core.hooksPath`, force pushes, and `git push` to `main`.
- `SessionStart` (`startup|resume|compact`): print the current step, branch, and unproven acceptance items from `PROGRESS.md`.

The real commit gate is the git `pre-commit` hook in `.githooks/` (set with `git config core.hooksPath .githooks`), which runs the same checks as CI, because Claude Code hooks do not see the builder's own commits.

## 6. Permissions (`.claude/settings.json`)

- `ask` rules for `git push`, `gh pr merge`, golden regeneration, and any `databento` download command.
- `deny` for reading `.env*` and the credential store.
- Every `Bash(...)` rule is paired with a `PowerShell(...)` twin; a `Bash` deny rule alone silently disables the PowerShell tool.
- Auto mode is the working mode; its classifier already blocks production-style actions. There is no command sandbox on native Windows, so the permission rules and hooks are the guardrails.

## 7. Integrations

| Integration | Verdict | Install |
| --- | --- | --- |
| GitHub via `gh` | keep (already signed in) | none |
| Language-server plugins | keep; Claude sees type errors after each edit | `/plugin install rust-analyzer-lsp@claude-plugins-official`, `pyright-lsp`, `typescript-lsp`, with the server binaries on PATH |
| Playwright | keep from P4: test runner in CI plus the agent-facing CLI for phone emulation and recordings | `pnpm add -D @playwright/test`; `npm install -g @playwright/cli@latest` then `playwright-cli install --skills` |
| `security-guidance` plugin | keep from P4 | `/plugin install security-guidance@claude-plugins-official` |
| Library-docs server (Context7) | add only if stale-API mistakes appear | `npx ctx7 setup --claude` |
| Skip | GitHub MCP (gh suffices), Chrome DevTools MCP (overlaps Playwright), Databento and Modal servers (community only; licensed data stays out of agent context) | |

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
