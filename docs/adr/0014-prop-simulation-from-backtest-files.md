# ADR-0014: A prop simulation replays an existing backtest file and never re-runs the strategy

Decision log: [D-25](../masterplan/DECISIONS.md), 2026-10-08

## Context

The builder's requirement: prop analysis is a separate step on saved results, without re-running the strategy.

## Decision

A prop simulation takes three inputs: prop rules, a prop strategy, and an existing backtest file with the full trade log. It never re-runs the trading strategy.

The plan added one thing the builder did not ask for: the same replay accepts trade logs imported from other platforms (step 7.5).

## Consequences

- The engine has no prop account inside it.
- Results state the fidelity of the price paths they replay.
- Where a strategy would have reacted to the account's state, for example by re-entering after a forced cut, the simulation approximates the reaction and flags it.

## How we would know it is wrong

If the flagged approximations changed prop outcomes so often that traders could not trust a result without re-running the strategy.

## Status

Accepted; supersedes the exact mode of [ADR-0011](0011-prop-rules-as-versioned-data.md). Recorded in step 0.7.
