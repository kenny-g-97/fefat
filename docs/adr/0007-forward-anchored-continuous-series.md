# ADR-0007: Forward-anchored continuous futures, execution on the actual contract

Decision log: [D-09](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Back-adjustment rewrites history at each roll. That invalidates caches and trips the leak detector.

## Decision

Continuous futures series are forward-anchored, and orders execute on the actual contract.

## Consequences

Series carry the columns `close`, `close_raw`, `adj_offset`, and `contract`. Back-adjusted series exist for display only.

## How we would know it is wrong

If a roll ever changed values already in a forward-anchored series, so that caches and the leak detector broke anyway.

## Status

Accepted; recorded in step 0.7. Amended by D-44 (step 1.7): the series also carry `roll_flag`, and the roll calendar that splices them records, at each roll, both contracts, the gap between their last closes before the session, and the session open at which a position is transferred; `docs/masterplan/02-engine-and-data.md` §1.5 has the rule.
