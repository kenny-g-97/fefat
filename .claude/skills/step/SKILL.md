---
name: step
description: Run one masterplan step N.M under the session protocol of docs/masterplan/05-build-process.md section 2 - brief, prerequisites, branch, skills, plan mode, work, checks, reviewers, pull request, and the PROGRESS.md row. With --dry-run it only previews the step.
argument-hint: "N.M [--dry-run]"
disable-model-invocation: true
---

# /step — run one masterplan step

Arguments: `$ARGUMENTS`

The first argument is the step ID `N.M` (for example `0.5` or `2.11`); `--dry-run` anywhere means preview only. Without a valid ID, print `Usage: /step N.M [--dry-run]` and stop.

The protocol is `docs/masterplan/05-build-process.md` §2, and this skill is its checklist; the step's own text in its phase file wins over anything here. Read the masterplan through `uv run --no-project python scripts/masterplan_step.py` (below: `masterplan_step.py`), never by parsing it yourself.

## 1. Brief

1. Run `masterplan_step.py brief <ID>`. An unknown ID exits with code 2: report it and stop.
2. Show the builder, briefly: the title with its phase file and line, the meta line, **Purpose**, **Prerequisites**, **Done means** (numbered), the skills to load, and the branch. If the model hint is `hard`, say which model this session runs on.
3. With `--dry-run`, stop here: "Dry run: nothing was changed." Otherwise ask with AskUserQuestion, "Proceed with step N.M?" (Proceed / Not now), and stop unless the answer is Proceed.

## 2. Prerequisites and branch

1. Run `git fetch origin --prune`, then `masterplan_step.py status <ID>`.
2. Every `Depends on` step must be `done` (or `skipped`) in PROGRESS.md **on origin/main**: a row turns true only when its pull request is merged. If one is not, stop and list it; continue only on the builder's explicit word, and record that under Deviations.
3. `git status --porcelain` must show no changes to tracked files; untracked files are fine. Never stash, reset, or discard anything to get a clean tree: ask instead.
4. Branch:
   - exactly one `step/<ID>-*` branch, local or on origin: switch to it (`git switch <branch>`, or `git switch --track origin/<branch>` when it exists only on origin);
   - several: ask which one;
   - none: `git switch --no-track -c step/<ID>-<slug> origin/main`, with the slug that `status` suggests (shorter if a person would choose shorter). `--no-track` keeps the new branch from tracking main.
5. Resume instead of restarting when the branch has commits (`git log --oneline origin/main..HEAD`) or a pull request (`gh pr list --head <branch> --state all`): merged means the step is finished (say so, run `masterplan_step.py next`, and stop); open means continue at section 5 with what remains; otherwise check each Done-means item for evidence (its test exists and passes, its file is there) and start from the first item without any.

## 3. Skills and plan

1. Load the skills that the brief suggests, adjusted by the phase file's own **Skills** note and by the paths the step touches (`docs/masterplan/08-code-design.md`):
   - `software-design-principles` for any code;
   - `designing-architecture` for a new module, package, crate, port, adapter, or seam;
   - `backtest-expert` for engine, prop, results, and research work;
   - `frontend-design:frontend-design` for anything under `web/`, after reading `web/DESIGN.md` (once step 4.3 has written it);
   - `engine-golden` when engine, scenario, or golden files change;
   - `claude-api` for any code that calls the Anthropic API.
2. Read the documents the step's prompt names and the rules in `.claude/rules/` for the areas it touches.
3. Plan mode: `required` means enter plan mode (EnterPlanMode) before any edit and wait for approval; `optional` means plan when the step adds a schema, a public API, or a module, or touches more than about six files; `skip` means start.

## 4. Work

- The step's **Prompt** is the task, including its "Not in this step". Anything else goes to `docs/masterplan/BACKLOG.md` (one line: what, why, source), never into the diff.
- If an assumption of the step no longer holds, stop: propose an "Amendment" block for the step (date, what changed, why) and wait for the builder.
- Each acceptance item gets a test that fails without the change. Show it failing first and keep that output for the pull request.
- Small logical commits, each with an imperative subject under 72 characters ending in `(step <ID>)` and a body that says why. Never commit on `main`, never use `--no-verify`.
- Two-corrections rule: if the same problem survives two corrections, stop and say so.

## 5. Checks and reviews

Before the pull request, run these in order, fix what they find, and re-run what each fix touches (at most two rounds, then report what remains):

1. `just check` and `just test`.
2. The `verify` skill with `--full`.
3. The `step-reviewer` subagent, given the step ID and the range `origin/main...HEAD`.
4. The reviewers on the meta line: the `engine-accuracy-reviewer` and `leakage-auditor` subagents; `code-review` there means step 5 runs at `high`; `ui-verifier` arrives with step 4.3 (until then, note it under Deviations).
5. `/code-review medium` (or `high`, see above).
6. `/security-review` when the meta line says `Security: yes`.

## 6. Pull request and PROGRESS.md

1. Predict the pull request number: one more than the highest number that `gh pr list --state all --limit 1 --json number` and `gh issue list --state all --limit 1 --json number` print (pull requests and issues share one sequence).
2. Update only this step's row in `docs/masterplan/PROGRESS.md`: status `done`, the predicted `#number`, today's date, and a one-line note (amendments, notable deviations). The row becomes true when the pull request is merged. Commit it as `Record step <ID> in PROGRESS.md`.
3. `git push -u origin HEAD` (the builder approves the push).
4. Write the body from `.github/pull_request_template.md` into a file in the scratchpad and run `gh pr create --base main --title "<subject> (step <ID>)" --body-file <file>`. Sections: Summary (the step, linked to its phase file with a full github.com URL), Done means (every item in order with its evidence: the command and what it printed, the test that fails without the change, a file), Deviations (or "None."), Follow-ups (the BACKLOG lines added), Progress row (as committed), Screenshots or recordings (UI steps; otherwise "Not a UI step."). End with the attribution line configured for pull requests.
5. If GitHub gave a different number than predicted, fix the row, commit, push, and update the body with `gh pr edit <number> --body-file <file>`.
6. Finish with the pull request URL and the step's **Your checks**, word for word, for the builder.

## Never

Switch to or commit on `main`; merge a pull request (the builder does, with the routine in `docs/masterplan/05-build-process.md` §8); change another step's row; start a second step in the same session.
