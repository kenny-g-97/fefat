# ADR-0017: One design system for every screen

Decision log: [D-28](../masterplan/DECISIONS.md), 2026-10-09

## Context

Without a deliberate design pass, each UI step produces the generic defaults that the `frontend-design` skill lists. A research terminal used for hours a day deserves a considered design.

## Decision

Every screen is built with the `frontend-design` skill from one design system, `web/DESIGN.md`. Step 4.3 creates it from a design brief collected at the Phase 4 kickoff.

## Consequences

- The Phase 4 kickoff asks the builder for the brief.
- Step 4.3 writes the tokens and themes shadcn/ui and the charts from them.
- Later UI steps load the skill and extend `web/DESIGN.md`.
- The exits of phases with UI run `design-critique` and `accessibility-review`.

## How we would know it is wrong

If the design critiques at phase exits still found generic defaults on screens built from the design system, or if UI steps worked around `web/DESIGN.md` instead of extending it.

## Status

Accepted; recorded in step 0.7.
