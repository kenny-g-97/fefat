# FEFAT web app

Vite, React, and TypeScript with Tailwind, shadcn/ui, TanStack Router and Query, and an `openapi-fetch` client over the types `just gen-api` generates, managed with pnpm from the repository root. Its design system is [DESIGN.md](DESIGN.md), which every change here builds from and extends.

```text
just dev        # fefat up, then the Vite dev server on http://localhost:5173 with its proxy, opening the app
just build-web  # build into web/dist, which fefat up serves at http://127.0.0.1:8765
just e2e        # build, then the Playwright specs of e2e/ against a seeded fefat up; screenshots in test-results/screenshots/
just check      # oxlint, oxfmt --check, tsc, and the areas' import boundary, with the rest of the repository
```

`src/` is laid out by product area (`docs/masterplan/08-code-design.md` §1.5): `app/` holds the router, its file routes, the login, and the shell; `areas/<area>/` the pages of one area, which import only `ui/`, `api/`, `charts/`, and `app/`, never another area; `ui/` the design system's primitives, the shadcn components among them; and `api/` the client, its CSRF header, and the query hooks. `src/app/routeTree.gen.ts` and `src/api/schema.d.ts` are generated, by the router's Vite plugin and by `just gen-api`, and committed.
