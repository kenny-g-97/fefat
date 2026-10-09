# ADR-0006: The engine clock is Databento's ts_recv

Decision log: [D-08](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Databento buckets its bars on `ts_recv`, and the tick era and the bar era of the data must share one clock.

## Decision

The engine's clock is Databento's `ts_recv` timestamp.

## Consequences

Ingest asserts that records are ordered on it. The comparison with NautilusTrader uses the same convention.

## How we would know it is wrong

If Databento stopped bucketing its bars on `ts_recv`, or if tick and bar data on this clock disagreed where the two eras meet.

## Status

Accepted; recorded in step 0.7.
