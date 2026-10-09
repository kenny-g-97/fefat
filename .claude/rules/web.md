---
paths:
  - "web/**"
---

# Web rules (TypeScript, React)

From `docs/masterplan/08-code-design.md` §1.5, §3.1, §3.4, and §5, and `docs/masterplan/01-architecture.md` §3 and §8.

- **Design system.** Load the `frontend-design:frontend-design` skill and read `web/DESIGN.md` before building UI (the file arrives in step 4.3). Build from its tokens, and add every new pattern to it so the app stays one design system.
- **Types from the API.** API types are generated from `web/openapi.json` with `openapi-typescript`, never written by hand. zod schemas cover everything the API does not type: URL search parameters, local storage, SSE payloads, imported files.
- **Numbers come from the API.** The client never recomputes a number the API returns; contract tests compare UI numbers with SDK numbers.
- **Strict TypeScript.** No `any`, no `as` assertions, no `@ts-ignore` or `@ts-expect-error` without a one-line reason and the reviewer's approval.
- **Shapes.** Discriminated unions for view state; `readonly` props; components under about 150 lines; hooks named after what they load or do.
- **Layout by product area.** `src/app/` (shell, router, providers), `src/areas/<area>/`, `src/ui/`, `src/charts/`, `src/api/`. An area imports only `ui/`, `api/`, `charts/`, and `app/`, never another area.
- **Phone first.** Every page works at 390 px wide without horizontal scroll; keyboard focus is visible; reduced motion is respected; contrast passes.
- **Testability.** Stable `data-testid`s on everything a test or the `ui-verifier` touches.
- **No remote assets.** No remote images or fonts at runtime (the CSP allows `img-src 'self' data: blob:` only).
- **Copy.** Plain verbs, sentence case, the same name for an action from button to toast, errors that say what happened and what to do.
- **Tooling.** pnpm only (`pnpm --dir web …`). `just check` runs oxlint and `tsc`, `just test` runs vitest.
