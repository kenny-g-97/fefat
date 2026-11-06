# ADR-0020: Workspace files are the record; the app's database indexes them

Decision log: [D-84](../masterplan/DECISIONS.md), 2026-11-06

## Context

By the end of Phase 3 the SDK keeps every record it saves as a file under `FEFAT_HOME`: feature versions as `workspaces/default/features/<name>/v<n>.json`, the leak detector's reports beside them under `validations/`, the import profiles a trader saved under `profiles/`, and saved runs as folders named by their run key (D-62), with a lookup of their requests. A feature version is immutable and named by its content hash, created whole by `create_atomically`, which never replaces a file, and a run's folder never changes once renamed into place (ADR-0009); a saved profile is written once, while a validation report is replaced by the next validation of the same hash. Step 4.1, written in October 2026, moves the feature versions into the app's SQLite database and keeps the files as a backup. But the SDK is the product: a notebook saves with `ff.features.save`, and the SDK may not import the app (ADR-0016). A database as the record would either couple the SDK to the app's schema and migrations, or leave what a notebook saves unseen by the app until someone imports it again.

## Decision

The files stay the record, and the app's database indexes them beside the app's own state: its settings, sessions, API tokens, jobs, events, and, from Phase 8, proposals.

- The SDK writes and reads the files as it does today and never opens the database.
- The app saves through the SDK and then indexes what was written.
- `fefat db import-workspace` rescans the workspace. It adds a row for each file it has not seen and moves and deletes nothing, so it can run at any time, and it rebuilds the index from the files alone.
- Strategy versions, from Phase 5, follow the same rule.

## Consequences

- A notebook and the app save to the same place, and a version saved by either is seen by both once indexed.
- The index can be deleted and rebuilt from the files, like the caches. The app's own state cannot, and is backed up with the workspace by `fefat backup` (Phase 13).
- Rows that index records are insert-only. A version's row never changes, and a validation report replaced on disk keeps its row, so the index holds every report it saw, while a rebuild holds those still on disk.
- A list, a search, or a join reads the database; a record's content is read from its file, through the SDK.
- Step 4.1 indexes feature versions, the leak detector's reports, and import profiles. The steps that first write runs, strategies, and studies to the database index them the same way.

## How we would know it is wrong

If the app needed to change several records at once as one step, which separate files cannot make atomic, or if a rescan of the workspace grew too slow to run when the app starts, the database would have to become the record, with the SDK reading it through a port.

## Status

Accepted; recorded at the Phase 4 kickoff, 2026-11-06.
