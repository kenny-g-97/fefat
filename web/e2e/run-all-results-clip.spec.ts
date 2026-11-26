import { expect, test } from "./support/fixtures.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// A run's results in full as a clip for the pull request (the UI recipe, step 5.22): your check,
// from the run page's All results to the table of all, long, and short trades, and back to the run.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 700

test("a run's results in full, recorded", async ({ loggedIn: page }) => {
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)
  await expect(page.getByTestId("key-figures")).toBeVisible()
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS * 2)
  const allResults = page.getByTestId("all-results")
  await allResults.hover()
  await page.waitForTimeout(PAUSE_MS)
  await allResults.click()

  const table = page.getByTestId("results-by-side")
  await expect(table).toBeVisible()
  await page.waitForTimeout(PAUSE_MS * 2)
  for (const row of ["net-pnl", "fees", "slippage", "max-drawdown"]) {
    const figure = page.getByTestId(`by-side-${row}`)
    await figure.scrollIntoViewIfNeeded()
    await figure.hover()
    await page.waitForTimeout(PAUSE_MS)
  }
  await page.getByTestId("results-by-side-note").scrollIntoViewIfNeeded()
  await page.waitForTimeout(PAUSE_MS * 2)

  await page.getByRole("link", { name: "Back to the run" }).click()
  await expect(page.getByTestId("key-figures")).toBeVisible()
  await page.waitForTimeout(PAUSE_MS)
})
