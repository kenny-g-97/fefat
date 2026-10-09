# ADR-0015: Every backtest stores each trade's compact price path

Decision log: [D-26](../masterplan/DECISIONS.md), 2026-10-08

## Context

Under [ADR-0014](0014-prop-simulation-from-backtest-files.md), a prop simulation reads saved runs and nothing is re-run later. Prop rules such as intraday trailing drawdowns and daily-loss limits need what happened inside each trade.

## Decision

Every backtest stores, alongside its fills, each trade's compact price path: the favourable and adverse extremes, with a mark and a restart at every minute boundary and at every fill. Every saved run is therefore ready for prop simulation.

## Consequences

- The engine records the paths during its in-position scan (step 2.13).
- A single run's target time rises from under 0.5 s to under 3 s.
- Compressed, the paths take a few MB for intraday runs, and more for runs with many multi-day holds.
- Sweep trials get paths only when they are saved as full runs.
- Runs saved before step 2.13 are not ready for prop simulation.

## How we would know it is wrong

If a prop rule needed something from inside a trade that the compact path does not keep, or if the paths pushed single runs past the 3 s target.

## Status

Accepted; recorded in step 0.7.
