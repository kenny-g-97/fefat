# 05 — The build process

How the masterplan is executed with Claude Code: one step per session, one pull request per step, evidence you can check without reading code.

## 1. The step

Every step in `phases/P*.md` has the same shape:

```text
### N.M Title
Meta line: Depends on · Plan mode: required|optional|skip · Reviews: … · Security: yes|no · Model hint: default|hard
#### Purpose        why it exists; what you can do afterwards
#### Prerequisites  merged steps; tools, keys, or data to have ready
#### Prompt         the copy-paste prompt (goal, reason, what to read, constraints, "Not in this step")
#### Done means     numbered checks, each with the evidence Claude Code must show in the PR
#### Your checks    5–15 minutes, no code reading: a notebook cell, a click path, a number to verify
#### If it fails    symptoms, what to tell Claude Code, when to stop
```

- **Size:** what you can check in about 15 minutes. If a step grows past that, it is split at the phase kickoff.
- **Prompt style:** about 100–350 words, longer for steps that define a subsystem and shorter for polish and end-to-end steps whose specifics come from the phase kickoff. States the outcome, the reason, what to read, constraints, and exclusions. No ordered micro-steps, no code except where a signature is the contract, no capitals or "CRITICAL", no repeats of `CLAUDE.md`, no real data paths, no secrets.
- **Model hint:** `default` means the model you normally use (Claude Opus 5.5 is a good default; Sonnet 5.5 for small UI steps); `hard` means the strongest model available (Fable 5.1) for engine semantics, prop rules, and schema design. These are hints, not requirements.

## 2. The session protocol

1. Open Claude Code in the repo root and start a **fresh session**. Run `/step N.M` (from step 0.5 on), ask for it in plain words ("0.6 is merged, plan the next step"), or paste the step's Prompt. Steps 0.1–0.4 are pasted, because 0.4 is the step that creates the runner.
2. The step runner reads the step, checks `PROGRESS.md` for prerequisites, and creates or reuses the branch `step/N.M-<slug>`.
3. **Plan mode** when the meta line says `plan: required` (new subsystems, schemas, public SDK or API surfaces, engine semantics). Read the plan for outcome and risk, then approve. `optional` means Claude Code decides; `skip` means go straight to work. In practice you open every step in plan mode, so `skip` gets a short plan; you plan on the strongest model and switch to Opus with `/model opus` once you approve.
4. Claude Code loads the skills for the step's area before writing code — `software-design-principles` for any code, `designing-architecture` for a new module or seam, `backtest-expert` for engine, prop, results, and research steps, `frontend-design` and `unslop` with `web/DESIGN.md` for anything under `web/` (`08-code-design.md`; the `step` skill does this from the paths a step touches) — then works in auto mode, commits in small logical commits, and never commits to `main`.
5. Before opening the PR it runs `just check` and `just test`, the `verify` skill, the `step-reviewer` subagent, `/code-review`, the ponytail plugin's `/ponytail-review`, and the specialist reviewers the step lists. `/security-review` runs when the step says `security: yes` and at every phase exit.
6. It opens the PR from the template: what changed, evidence per "Done means" item, deviations from the prompt, follow-ups added to `BACKLOG.md`, and the `PROGRESS.md` row (status, PR number, date, note).
7. You run "Your checks", wait for CI, and squash-merge with the routine in §8; the step's closing message names the next step and the line to start it in a fresh session. GitHub's free plan cannot protect `main` on a private repository (D-30), so nothing on GitHub's side stops a merge with failing checks or a direct push: the routine protects your merges, and Claude Code's hooks block its own pushes to `main` (step 0.4).
8. **Resume after an interruption:** rely on git, the step file, and `PROGRESS.md`, not on the conversation. Same day: continue the session. Otherwise: fresh session, `/step N.M` again; the runner continues from the first unproven "Done means" item.
9. **Two-corrections rule:** if the same problem survives two corrections in one session, start a new session with a sharper prompt (or ask the agent for the smallest failing case first).

## 3. Reviews and subagents

| Reviewer | Runs when | Looks for |
| --- | --- | --- |
| `step-reviewer` | every step | the diff versus "Done means" and "Not in this step"; each acceptance item has a test that fails without the change; no weakened tests |
| `engine-accuracy-reviewer` | engine, data, prop steps | tries to refute fills, costs, accounting, rounding, determinism; every finding carries a reproducing scenario |
| `leakage-auditor` | feature, data, research steps | as-of joins, bar labelling, cache keys, walk-forward splits; runs the truncation test |
| `ui-verifier` | UI steps | drives the app at desktop size with Playwright; returns pass/fail per criterion with screenshots |
| `design-reviewer` (the `apple-design` skill) | UI steps (every step that changes `web/`, from step 4.3); exits of phases with UI | the diff and the screenshots against Apple's interface principles: feedback on press, interruptible spring motion, spatial consistency, materials and depth, tracking and leading by size, reduced motion, transparency, and contrast, and the eight design principles; `web/DESIGN.md` and the brief's own words win where they differ (D-34) |
| `/code-review` | every step (level `medium`; `high` at phase exits) | correctness bugs |
| `/ponytail-review` (the `ponytail` plugin) | every step; phase exits, over the phase diff | code that need not exist: speculative options, abstractions with one use, near-copies, a new dependency for a few lines, a helper the repository already has; also logic, safety, load, missing tests, and speed, each finding with a concrete case in plain English (D-32) |
| `/security-review` | steps marked `security: yes`; phase exits | the local server, uploads, code execution, secrets |
| `design-critique`, `accessibility-review` (the `design` plugin) | exits of phases with UI (P4–P8, P12) | hierarchy, consistency, copy; WCAG 2.1 AA: contrast, keyboard, touch targets, screen readers |

## 4. Verification you can do without reading code

- **Numeric.** Scenario tables (5–20 row cases with hand-computable fills and P&L); property tests (accounting identity, no fill outside traded prices, determinism hash, truncation never changes past feature values); the readable Python reference engine; the NautilusTrader comparison with a written list of known differences; goldens from synthetic data, exact for fills and money and within a stated tolerance for statistics, run on Windows and Linux.
- **Visual.** Each UI step attaches desktop screenshots and a short recording, and gives you a click path. Contract tests assert that UI numbers equal SDK numbers for the same run.
- **Automated.** Unit and integration tests per area; Playwright end-to-end in CI on seeded data; `just e2e` locally.
- **Notebooks.** `notebooks/checks/<phase>.<step>.ipynb` with a two-digit step number (for example `2.06.ipynb`) where a step says so: the last cell prints a verdict you can read.

## 5. Test-data policy

- Licensed market data lives outside the repository under `FEFAT_DATA_DIR` and is referenced by path. It is never committed, never attached to a PR, never pasted into a prompt.
- The repository contains only synthetic fixtures under `fixtures/synthetic/`, each listed in a manifest with its generator, seed, and hash, plus scenario tables under `fixtures/scenarios/`.
- `.gitignore`, the pre-commit guard (`.githooks/pre-commit`), a Claude Code hook, and a CI job reject data files outside `fixtures/synthetic/` by name: binary formats (`.dbn`, `.dbn.zst`, `.parquet`, `.arrow`, `.arrows`, `.feather`, `.duckdb`, `.sqlite`, and the like, with the platforms' own history files, NinjaTrader's `.ncd` and Sierra Chart's `.scid`), plain-text tables (`.csv`, `.tsv`, `.jsonl`, `.ndjson`), spreadsheets (`.xls`, `.xlsx`), and archives and compressors (`.zip`, `.gz`, `.tar`, `.7z`, `.xz`, `.bz2`, `.lz4`, `.zst`). The guard also rejects data saved under another name by its first bytes, and a text export (`.txt`, `.prn`, `.asc`, `.dat`, or no extension) that begins with a table of numbers, such as a NinjaTrader or TradeStation export; Markdown, JSON, and YAML files are never read as tables. It checks every commit, not only the last: the pre-push hook (`.githooks/pre-push`) checks each commit a push sends, and CI each commit of a pull request, so a data file committed and removed again never reaches GitHub (D-48).
- Notebooks are committed without outputs, because outputs can contain licensed data; expected results are described in markdown cells, and the guard rejects notebooks with outputs (`just strip-notebooks` clears them).
- Claude Code may run code against real data and read aggregated output (counts, statistics, a few sample rows); it should not dump raw licensed data into the conversation.

## 6. Keeping the plan true

- **Phase kickoff** (`/phase-kickoff N`, strongest model), delivered as a docs-only PR: read the phase's steps, the ADRs, and the code as it now is; list step assumptions that no longer hold; propose edits to this phase's unstarted steps only, keeping IDs stable; pull in backlog items; ask you the open decisions listed in the phase file.
- **Change control.** A step changes only through a kickoff PR or an "Amendment" block Claude Code proposes when an assumption breaks mid-step; it then stops instead of deviating silently. Finished steps are never rewritten.
- **Phase exit** (`/phase-exit N`): full suite from a clean checkout; specialist review of the phase diff, with `/code-review high` and `/ponytail-review`; `/security-review`; for phases with UI, the `design-reviewer`, `design-critique`, and `accessibility-review` over the main pages; the upgrade step of §7 (toolchain pin, lockfiles, CI pins); a demo script you perform; repeated corrections turned into `CLAUDE.md`, rule, or skill edits (including deletions); docs and runbook updated; backlog groomed; Claude Code version and usage logged; tag `phase-N`.
- **ADRs** in `docs/adr/`: context, decision, consequences, how we would know it is wrong. Written when a decision affects more than one step; superseded, never edited.
- **`PROGRESS.md`** is the single status table. **`BACKLOG.md`** takes everything Claude Code notices but must not do now.

## 7. Failure modes and guardrails

| Failure | Guardrail |
| --- | --- |
| Plan drift | Kickoff reconciliation PRs; immutable step files plus amendments; a "deviations" field in every PR; `step-reviewer` |
| Over-engineering | "Not in this step" in every prompt; backlog for extras; reviewers report gaps, not style; a new dependency needs an ADR line |
| Generic, templated code or UI | the rules of `08-code-design.md` in `.claude/rules/`; import-linter and eslint boundaries in `just check`; one design system in `web/DESIGN.md` built with the `frontend-design` and `unslop` skills, and unslop's audit and checklist at the end of every UI step; `step-reviewer` checks names and state types |
| Silent numeric errors | Scenario tables as the specification; reference engine; cross-engine and cross-OS goldens; golden changes need a changelog entry and your approval; `engine-accuracy-reviewer`; leak detector |
| Tests that assert nothing | Each acceptance item maps to a test shown failing before the change; mutation spot-checks on the engine at phase exit; CI flags removed tests and new skip markers |
| Context loss | One step per session; state in git, the step file, and `PROGRESS.md`; a `SessionStart` hook reprints state after resume and compaction |
| Dependency churn | Lockfiles and toolchain pins committed; no upgrades inside feature steps; one upgrade step per phase exit |
| Cost blowups | Model hints; Sonnet for the UI verifier; no multi-agent workflows by default; a cost preview and an `ask` permission rule before any Databento download |
| Windows quirks | Hooks as Node scripts; permission rules for both PowerShell and Bash; `just` recipes; LF endings; `pathlib`; always `uv run python`, never bare `python` (a Store stub on this PC); CI on Linux as the second opinion |

## 8. Git conventions

- Branches `step/N.M-<slug>`, `kickoff/PN`, `exit/PN`, and `config/<slug>` for a setup change or plan revision outside any step (a skill, reviewer, plugin, setting, or decision). Squash-merge into `main`. Tags `phase-N` at phase exits.
- Commit messages: imperative subject under 72 characters, body explains why. Claude Code's attribution line as configured.
- PR template sections: Summary · Done means (evidence per item) · Deviations · Follow-ups · Progress row · Screenshots/recordings (UI).
- `main` is not protected on GitHub's side: the free plan offers no branch protection for private repositories, and you chose to stay on it (D-30). The repository allows squash merging only and deletes branches after merge (step 0.3); the routine below protects your merges, and Claude Code's hooks block its own pushes to `main` (step 0.4).

### Merging a pull request

From the repository folder, in PowerShell or Git Bash (12 stands for the pull request's number):

```text
gh pr list                               # open pull requests and their numbers
gh pr view 12 --web                      # read it in the browser
gh pr checks 12 --watch                  # from step 0.6 on: wait for CI; every check must pass
gh pr checkout 12                        # try the branch locally for "Your checks"
git switch main                          # back to main when your checks are done
gh pr merge 12 --squash --delete-branch  # squash-merge on GitHub and delete the branch
git pull --ff-only                       # bring the merged commit to this PC
```

- In the browser instead: "Squash and merge", then "Confirm squash and merge"; afterwards `git switch main` and `git pull --ff-only`.
- A failing check means no merge: tell Claude Code which check failed and paste what it printed.
- The Benchmarks check (from step 2.15) runs on a change to the engine or the benchmarks, and warns in its summary when the engine runs more than 30 % slower than the runner's baseline. It passes even then, and when its benchmarks break, so it never stops a merge: read its summary before merging such a change.
- Never `git push origin main` or `git push --force`: on the free plan GitHub accepts both.
- Claude Code opens the pull requests from step 0.4 on. To open one by hand from a step branch: `git push -u origin HEAD`, then `gh pr create --base main --web` (the browser form starts from the template).

## 9. Worked examples

Two steps are written out in full as models for the rest: **2.6** (engine, numeric) and **5.9** (UI, visual) in their phase files. Every other step follows the same shape.
