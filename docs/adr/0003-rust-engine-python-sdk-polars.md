# ADR-0003: A Rust engine core, a Python SDK, and Polars for user code

Decision log: [D-05](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

The per-tick work of a backtest has to be fast, and the builder works in Python. Polars gives speed and a safer expression API for the code users write.

## Decision

The engine core is written in Rust and the SDK in Python, and user code works with Polars.

## Consequences

The engine reaches Python through PyO3 and ships as maturin wheels. Data crosses between Rust and Python through Arrow without copies.

## How we would know it is wrong

If the per-tick work ran fast enough in Python alone, or if a PyO3 wheel could not be built for a platform FEFAT must run on.

## Status

Accepted; recorded in step 0.7.
