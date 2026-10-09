---
paths:
  - "docs/masterplan/**"
---

# Masterplan rules

From `docs/masterplan/05-build-process.md` §1 and §6, and the conventions in `docs/masterplan/README.md`.

- **Stable IDs.** Step IDs are never renumbered or reused.
- **Finished steps are never rewritten.** A change arrives as an "Amendment" block appended under the step (date, what changed, why), or through a phase kickoff PR that edits unstarted steps only.
- **Shape.** Every step keeps its heading `### N.M Title`, its meta line `Depends on: … · Plan mode: … · Reviews: … · Security: … · Model hint: …`, and the six sections in order (Purpose, Prerequisites, Prompt, Done means, Your checks, If it fails), optionally followed by Amendment sections.
- **Prompts** start with "Masterplan step N.M — Title" and end with "Not in this step".
- **Checker.** `uv run python docs/masterplan/tools/check_masterplan.py` stays green after every edit; `scripts/masterplan_step.py` reads the same format.
- **Status.** `PROGRESS.md` is the single status table; `BACKLOG.md` takes what is noticed but not done now; `DECISIONS.md` entries are never rewritten, only superseded by a later entry.
- **Nothing private.** No real data paths, account details, or secrets in any masterplan file.
