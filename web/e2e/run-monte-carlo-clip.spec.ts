import { expect, test } from "./support/fixtures.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The Monte Carlo card as a clip for the pull request (the UI recipe, step 5.20): its figures, the
// pointer along the fan with the readout following it, and the keys stepping it.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAUSE_MS = 700
const POINTER_STOPS = 12

test("the Monte Carlo card, recorded", async ({ loggedIn: page }) => {
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)
  const card = page.getByRole("region", { name: "Monte Carlo" })
  const chart = card.getByTestId("fan-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await card.evaluate((shown) => shown.scrollIntoView({ block: "start" }))
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS * 2)

  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the fan drawn, got no box.")
  }
  for (let stop = 1; stop <= POINTER_STOPS; stop += 1) {
    const across = box.x + (box.width * stop) / (POINTER_STOPS + 1)
    await page.mouse.move(across, box.y + box.height * 0.5, { steps: 6 })
    await page.waitForTimeout(PAUSE_MS / 3)
  }
  await page.mouse.move(box.x + box.width / 2, box.y - 120)
  await page.waitForTimeout(PAUSE_MS)

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
})
