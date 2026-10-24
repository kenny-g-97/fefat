# Goldens changelog

Every change of a golden under `fixtures/goldens/`, newest first, written in the pull request that makes it, after the builder's approval and the version bump the change belongs to (the `engine-golden` skill). `just regenerate-goldens` writes the goldens; each folder's `MANIFEST.json` names the command, the versions, the inputs, and the outputs.

| Date | Pull request | Goldens | Reason | Versions |
| --- | --- | --- | --- | --- |
| 2026-10-25 | #29 | `determinism` | The first golden (step 2.4): the digest of a seeded tape's records and offsets as the in-memory reader serves them, a seeded run of fills and marks through the ledger, and a run key. No scenario changes. | engine 1, fill model 1, artifact schema 1: the first values, none bumped |
