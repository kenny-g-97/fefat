"""The app's database, `<FEFAT_HOME>/fefat.sqlite` (step 4.1, `01-architecture.md` section 5): its
own state and an index of the workspace's files, which stay the record (D-84, ADR-0020).

`schema` opens the file and runs the migrations under `migrations/`, `models` describes the
tables, `uuid7` makes their ids, and `workspace_index` indexes the files the SDK saves."""
