# UI recipe

Step 4.3 activates this recipe when it adds the Playwright harness and the `ui-verifier` subagent; until then it records what every UI step will have to show (`docs/masterplan/05-build-process.md` §4, `08-code-design.md` §5).

For every page the step adds or changes:

1. Start the app with `just dev`, or the seeded server of `just e2e`.
2. With Playwright, open the page at desktop size (1280 × 800) and at phone size (390 × 844), and save a screenshot of each.
3. At 390 px: no horizontal scroll (`document.documentElement.scrollWidth <= window.innerWidth`), every control reachable, touch targets of at least 44 px.
4. Keyboard focus is visible on every interactive element when tabbing through the page, and reduced motion (`prefers-reduced-motion: reduce`) is respected.
5. Every number on the page equals the SDK or API value for the same run (the contract tests check this automatically from step 5.7).
6. When the step's "Your checks" describe a click path, record a short clip of it.

Attach the screenshots and the clip to the pull request under "Screenshots or recordings (UI)", with the click path for the builder's checks.
