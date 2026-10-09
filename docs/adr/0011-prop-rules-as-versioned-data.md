# ADR-0011: Prop rules as versioned data, with an exact mode and a fast replay

Decision log: [D-13](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Prop firms change their rules often. A fast replay makes Monte Carlo at scale possible.

## Decision

Prop rules are versioned data, each with its sources and worked examples. The simulator has an exact mode and a fast replay, and the two must agree.

## Consequences

Presets are files with as-of dates and carry a `replayable` flag. Equivalence tests check that the exact mode and the fast replay agree.

## How we would know it is wrong

If a firm's rule could not be written as data, or if the exact mode and the fast replay disagreed.

## Status

Accepted 2026-10-05/06 (planning). Partly superseded: the exact mode, and with it the equivalence tests between the exact mode and the fast replay, is superseded by [ADR-0014](0014-prop-simulation-from-backtest-files.md) (D-25, 2026-10-08), under which a prop simulation replays an existing backtest file and never re-runs the strategy. Rules as versioned data and the fast replay stand. Recorded in step 0.7.
