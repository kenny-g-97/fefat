---
name: phase-exit
description: Close masterplan phase N - full suite from a clean checkout, specialist reviews of the phase diff, /code-review high, /ponytail-review, /security-review, design reviews for UI phases, the upgrade step, a demo script, the retro into CLAUDE.md, rules, and skills, backlog grooming, the Claude Code version, and an exit pull request from exit/PN; the builder tags phase-N after merging.
argument-hint: "N"
disable-model-invocation: true
---

# /phase-exit — close a phase

Arguments: `$ARGUMENTS` (the phase number N).

The procedure is `docs/masterplan/05-build-process.md` §6. The phase file's `## Phase exit` prompt adds what is specific to the phase and is followed as written.

1. Every step of the phase must be `done` or `skipped` on origin/main (`uv run --no-project python scripts/masterplan_step.py next`, and the rows in PROGRESS.md). If one is not, stop and list it.
2. Run `git fetch origin --prune`, then `git switch --no-track -c exit/P<N> origin/main` (or switch to the existing branch). The phase diff is `git diff phase-<N-1>..origin/main` (for Phase 0, from the first commit).
3. **Clean checkout.** `git worktree add <scratchpad>/exit-P<N> origin/main`; there run `just setup`, `just doctor`, `just check`, and `just test` (and `just e2e` once it exists), and record each result; then `git worktree remove` it. When Windows refuses ("Filename too long": pnpm's `node_modules` under the long scratchpad path), delete the folder with `node -e "require('fs').rmSync(process.argv[1], {recursive: true, force: true})" <folder>` and run `git worktree prune`. uv ignores the `VIRTUAL_ENV` that VS Code sets for the main checkout, but the doctor's Python row shows it.
4. **Reviews of the phase diff.** The specialist reviewers the exit prompt names (`engine-accuracy-reviewer`, `leakage-auditor`, `step-reviewer`), `/code-review high`, `/ponytail-review` (the ponytail plugin, D-32), and `/security-review`, each given the phase diff by its range. `/security-review` fills in the current branch's diff by itself, so run its method (a finding pass, a false-positive pass per finding, a cut below 8) over the phase diff, and a phase-wide `step-reviewer` can use up its turns, so ask it for the table per step first. For phases with UI (4, 5, 6, 7, 8, 12), also the `design-reviewer` subagent (D-34) and the `design:design-critique` and `design:accessibility-review` skills over the main pages. Small findings are fixed in this pull request; the rest become backlog items or steps.
5. **Upgrade step** (05 §7). Bump what is behind and run the full suite again: the Rust pin in `engine/rust-toolchain.toml` (`rustup check`); the lockfiles (`uv lock --upgrade --dry-run`, `cargo update --dry-run` in `engine/`, `pnpm --dir web outdated`); the commit pins and release comments of the actions in `.github/workflows/ci.yml` (D-33; `git ls-remote --tags` lists their releases) and its uv, `just`, and Node versions, which move with the PC's. Major versions and tools on the PC are the builder's call; a change to a logged decision gets a new entry in `DECISIONS.md`.
6. **Demo script** for the builder, in `docs/demos/phase-<N>.md` or the file the exit prompt names: numbered actions, each with what it should show, runnable without reading code.
7. **Retro.** Corrections the builder had to repeat during the phase become edits to `CLAUDE.md`, `.claude/rules/`, or a skill, including deletions of what did not help. Keep `CLAUDE.md` under 150 lines.
8. Update the documents and runbook the phase touched, and groom `docs/masterplan/BACKLOG.md`: drop what is done, retarget the rest.
9. Record the Claude Code version: the newest `anthropic.claude-code-*` folder under `~/.vscode/extensions/`, whose `resources/native-binary/claude.exe --version` prints it; add the session usage if the builder shares it. When the version changed since the last exit, prove the reviewer guard again with action 7 of `docs/demos/phase-0.md`: the guard relies on the `agent_type` that Claude Code sends its hooks.
10. Fill the exit columns of the phase row in PROGRESS.md (predicted pull request number, date, tag `phase-<N>`), commit, `git push -u origin HEAD`, and `gh pr create --base main` with the template, linking the demo script in the Summary.
11. Finish with the pull request URL and the tag commands for the builder to run after merging it: `git switch main`, `git pull --ff-only`, `git tag phase-<N>`, `git push origin phase-<N>`.
