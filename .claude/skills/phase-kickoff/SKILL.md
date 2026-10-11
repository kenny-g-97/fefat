---
name: phase-kickoff
description: Open masterplan phase N - read its steps, the ADRs, and the code as it now stands; list the step assumptions that no longer hold; amend only unstarted steps, keeping IDs stable; pull in backlog items; ask the builder the phase's open decisions; open a docs-only pull request from kickoff/PN and record the kickoff in PROGRESS.md.
argument-hint: "N"
disable-model-invocation: true
---

# /phase-kickoff — reconcile a phase before it starts

Arguments: `$ARGUMENTS` (the phase number N).

The procedure is `docs/masterplan/05-build-process.md` §6. Run it with the strongest model available.

1. Open the phase file `docs/masterplan/phases/P<NN>-*.md` (two digits). Read its header (Goal, You get, Depends on, Skills, Open decisions) and its `## Kickoff` prompt, which names the documents to read and is followed as written.
2. Check that the previous phase is closed: its exit is recorded in the second table of `docs/masterplan/PROGRESS.md` (Phase 0 has no kickoff). If it is not, stop and suggest `/phase-exit <N-1>`.
3. Run `git fetch origin --prune`, then `git switch --no-track -c kickoff/P<N> origin/main` (or switch to the existing branch).
4. Read the phase's steps, the ADRs in `docs/adr/`, `docs/masterplan/DECISIONS.md`, and the code the steps build on, as it now stands.
5. List every step assumption that no longer holds: the step, what it assumes, what is true now, with file references. Propose edits to unstarted steps only; never rewrite a finished step and never change an ID. Each edited step gets an "Amendment" block dated today.
6. Pull in the `docs/masterplan/BACKLOG.md` items that name this phase or one of its steps, and say which step absorbs each one.
7. Ask the builder the phase's open decisions with AskUserQuestion, a few at a time, with the recommended option first. A decision that affects more than one step becomes a new entry in `docs/masterplan/DECISIONS.md`; one marked **ADR** also gets its record in `docs/adr/` in the same pull request, copied from `0000-template.md` with the next number (`check_masterplan.py` refuses a marked decision without its record).
8. `uv run python docs/masterplan/tools/check_masterplan.py` must pass.
9. Open a docs-only pull request (no code): commit; fill the kickoff columns of the phase row in PROGRESS.md (the predicted pull request number and today's date, predicted as `/step` does); `git push -u origin HEAD`; `gh pr create --base main` with the template, whose Done means are the reconciled assumptions and the decisions asked.
10. Finish with the pull request URL and a short list of what changed in the phase.
