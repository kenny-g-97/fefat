# ADR-0002: A web UI over a desktop-ready local backend, packaged with Tauri last

Decision log: [D-03](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

FEFAT is used in the browser, on the phone, and in a desktop window. Packaging is the fiddliest part of the build, and it is best done once the app is stable.

## Decision

The user interface is a React web app over a local backend that is ready to run on the desktop. Tauri packages it as a desktop app last.

## Consequences

The same UI serves the browser, the phone, and the desktop window. The backend is one process with SQLite and files, without Docker, on a configurable port.

## How we would know it is wrong

If one UI could not serve the browser, the phone, and the desktop window well, or if packaging at the end forced changes to the backend that an earlier start would have avoided.

## Status

Accepted; recorded in step 0.7.
