"""The app's database, `<FEFAT_HOME>/fefat.sqlite` (step 4.1, `01-architecture.md` section 5): its
own state and an index of the workspace's files, which stay the record (D-84, ADR-0020).

`schema` opens the file and runs the migrations under `migrations/`, `models` describes the
tables, `uuid7` makes their ids, `workspace_index` indexes the files the SDK saves,
`access_records` keeps the password's hash, the login sessions, and the API tokens (step 4.2),
`preferences` the trader's choices (step 4.3), and `job_records` the jobs and their streams'
events (step 4.4)."""
