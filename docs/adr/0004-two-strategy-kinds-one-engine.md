# ADR-0004: Two strategy kinds on one engine, signal strategies first

Decision log: [D-06](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Signal strategies need no Python in the hot loop, so they run fast, and the strategy builder form can generate them. Event strategies cover path-dependent logic.

## Decision

One engine runs two kinds of strategy: signal strategies, built first, and event strategies, built later.

## Consequences

One `ExitPlan` in Rust serves both kinds. Parity tests check that the two kinds agree.

## How we would know it is wrong

If parity tests could not make the two kinds agree on a strategy both can express, or if most strategies traders write needed the path-dependent logic of event strategies.

## Status

Accepted; recorded in step 0.7.
