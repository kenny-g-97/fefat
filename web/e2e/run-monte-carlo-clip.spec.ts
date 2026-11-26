import type { Locator, Page } from "@playwright/test"
import { expect, test } from "./support/fixtures.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The Monte Carlo card as a clip for the pull request (the UI recipe, steps 5.20 and 5.21): its
// figures, the pointer along the fan with the readout following it, the keys stepping it, then Max
// drawdown chosen in its select and the pointer along the percent of paths.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 700
const POINTER_STOPS = 12

/** Move the pointer across `chart` in `POINTER_STOPS` stops, then off it. */
async function sweep(page: Page, chart: Locator): Promise<void> {
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart drawn, got no box.")
  }
  for (let stop = 1; stop <= POINTER_STOPS; stop += 1) {
    const across = box.x + (box.width * stop) / (POINTER_STOPS + 1)
    await page.mouse.move(across, box.y + box.height * 0.5, { steps: 6 })
    await page.waitForTimeout(PAUSE_MS / 3)
  }
  await page.mouse.move(box.x + box.width / 2, box.y - 120)
  await page.waitForTimeout(PAUSE_MS)
}

test("the Monte Carlo card, recorded", async ({ loggedIn: page }) => {
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)
  const card = page.getByRole("region", { name: "Monte Carlo" })
  const chart = card.getByTestId("fan-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await card.evaluate((shown) => shown.scrollIntoView({ block: "start" }))
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS * 2)

  await sweep(page, chart)

  await chart.focus()
  for (const pressed of [
    "Home",
    "ArrowRight",
    "ArrowRight",
    "ArrowRight",
    "End",
    "Escape",
  ]) {
    await page.keyboard.press(pressed)
    await page.waitForTimeout(PAUSE_MS)
  }

  await card.getByRole("combobox", { name: "Chart", exact: true }).click()
  await page.waitForTimeout(PAUSE_MS)
  await page.getByRole("option", { name: "Max drawdown", exact: true }).click()
  const percentiles = card.getByTestId("percentile-chart")
  await expect(percentiles.locator("canvas").first()).toBeVisible()
  await page.waitForTimeout(PAUSE_MS)
  await sweep(page, percentiles)
})
