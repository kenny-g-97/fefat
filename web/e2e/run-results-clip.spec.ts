import { z } from "zod"
import { expect, test } from "./support/fixtures.ts"

// A finished run's page as a clip for the pull request (the UI recipe, step 5.7): its figures, the
// pointer along the equity curve with the readout following it, and the keys stepping it.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const listed = z.object({ runs: z.array(z.object({ run_key: z.string() })) })
const PAUSE_MS = 700
const POINTER_STOPS = 12

test("a finished run's results, recorded", async ({ loggedIn: page }) => {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const seeded = listed.parse(await answer.json()).runs.at(-1)
  if (seeded === undefined) {
    throw new Error("Expected the seed's saved run of demo, got none.")
  }

  await page.goto(`/runs/run?key=${seeded.run_key}`)
  await expect(page.getByTestId("key-figures")).toBeVisible()
  // A clip shows each part for a moment; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS * 2)

  const chart = page.getByTestId("equity-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await page.getByTestId("equity-figure").scrollIntoViewIfNeeded()
  await page.evaluate(() => window.scrollBy(0, 240))
  await page.waitForTimeout(PAUSE_MS)
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart drawn, got no box.")
  }
  for (let stop = 1; stop <= POINTER_STOPS; stop += 1) {
    const across = box.x + (box.width * stop) / (POINTER_STOPS + 1)
    await page.mouse.move(across, box.y + box.height * 0.3, { steps: 6 })
    await page.waitForTimeout(PAUSE_MS / 3)
  }
  await page.mouse.move(box.x + box.width / 2, box.y - 120)
  await page.waitForTimeout(PAUSE_MS)

  await chart.focus()
  for (const key of ["Home", "ArrowRight", "ArrowRight", "End", "Escape"]) {
    await page.keyboard.press(key)
    await page.waitForTimeout(PAUSE_MS)
  }
})
