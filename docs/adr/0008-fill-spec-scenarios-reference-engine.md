# ADR-0008: The fill specification, scenario tables, and a Python reference engine are the truth

Decision log: [D-10](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

The builder will not review Rust. Correctness must therefore come from tests the builder can read.

## Decision

The reviewable truth about fills is a plain-language fill specification, scenario tables, and a slow Python reference engine. The Rust engine must match the reference exactly.

## Consequences

Differential tests with Hypothesis compare the two engines. `run.explain` replays a run through the reference engine.

## How we would know it is wrong

If a fill error reached a saved run although the scenario tables and the differential tests passed, or if the specification and the tables grew beyond what the builder can read.

## Status

Accepted; recorded in step 0.7.
