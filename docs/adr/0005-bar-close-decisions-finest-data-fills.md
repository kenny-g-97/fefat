# ADR-0005: Decisions at bar close, fills on the finest data inside the bar

Decision log: [D-07](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Backtests should be quick and highly accurate without tick-level strategy logic.

## Decision

Strategies decide at bar close. Fills are computed on the finest data inside the bar, with conservative defaults, and every fill is tagged with its fidelity.

## Consequences

A fill specification document and scenario tables define the fills. Reports split results by fill fidelity.

## How we would know it is wrong

If fills computed this way differed materially from fills on tick data for the strategies FEFAT targets, or if those strategies needed to react inside the bar.

## Status

Accepted; recorded in step 0.7.
