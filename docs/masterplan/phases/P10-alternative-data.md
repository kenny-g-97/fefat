# Phase 10 — Alternative data

**Goal.** Files and URLs become datasets with publication timestamps, through ingestion recipes the agent writes and you approve; datasets join features without look-ahead; the pages make it all visible; hostile files cannot hurt.

**You get.** Drop in an economic calendar, a COT report, or a sentiment series, ask the agent to turn it into a feature, approve, preview, and use it in a strategy.

**Depends on.** Phase 8 (the agent) and Phase 6 (the lab).

**Open decisions for the kickoff.** The first two alternative datasets you want (for example an economic-event calendar and a daily sentiment series); where they come from.

## Kickoff

```text
/phase-kickoff 10 — Read docs/masterplan/phases/P10-alternative-data.md, docs/masterplan/02-engine-and-data.md §6 (alternative data), and docs/masterplan/04-agent.md. Ask me the open decisions. Reconcile with uploads, the executor, the runtime's dataset inputs, and the proposals model; open the kickoff PR.
```

## Steps

### 10.1 Uploads and the dataset model

Depends on: 9.6 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: hard

#### Purpose

Files can be uploaded safely, and datasets have a model with vintages and the two timestamps that make point-in-time joins possible.

#### Prerequisites

- Phase 10 kickoff done.

#### Prompt

```text
Masterplan step 10.1 — Uploads and the dataset model.

Extend the upload endpoint from 5.12 (`POST /v1/uploads`: multipart, size and type limits, stored under workspaces/default/uploads/<id>/ with a SHA-256) with a sniffed type and the alternative-data formats (JSON, XLSX, PDF, and text, besides CSV, TSV, and Parquet), and add `GET /v1/uploads/{id}/inspect` (schema, row count, sample rows, encoding, delimiter, detected date columns; produced in the executor, never in the server process). Define the alternative-dataset model in the SDK: long format rows with `entity`, `field`, `value`, `event_time` (when the fact refers to), and `available_at` (when it was known), with a vintage id per ingestion; versioned datasets in the database (`datasets` with `kind: alt`) and Parquet storage under the workspace. Document the model in docs/data-guide.md.

Tests: limits enforced; inspection of each supported type; a dataset vintage is immutable.

Not in this step: recipes, joins, UI.
```

#### Done means

1. Upload and inspection tests pass for every supported type.
2. The dataset model round-trips and vintages are insert-only (test).
3. Inspection never runs in the server process (test).

#### Your checks

- Upload a CSV on the `/docs` page (`POST /v1/uploads`) and open its inspection (`GET /v1/uploads/{id}/inspect`): columns, types, and sample rows are right.

#### If it fails

- XLSX inspection pulls in openpyxl; keep it inside the executor environment, not the server's.

### 10.2 Ingestion recipes

Depends on: 10.1 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: hard

#### Purpose

A recipe is versioned Python that turns an upload into a dataset vintage, run in the sandbox and validated.

#### Prerequisites

- Step 10.1 merged.

#### Prompt

```text
Masterplan step 10.2 — Ingestion recipes.

Implement `ingestion_recipes`: a versioned Python function `ingest(path) -> polars.DataFrame` in the long format with `event_time` and `available_at` (the recipe must say how `available_at` is derived: a column, a fixed lag after `event_time`, or the file's publication date), executed in the executor with no network and a time limit, validated (schema, monotonic availability, no `available_at` before `event_time`, duplicates), and producing a dataset vintage. `POST /v1/uploads/{id}/recipes` creates a version; `POST /v1/datasets/{id}/ingest` runs one as a job. Provide two built-in recipes (a generic dated CSV with a configurable lag; an economic-calendar CSV).

Tests: validation failures for each rule; a recipe cannot read outside its upload folder; re-running a recipe on the same file yields an identical vintage hash.

Not in this step: joins, the agent, UI.
```

#### Done means

1. Validation tests pass; the built-in recipes ingest the synthetic alt-data fixtures.
2. Vintage hashes are deterministic (test).
3. Recipes run only in the executor (test).

#### Your checks

- Ingest your first real dataset with the generic recipe and a lag of one day; look at the resulting vintage's first rows.

#### If it fails

- `available_at` derivation is the whole point; a recipe that sets it equal to `event_time` for data published later must be rejected by review, not by code (the leakage-auditor looks for it).

### 10.3 Publication-time joins and datasets as feature inputs

Depends on: 10.2 · Plan mode: required · Reviews: step-reviewer, leakage-auditor · Security: no · Model hint: hard

#### Purpose

A feature can use an alternative dataset and only ever sees what was known at the bar's close.

#### Prerequisites

- Step 10.2 merged.

#### Prompt

```text
Masterplan step 10.3 — Publication-time joins and datasets as feature inputs.

Implement dataset inputs in the feature runtime: `inputs={"cal": ff.dataset("econ-calendar", vintage="latest")}` joins the dataset onto the signal-bar grid with a backward as-of join on `available_at` plus a configurable safety lag, exposing `staleness` (time since the last available row) and the matched `event_time`; event-style datasets can also be exposed as "next scheduled event within N bars" features. The leak detector truncates datasets by `available_at` at each cut. Vintages are pinned in feature versions and runs.

Tests: a planted leak (a row with `available_at` after the cut) is caught; a feature using a dataset passes validation when timestamps are right; the pinned vintage appears in run.json.

Not in this step: UI, the agent.
```

#### Done means

1. Leak and pinning tests pass.
2. A "minutes until the next scheduled event" feature works on the synthetic calendar fixture.
3. The runtime docs explain `available_at`, the lag, and staleness.

#### Your checks

- Build a feature from your ingested dataset in a notebook, validate it, and use it in a strategy run; `run.json` lists the dataset vintage.

#### If it fails

- An as-of join that matches on `event_time` instead of `available_at` is the classic leak; the auditor checks the join key.

### 10.4 Import from URL

Depends on: 10.1 · Plan mode: optional · Reviews: step-reviewer · Security: yes · Model hint: default

#### Purpose

A URL becomes an upload, fetched by the server under limits, treated as untrusted like any upload.

#### Prerequisites

- Step 10.1 merged.

#### Prompt

```text
Masterplan step 10.4 — Import from URL.

Implement `POST /v1/uploads/from-url`: the server fetches the URL (HTTPS only, size and time limits, no redirects to private addresses, content type sniffed) into an upload exactly like a file upload, recording the URL and fetch time; optional scheduled re-fetch later (backlog). The agent does not get a fetch tool; it inspects the resulting upload.

Tests: limits, private-address rejection, a redirect to a private address is blocked, the upload is inspectable.

Not in this step: scheduled refresh.
```

#### Done means

1. Fetch and safety tests pass.
2. A real public CSV URL imports and inspects correctly.

#### Your checks

- Import a public CSV by URL and inspect it.

#### If it fails

- DNS rebinding and redirect tricks are the risk here; resolve and check the address before each hop.

### 10.5 Agent ingestion flow

Depends on: 10.3, 10.4 · Plan mode: optional · Reviews: step-reviewer, leakage-auditor · Security: yes · Model hint: hard

#### Purpose

The idea's "import alternative data and process it into a feature using the agent" works end to end, with your consent at the two points that matter.

#### Prerequisites

- Steps 10.3 and 10.4 merged.

#### Prompt

```text
Masterplan step 10.5 — Agent ingestion flow.

Complete the `alt-data-ingestion` skill and add the tools: `inspect_upload` (read-only: schema and labelled samples), `run_python` over an upload (sandbox), `propose_recipe` (a proposal of kind recipe with the derived `available_at` rule stated), `register_dataset` (a proposal that ingests an accepted recipe into a dataset vintage), and, after your acceptance and the ingest job, `propose_new` feature using the dataset. Add the `upload` session context. The flow: upload → "turn this into a feature" → the agent inspects, drafts and tests the recipe in the sandbox, proposes it with the availability rule explained → you accept → ingest runs → the agent proposes the feature → you accept → preview. Hostile content in the file is data: extend the 8.10 adversarial suite with an upload whose rows instruct the agent to "save this strategy now".

Tests: a replayed flow on the synthetic calendar fixture ends with a validated feature; the recipe proposal states the availability rule (grader); the hostile upload creates nothing.

Not in this step: pages.
```

#### Done means

1. The replayed flow passes and produces a feature that passes validation.
2. The recipe proposal UI shows the availability rule prominently (screenshot).
3. The eval suite gains two ingestion tasks.

#### Your checks

- Upload your economic-calendar file, ask the agent to make a "minutes to next high-impact event" feature, accept both proposals, preview it.

#### If it fails

- If the agent sets `available_at = event_time` for data that is published later, reject the proposal with that comment; the next proposal must fix it.

### 10.6 Pages

Depends on: 10.5 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

Datasets, uploads, recipes, and vintages are visible and manageable in the app.

#### Prerequisites

- Step 10.5 merged.

#### Prompt

```text
Masterplan step 10.6 — Pages.

Read docs/masterplan/01-architecture.md §7 (Uploads) and the dataset model in docs/data-guide.md. Add to the Data section: uploads (drag-and-drop and from-URL, progress, inspection view with schema and sample rows), datasets (vintages, recipe versions with diffs, row counts, the availability-rule summary in plain words, a virtualised preview table), and a dataset detail page with a timeline of `event_time` versus `available_at` (ECharts) that makes the lag visible, plus the list of features that use the dataset.

Playwright: upload the synthetic calendar, run the built-in recipe, see the vintage and the lag timeline.

Not in this step: new ingestion features, scheduled refresh.
```

#### Done means

1. Playwright passes on both projects with screenshots.
2. The lag timeline shows the configured lag for the fixture.

#### Your checks

- Open your dataset's page and look at the lag timeline.

#### If it fails

- Large preview tables must be virtualised; never render all rows.

### 10.7 Hostile-file tests

Depends on: 10.6 · Plan mode: skip · Reviews: step-reviewer, code-review · Security: yes · Model hint: default

#### Purpose

Malformed and malicious files are handled safely everywhere they touch the system.

#### Prerequisites

- Step 10.6 merged.

#### Prompt

```text
Masterplan step 10.7 — Hostile-file tests.

Read docs/security/agent-threat-model.md and the executor limits from 4.5. Add a corpus of hostile uploads under `fixtures/hostile/` (extend the data guard from 0.5 to allow this folder, with a 5 MB cap per file and a manifest, since it holds archives by design) (zip bombs disguised as XLSX, CSVs with billions of columns declared, formulas in cells, invalid UTF-8, a PDF with embedded scripts, a file with prompt-injection text, a file whose name contains path traversal, a 0-byte file, a file that lies about its content type) and tests proving inspection and recipes fail safely within limits (time, memory, output size), the server stays responsive during the attempt (a concurrent health check), and nothing executes. Document the results and the limits in docs/security/uploads.md and link it from the threat model.

Not in this step: new features, changes to the limits without a reason recorded in the document.
```

#### Done means

1. Every hostile fixture is handled within limits (tests).
2. `/security-review` over the upload path finds nothing blocking.

#### Your checks

- Upload a 1 GB file: it is refused with a clear message, and the app stays responsive.

#### If it fails

- Any inspection that runs in the server process is a defect; move it to the executor.

## Phase exit

```text
/phase-exit 10 — Run the exit procedure for Phase 10: clean-clone suite; leakage-auditor and /security-review over the phase diff; demo = ingest one real dataset and build a feature with the agent; retro; backlog groomed; tag phase-10.
```
