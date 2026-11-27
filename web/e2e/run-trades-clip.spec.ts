import { expect, test } from "./support/fixtures.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// A run's trade table as a clip for the pull request (the UI recipe, step 5.8): your check on the
// seeded run, from the run's page to its losing trades that a stop closed, sorted by MAE, the
// worst first, then a trade selected and the next reached by the keys, the column chooser, and
// a query in the SQL tab.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 700

test("a run's trades filtered, sorted, selected, and queried, recorded", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS)
  await page.getByTestId("trades").click()
  await expect(page.getByTestId("trade-row").first()).toBeVisible()
  await page.waitForTimeout(PAUSE_MS * 2)

  await page.getByRole("combobox", { name: "P&L" }).click()
  await page.waitForTimeout(PAUSE_MS / 2)
  await page.getByRole("option", { name: "Losing" }).click()
  await page.waitForTimeout(PAUSE_MS)
  await page.getByRole("combobox", { name: "Exit reason" }).click()
  await page.waitForTimeout(PAUSE_MS / 2)
  await page.getByRole("option", { name: "Stop" }).click()
  await page.waitForTimeout(PAUSE_MS)
  await page.getByTestId("sort-mae_ticks").click()
  await expect(page).toHaveURL(/order=desc/)
  await page.waitForTimeout(PAUSE_MS * 2)

  await page.getByTestId("trade-row").first().click()
  await page.waitForTimeout(PAUSE_MS)
  for (let step = 0; step < 3; step += 1) {
    await page.keyboard.press("ArrowDown")
    await page.waitForTimeout(PAUSE_MS / 2)
  }
  await page.waitForTimeout(PAUSE_MS)

  await page.getByTestId("column-chooser").click()
  await page.waitForTimeout(PAUSE_MS)
  await page.getByRole("menuitemcheckbox", { name: "Path fidelity" }).click()
  await page.waitForTimeout(PAUSE_MS)
  await page.keyboard.press("Escape")
  await page.waitForTimeout(PAUSE_MS)

  await page.getByTestId("tab-sql").click()
  await page
    .getByTestId("run-sql")
    .fill(
      "SELECT exit_reason, count(*) AS trades, sum(pnl) AS pnl FROM trades GROUP BY exit_reason"
    )
  await page.waitForTimeout(PAUSE_MS)
  await page.getByRole("button", { name: "Run query" }).click()
  await expect(page.getByTestId("run-sql-row").first()).toBeVisible()
  await page.waitForTimeout(PAUSE_MS * 3)
})
