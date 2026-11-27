import { chartReady } from "./support/chart.ts"
import { expect, test } from "./support/fixtures.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The trade review chart as a clip for the pull request (the UI recipe, step 5.9): your check on
// the seeded run, three trades clicked in the table, each arrow on the candle of its time in the
// table and its entry's tooltip pinned, then Next and Previous, a fill's marker under the
// pointer, and Explain with the replay's timeline beside the chart. A window 960 px tall holds
// the chart and the table's first rows together, so that no click scrolls the page.

test.use({
  viewport: { width: 1280, height: 960 },
  video: { mode: "on", size: { width: 1280, height: 960 } },
})

const PAUSE_MS = 900

test("three trades reviewed on the chart, stepped through, and one explained, recorded", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.goto(`/runs/run/trades?key=${key}`)
  await expect(page.getByTestId("trade-row").first()).toBeVisible()
  await chartReady(page)
  // The chart and the table's first rows in one window, the trade line under the top bar.
  await page
    .getByTestId("trade-review")
    .evaluate((review) =>
      window.scrollTo(
        0,
        review.getBoundingClientRect().top + window.scrollY - 88
      )
    )
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS)

  const rows = page.getByTestId("trade-row")
  for (const index of [0, 2, 1]) {
    await rows.nth(index).click()
    await expect(page.getByTestId("entry-marker-tooltip")).toBeVisible()
    await page.waitForTimeout(PAUSE_MS * 2)
  }

  await page.getByTestId("next-trade").click()
  await page.waitForTimeout(PAUSE_MS * 1.5)
  await page.getByTestId("next-trade").click()
  await page.waitForTimeout(PAUSE_MS * 1.5)
  await page.getByTestId("previous-trade").click()
  await page.waitForTimeout(PAUSE_MS * 1.5)

  const chart = await page.getByTestId("price-chart").boundingBox()
  if (chart !== null) {
    await page.mouse.move(
      chart.x + chart.width * 0.3,
      chart.y + chart.height * 0.3,
      {
        steps: 12,
      }
    )
    await page.waitForTimeout(PAUSE_MS)
    await page.mouse.move(
      chart.x + chart.width * 0.7,
      chart.y + chart.height * 0.3,
      {
        steps: 24,
      }
    )
    await page.waitForTimeout(PAUSE_MS)
  }

  await page.getByTestId("explain-trade").click()
  const filled = page
    .getByTestId("explanation-panel")
    .locator('[data-testid="explained-event"][data-kind="filled"]')
  // The replay runs in a worker of the server's pool, as a job.
  await expect(filled.first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(PAUSE_MS * 2)
  await filled.last().scrollIntoViewIfNeeded()
  await page.waitForTimeout(PAUSE_MS * 2)
})
