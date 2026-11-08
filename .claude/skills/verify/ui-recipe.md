# UI recipe

Every step that changes `web/` shows its screens through the Playwright harness of step 4.3 (`docs/masterplan/05-build-process.md` §4, `08-code-design.md` §5). The harness verifies at desktop size only; the phone pass is the backlog's phone item (D-54).

For every page the step adds or changes:

1. A spec under `web/e2e/` opens the page at desktop size (1280 × 800) and saves a screenshot with `screenshot(page, name)` from `web/e2e/support/`, in the dark theme and, where the step changes colour, in the light one; a screenshot that would show a local path or a token masks it.
2. The page joins the list of the quality-floor spec, which checks that nothing scrolls sideways at 1280 px, that keyboard focus is visible, that reduced motion (`prefers-reduced-motion: reduce`) stops the transitions, and that the console stays free of errors, a refused content security policy among them.
3. `just e2e` passes: it builds the web app, starts `fefat up` on a seeded temporary home, and runs every spec, the login a second time through the Vite dev server's proxy. The screenshots land in `web/test-results/screenshots/`.
4. Every number on the page equals the SDK or API value for the same run (the contract tests check this automatically from step 5.7).
5. When the step's "Your checks" describe a click path, record a short clip of it.
6. The `ui-verifier` subagent runs the harness and reports per criterion, then the `design-reviewer` reviews the diff with the screenshots.

Copy the screenshots to `docs/validation/screenshots/<step>/` and link them in the pull request under "Screenshots or recordings (UI)", with the click path for the builder's checks.
