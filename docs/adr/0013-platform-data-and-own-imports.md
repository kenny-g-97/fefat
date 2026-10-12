# ADR-0013: Platform data for a curated set of products, and imports of your own data

Decision log: [D-24](../masterplan/DECISIONS.md), 2026-10-08

## Context

The builder's requirement: ready-to-use data for the main products lowers the barrier to start, and imports cover every other product. [ADR-0001](0001-local-first-no-hosted-market-data.md) had ruled out shipping any market data.

## Decision

FEFAT provides market data for a curated set of products ("platform data"), and traders can also import their own market data for any product. Compute stays local.

## Consequences

- Every dataset carries `source: platform` or `source: user`.
- Phase 1 adds the platform catalog and the importer for the trader's own files; Phase 5 adds the import wizard.
- The commercial version needs a distribution licence for every platform product it delivers ([research appendix §3](../masterplan/appendix/research-market-data.md#3-licensing-for-a-product)).
- The commercial version delivers signed data packs from a hosted service (Phase 14). It is FEFAT's only hosted component, and it serves downloads only.
- A product without a distribution licence can still be offered as managed sync with the customer's own vendor account.
- Imported data never leaves the trader's machine.

## How we would know it is wrong

If platform data did not lower the barrier to start, because traders brought their own data anyway, or if imports could not cover the products traders need.

## Status

Accepted 2026-10-08; supersedes [ADR-0001](0001-local-first-no-hosted-market-data.md). Partly superseded by [ADR-0018](0018-own-data-sources-no-shipped-data.md) (D-37, 2026-10-12): FEFAT no longer provides platform data or delivers data to customers; the catalog, the imports, and the rule that imported data never leaves the trader's machine stand. Recorded in step 0.7.
