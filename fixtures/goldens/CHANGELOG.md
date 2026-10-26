# Goldens changelog

Every change of a golden under `fixtures/goldens/`, newest first, written in the pull request that makes it, after the builder's approval and the version bump the change belongs to (the `engine-golden` skill). `just regenerate-goldens` writes the goldens; each folder's `MANIFEST.json` names the command, the versions, the inputs, and the outputs.

| Date | Pull request | Goldens | Reason | Versions |
| --- | --- | --- | --- | --- |
| 2026-10-26 | #31 | `determinism` | The tick loop of step 2.6 joins the digest: the orders, fills, and event log of the seeded tape's trades and TBBO records, run with 20 seeded orders, beside the records, the ledger run, and the run key, which the engine version moves. The digest of seed 20260308 goes from `0e0916c2…f239a` to `147d5a6a…77e5c`. No scenario changes; the fill model is first implemented, not changed. | engine 1 to 2; fill model 1 and artifact schema 1 unchanged |
| 2026-10-25 | #29 | `determinism` | The first golden (step 2.4): the digest of a seeded tape's records and offsets as the in-memory reader serves them, a seeded run of fills and marks through the ledger, and a run key. No scenario changes. | engine 1, fill model 1, artifact schema 1: the first values, none bumped |
