# ADR-0023: Deleting an instrument's stored data

Decision log: [D-107](../masterplan/DECISIONS.md), 2026-11-19

## Context

Nothing in FEFAT removed stored data: an import adds records or merges them into the partitions they overlap (ADR-0021), the raw manifest keeps each original file, which never changes (ADR-0019), and a file is imported once, as its first import read it (D-50). A trader who imported a file under the wrong settings, or no longer wants a product, had no way back but to delete folders by hand, which leaves the raw manifest naming files that are gone, so that their import again does nothing.

A merge leaves one file's records inseparable from another's in the shared partitions, and the raw manifest records which roots each file fed, not which records. So the unit that can be removed cleanly is a provider's data of a root, a row of the Data page's list, the pair a quality report covers.

## Decision

- **What a delete takes.** One provider's data of one root, whole: every dataset of the pair, of every schema; FEFAT's copies under `raw` of the files they were imported from, with their entries in the raw manifest, so that those files import again as new under any arguments; the pair's quality report; and its engine cache. Saved runs, the instrument's saved specification under `instruments`, other providers' data of the root, and the trader's own files stay.
- **Which raw files go**, decided entry by entry, never by folder: an entry of the pair's provider that names the root goes where no other root it names is still stored from that provider; an entry that names no root, a batch's side file, goes once no entry of the provider that names a root is left in its folder. Only recorded paths are removed, and a folder only once empty. A raw file that also feeds another root still stored is kept and named, and goes with the last of its roots.
- **Planned, then done.** `planned_deletion` says what a delete removes and writes nothing; `delete_stored_data` refuses a pair the store does not list before it holds or writes anything, takes the store's import lock, waiting a few seconds at most, plans once it holds it, and removes. The datasets are those the store lists for the pair, never a path built from the text that names it.
- **The order of removal**, each act passing over what is already gone, a file that another program removed during the delete among it: the quality report, under its own lock, whose file stays; the engine cache; the raw copies of the entries that name the root, then their batches' side files, the vendor's conditions last; the raw manifest, rewritten in one step without them; the raw folders left empty; the records of the kinds the Data page does not list the pair by, then those of trades, TBBO, and bars; then each `dataset.json`, and the folders left empty. A report never vouches for data half deleted; every entry stays until its file is gone, so that a delete stopped part way finds it again, and the conditions, which the quality reports read through the manifest, keep their file while recorded, but for a crash in the instant between their removal and the manifest's rewrite, which the next delete finishes; no entry says a file is imported once its records are gone; and the row stays on the Data page while a record of it remains. A file another program holds open refuses the delete with its path, and asking again finishes it.
- **Saved runs.** A run's record and results stand (ADR-0009). A delete's plan counts the saved runs that read the pair, and a run whose dataset is gone refuses to be explained or checked again in words that say its data was deleted.
- **Where it is asked.** `fefat data delete <provider> <root>` prints the plan and deletes only with `--yes`; the server answers the plan and deletes, refusing while any job is queued or running and holding every new job back until the delete ends; the instrument's page ends in a card that says what goes, with Delete, then Delete now and Keep, and leads to the Data page, which says what was deleted.

## Consequences

- A file imported under the wrong settings is put right by deleting its instrument's data from its provider and importing its files again, all of them, since the others' records go too.
- A Databento batch that fed several roots stays in `raw` until the last of them is deleted, and until then importing it again is a file imported before, which writes nothing: the deleted root comes back only from another file (`BACKLOG.md`).
- A run read again after a delete is refused, as after a merge; running its strategy again on data imported anew gives a new run.
- The import lock keeps a delete and an import's writes apart, and the server holds its jobs back while it deletes; a reader takes no lock, so a notebook reading the pair meanwhile may meet a missing file. The command line does not see the app's jobs: let them end before deleting from a terminal. A quality report written from a terminal in the same moment as a delete can be left behind with no data, and is replaced by the next report of the pair (`BACKLOG.md`).
- A delete stopped part way can leave entries whose copies are gone until it is asked again, and once its last trades, TBBO, and bars are gone the Data page no longer lists the row, while a `dataset.json` may remain: `fefat data delete` then finishes it.
- The features' cache keeps its entries, keyed by the snapshots they read, which a read of data imported anew matches only where its files are the same bytes; `fefat cache features --prune` removes those no read used for a while.
- The code is `fefat.market.stored_deletion`, `fefat.backtest.saved_runs` and `pinned_data`, `fefat data delete`, the catalog's service and routes, and the dataset's page.

## How we would know it is wrong

If a delete removed a file of another provider or root, or left, once finished, a manifest entry whose file is gone or a file of the pair; if a file of a deleted pair could not be imported again; if an interrupted delete could not be finished by asking again; or if traders often needed to remove one file's records, or one root of a shared batch, without the rest.

## Status

Accepted; recorded at the plan of step 5.18. It refines [ADR-0019](0019-canonical-market-data-store.md), whose raw files never change until their instrument's data is deleted, and leaves [ADR-0009](0009-deterministic-pinned-hashed-runs.md) and [ADR-0021](0021-imports-merge-into-the-partitions-they-overlap.md) as they are.
