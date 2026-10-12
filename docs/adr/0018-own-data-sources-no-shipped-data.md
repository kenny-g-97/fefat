# ADR-0018: Traders connect their own data sources, and FEFAT ships no market data

Decision log: [D-37](../masterplan/DECISIONS.md), 2026-10-12

## Context

[ADR-0013](0013-platform-data-and-own-imports.md) had FEFAT provide "platform data" for a curated set of products and, in the commercial version, deliver it as signed data packs from a hosted service. The licensing review at the Phase 0 exit (2026-10-11 and 12) priced that at about $127k a year for the CME products ([research appendix §3](../masterplan/appendix/research-market-data.md#3-licensing-for-a-product)). The alternative of hosted backtests, where customers receive only results and trade logs, still counts as redistribution of derived information under Databento's agreement (§1.1, §1.5(e)) and CME's managed non-display rules, and would move compute off the trader's machine, against D-01 and D-17. A desktop app that fetches data with the trader's own account, which ADR-0013 already named as the fallback, needs no licence from FEFAT.

## Decision

FEFAT ships no market data and never receives, stores, or serves it for anyone else. Traders connect their own data sources: vendor accounts and public archives through connectors, and files through import presets. FEFAT provides the product catalog (instrument specifications, calendars, roll rules, quality rules, and recommended sources), a guide to well-known sources with their costs and terms, the connectors and presets, and the sync that keeps a product current on the trader's machine.

## Consequences

- Every dataset records its `origin` (`sync` or `import`), its `provider`, and the licence scope the source's terms give the trader; "platform data" exists nowhere.
- One `Provider` interface is the seam for every connector, so adding a vendor is adding one provider. `PlatformDataSource`, data packs, entitlement tokens for data, and the hosted data service are gone.
- The commercial version runs the same data code as the personal one. Phase 14 ships the catalog and the source guide inside the app, proves that no data ships with it, and hosts a signed index of the catalog (never data) for updates.
- The vendors in the source guide are asked to confirm in writing that the app may use a customer's own account on the customer's machine; a source without that confirmation is shown as "check the terms yourself".
- Hosted compute and hosted market data for other users stay out of scope.

## How we would know it is wrong

If traders did not start because connecting a source was more friction than ready data, or if a vendor refused to let its customers use their own accounts through FEFAT and no other source covered the product.

## Status

Accepted; partly supersedes [ADR-0013](0013-platform-data-and-own-imports.md) (the delivery of platform data). Recorded at the plan revision of 2026-10-12 (D-37).
