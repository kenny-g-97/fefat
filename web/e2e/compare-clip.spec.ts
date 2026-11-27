import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"

// The comparison, the version diff, and Reproduce as a clip for the pull request (the UI recipe,
// step 5.10): your check on the seed's two runs of demo, version 1 and version 2's wider stop,
// ticked on the Runs page and compared, the pointer over their equity, then the stop's change on
// the strategy page, then the first run reproduced, its trades matching.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 900
const REPRODUCTION_TIMEOUT = 90_000

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("two runs compared, their versions diffed, and one reproduced, recorded", async ({
  loggedIn: page,
}) => {
  await page.goto("/runs")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Runs")
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS)
  await page
    .getByRole("checkbox", { name: /^Compare demo version 1, / })
    .click()
  await page.waitForTimeout(PAUSE_MS / 2)
  await page
    .getByRole("checkbox", { name: /^Compare demo version 2, / })
    .click()
  await page.waitForTimeout(PAUSE_MS)
  await page.getByTestId("runs-compare").click()

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Comparison")
  const chart = page.getByTestId("comparison-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await page.waitForTimeout(PAUSE_MS)
  const box = await chart.boundingBox()
  if (box !== null) {
    await page.mouse.move(box.x + box.width * 0.1, box.y + box.height * 0.5)
    await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.5, {
      steps: 24,
    })
    await page.waitForTimeout(PAUSE_MS)
  }
  await page.mouse.move(700, 36)
  await page.getByTestId("compared-pnl").scrollIntoViewIfNeeded()
  await page.waitForTimeout(PAUSE_MS * 2)

  await page.goto("/strategies/strategy?name=demo")
  const changes = page.getByRole("region", { name: "Changes" })
  await expect(changes.locator(".cm-merge-b .cm-changedText")).toHaveText([
    "2.0",
  ])
  await changes.scrollIntoViewIfNeeded()
  await page.waitForTimeout(PAUSE_MS * 2.5)

  await page.goto("/runs")
  await page
    .getByTestId("run-row")
    .filter({ hasText: "stop_atr 1.5" })
    .first()
    .click()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")
  await page.waitForTimeout(PAUSE_MS)
  await page.getByTestId("reproduce-run").click()
  await expect(page.getByTestId("reproduction")).toContainText(
    "Reproduced: the trades match the saved run's",
    { timeout: REPRODUCTION_TIMEOUT }
  )
  await page.waitForTimeout(PAUSE_MS * 2)
})
