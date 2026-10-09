---
name: phase-exit
description: Close masterplan phase N - full suite from a clean checkout, specialist reviews of the phase diff, /code-review high, /security-review, design reviews for UI phases, a demo script, the retro into CLAUDE.md, rules, and skills, backlog grooming, the Claude Code version, and an exit pull request from exit/PN; the builder tags phase-N after merging.
argument-hint: "N"
disable-model-invocation: true
---

# /phase-exit — close a phase

Arguments: `$ARGUMENTS` (the phase number N).

The procedure is `docs/masterplan/05-build-process.md` §6. The phase file's `## Phase exit` prompt adds what is specific to the phase and is followed as written.

1. Every step of the phase must be `done` or `skipped` on origin/main (`uv run --no-project python scripts/masterplan_step.py next`, and the rows in PROGRESS.md). If one is not, stop and list it.
2. Run `git fetch origin --prune`, then `git switch --no-track -c exit/P<N> origin/main` (or switch to the existing branch). The phase diff is `git diff phase-<N-1>..origin/main` (for Phase 0, from the first commit).
3. **Clean checkout.** `git worktree add <scratchpad>/exit-P<N> origin/main`; there run `just setup`, `just doctor`, `just check`, and `just test` (and `just e2e` once it exists), and record each result; then `git worktree remove` it.
4. **Reviews of the phase diff.** The specialist reviewers the exit prompt names (`engine-accuracy-reviewer`, `leakage-auditor`, `step-reviewer`), `/code-review high`, and `/security-review`. For phases with UI (4, 5, 6, 7, 8, 12), also the `design:design-critique` and `design:accessibility-review` skills over the main pages. Small findings are fixed in this pull request; the rest become backlog items or steps.
5. **Demo script** for the builder, in `docs/demos/phase-<N>.md` or the file the exit prompt names: numbered actions, each with what it should show, runnable without reading code.
6. **Retro.** Corrections the builder had to repeat during the phase become edits to `CLAUDE.md`, `.claude/rules/`, or a skill, including deletions of what did not help. Keep `CLAUDE.md` under 150 lines.
7. Update the documents and runbook the phase touched, and groom `docs/masterplan/BACKLOG.md`: drop what is done, retarget the rest.
8. Record the Claude Code version: the newest `anthropic.claude-code-*` folder under `~/.vscode/extensions/`, whose `resources/native-binary/claude.exe --version` prints it; add the session usage if the builder shares it.
9. Fill the exit columns of the phase row in PROGRESS.md (predicted pull request number, date, tag `phase-<N>`), commit, `git push -u origin HEAD`, and `gh pr create --base main` with the template, linking the demo script in the Summary.
10. Finish with the pull request URL and the tag commands for the builder to run after merging it: `git switch main`, `git pull --ff-only`, `git tag phase-<N>`, `git push origin phase-<N>`.
