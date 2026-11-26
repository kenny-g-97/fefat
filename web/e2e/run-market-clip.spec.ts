import { expect, test } from "./support/fixtures.ts"
import { countedAnswer, withExposure } from "./support/market-answers.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// A run's market exposure as a clip for the pull request (the UI recipe, step 5.23): your check,
// from the card's correlation and beta to buy and hold's cyan line at the end of the equity chart,
// on the seeded run with the counted answer the specs give it (`countedAnswer`).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 700

test("a run's market exposure beside buy and hold, recorded", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await withExposure(page, key, await countedAnswer(page, key))

  await page.goto(`/runs/run?key=${key}`)
  const figures = page.getByTestId("market-figures")
  await expect(figures).toBeVisible()
  // A clip shows each part for a moment; nothing here waits on the app.
  await figures.scrollIntoViewIfNeeded()
  await page.waitForTimeout(PAUSE_MS * 2)
  for (const stat of ["correlation", "beta", "alpha", "explained"]) {
    await page.getByTestId(`market-${stat}`).hover()
    await page.waitForTimeout(PAUSE_MS)
  }
  for (const row of ["net-pnl", "max-drawdown", "sharpe"]) {
    const figure = page.getByTestId(`buy-and-hold-${row}`)
    await figure.scrollIntoViewIfNeeded()
    await figure.hover()
    await page.waitForTimeout(PAUSE_MS)
  }

  const chart = page.getByTestId("equity-chart")
  await chart.scrollIntoViewIfNeeded()
  await expect(chart.locator("canvas").first()).toBeVisible()
  await page.getByTestId("equity-legend-buy-and-hold").hover()
  await page.waitForTimeout(PAUSE_MS * 2)
  await chart.focus()
  await page.keyboard.press("Home")
  await page.waitForTimeout(PAUSE_MS)
  await page.keyboard.press("End")
  await page.waitForTimeout(PAUSE_MS * 2)
  for (let step = 0; step < 4; step += 1) {
    await page.keyboard.press("ArrowLeft")
    await page.waitForTimeout(PAUSE_MS / 2)
  }
  await page.keyboard.press("Escape")
  await page.waitForTimeout(PAUSE_MS * 2)
})
