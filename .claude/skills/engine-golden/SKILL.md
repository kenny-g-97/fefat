---
name: engine-golden
description: How engine behaviour changes are specified and recorded - scenario rows first, then the code, then golden runs and snapshots regenerated only with the builder's approval, a fill-model version bump when fills change, and a changelog entry.
when_to_use: When a change under engine/, fixtures/scenarios/, or fixtures/goldens/ alters fills, costs, accounting, rounding, ordering, or run artifacts; when a golden or .snap file differs from what the code now produces; before any cargo insta accept or just regenerate-goldens.
paths:
  - "engine/**"
  - "fixtures/scenarios/**"
  - "fixtures/goldens/**"
---

# engine-golden — scenarios, goldens, and their changelog

The engine's truth is what the builder can read: the fill specification (`docs/spec/fill-semantics.md`, written in step 2.1), the scenario tables, and the Python reference engine (D-07, D-10). Goldens pin what a run produces, and they change only on purpose (D-11, `docs/masterplan/02-engine-and-data.md` §8). The hooks ask the builder before any golden or snapshot file is written, before an existing scenario or the fill specification is edited (new scenarios stay free to add), and before any regeneration command runs.

## Scenarios first

1. A behaviour change starts as scenarios in `fixtures/scenarios/`: one YAML file per scenario named `S-<area>-NNN`, in the format of that folder's `README.md` (step 2.1). Each row can be computed by hand: the tape (ticks or bars), the orders, the expected fills with prices, the rule identifiers of the specification (`F-MKT-01`, …), and the fidelity.
2. Run the scenarios against both engines: the new rows fail before the code change and pass after it. A scenario's expected value is never edited to match the code; if the specification is wrong, change the specification first, with the builder.

## Goldens

Golden runs live in `fixtures/goldens/<name>/`, each with a `MANIFEST.json`: the command that produced it; the engine, fill-model, and artifact-schema versions; the input fixtures with their hashes; and the output hashes. insta snapshots (`*.snap`) live next to the tests that own them.

When a change makes a golden differ:

1. Show the builder the difference: which runs, which fills or numbers moved, from what to what, and how the change explains it.
2. Bump the fill-model version for every golden change (02 §8: golden snapshots change only with a fill-model version bump and the builder's approval), so the run key changes with the output (02 §4); if the artifact layout changes, bump the artifact-schema version as well.
3. Ask for approval in the conversation. Only after an explicit yes, run `just regenerate-goldens` (the recipe arrives with the first golden in Phase 2), or `cargo insta review` for snapshots; never `INSTA_UPDATE=always`, and never edit a golden by hand.
4. Add an entry to `fixtures/goldens/CHANGELOG.md`: date, pull request, reason, the scenarios and goldens affected, and the version bumped.
5. CI asserts identical golden hashes on Windows and Linux. A golden that differs between the two systems is a determinism bug to fix, not a golden to regenerate.

## Never

Write inline snapshots (`assert_snapshot!(value, @"…")`): snapshots live in `.snap` files, where the guards see every change. Accept a snapshot to make a failing test pass without understanding the difference; regenerate goldens in a step whose prompt does not call for a behaviour change; edit a golden or a scenario's expected value by hand.
