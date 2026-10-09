# ADR-0009: Deterministic, pinned, hashed runs and immutable versions

Decision log: [D-11](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Strategies and backtests need reproducibility and version control.

## Decision

Runs are deterministic, their inputs are pinned, and each run is hashed. Versions are immutable.

## Consequences

The run hash detects duplicate submissions. Goldens change only with the builder's approval.

## How we would know it is wrong

If the same pinned inputs ever produced two different results or two different hashes.

## Status

Accepted; recorded in step 0.7.
