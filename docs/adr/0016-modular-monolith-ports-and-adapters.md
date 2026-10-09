# ADR-0016: A modular monolith with ports and adapters

Decision log: [D-27](../masterplan/DECISIONS.md), 2026-10-09

## Context

The `designing-architecture` and `software-design-principles` skills were applied to the plan before any code existed. The seams of [01-architecture.md §10](../masterplan/01-architecture.md#10-seams-that-keep-options-open) were already ports in prose, and renames cost nothing before step 0.2.

## Decision

FEFAT is a modular monolith with ports and adapters:

- the SDK is the domain and application core;
- `fefat_app` is a ring of adapters around application services;
- the engine's market-data access is a trait in `fefat-core`;
- dependencies point inward, and `just check` enforces it;
- the names and design rules of [08-code-design.md §2](../masterplan/08-code-design.md#2-what-changed-in-the-layout-and-names) and [§3](../masterplan/08-code-design.md#3-design-rules-by-language) apply to all code.

The rule, its reasons, and how `just check` enforces it are in [08-code-design.md §1](../masterplan/08-code-design.md#1-the-architecture-decision).

## Consequences

- The layout and names are those of [01-architecture.md §3](../masterplan/01-architecture.md#3-repository-layout): `fefat.market`, `fefat.indicators`, `fefat.reference`, `fefat_app.http`, `services/`, `ports.py`, `container.py`, `database/`, `executor.py`, `credentials.py`, and the web app's `areas/`.
- The Python packages use the src layout.
- `import-linter`, and an import-boundary lint for the web app, are development dependencies.
- The rules files of step 0.4 carry the rules.

## How we would know it is wrong

If changes routinely had to break the dependency rule to work, or if swapping an adapter behind its port needed changes in the core.

## Status

Accepted; recorded in step 0.7.
