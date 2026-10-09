# ADR-0012: The in-app agent runs on the Messages API

Decision log: [D-14](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Pure Python runs on Windows and macOS with the customer's own API key, while the Agent SDK has no Windows wheel. Consent to an agent's action must be a product object, not a blocking callback.

## Decision

The in-app agent is built on the Messages API in Python. Its tools come from one registry, actions that need consent become proposals, and its skills are files.

## Consequences

The agent sits behind an `AgentRuntime` seam, and its transcript is append-only. It has no shell, file, or web tools.

## How we would know it is wrong

If the Agent SDK ran on Windows with the customer's own key, or if proposals could not capture the consent an action needs.

## Status

Accepted; recorded in step 0.7.
