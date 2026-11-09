import { expect, test } from "@playwright/test"
import { cancelActiveJobs, progressOf } from "./support/jobs.ts"
import { E2E_PASSWORD } from "./support/password.ts"

// The builders' checks of steps 4.3 and 4.4 as a clip for the pull request (the UI recipe): log
// in, open each page of the sidebar, switch to the light theme and back, then start the demo
// job, watch it in the jobs drawer, reload, and cancel it. The settings page's local path must
// stay below the fold of 800 px, out of the clip, since a video cannot be masked (D-80).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAGES = ["Lab", "Strategies", "Runs", "Prop", "Agent", "Data", "Settings"]
const PAUSE_MS = 500

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("the builder's click path, recorded", async ({ page }) => {
  await page.goto("/")
  await page.getByLabel("Password").fill(E2E_PASSWORD)
  await page.waitForTimeout(PAUSE_MS)
  await page.getByRole("button", { name: "Log in" }).click()
  const sidebar = page.getByRole("navigation", { name: "Main" })

  for (const name of PAGES) {
    await sidebar.getByRole("link", { name, exact: true }).click()
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible()
    // A clip shows each page for a moment; nothing here waits on the app.
    await page.waitForTimeout(PAUSE_MS)
  }
  for (const theme of ["Light", "Dark"]) {
    await page.getByRole("radio", { name: theme }).click()
    await expect(page.getByRole("radio", { name: theme })).toBeChecked()
    await page.waitForTimeout(PAUSE_MS)
  }

  const indicator = page.getByTestId("jobs-indicator")
  const drawer = page.getByRole("dialog", { name: "Jobs" })
  const row = drawer.getByTestId("job-row").first()
  await page.getByRole("button", { name: "Run demo job" }).click()
  await indicator.click()
  await expect
    .poll(() => progressOf(row.getByRole("progressbar")), { timeout: 30_000 })
    .toBeGreaterThan(0)
  await page.waitForTimeout(PAUSE_MS * 4)
  await page.reload()
  await indicator.click()
  await expect(row.getByRole("progressbar")).toBeVisible()
  await page.waitForTimeout(PAUSE_MS * 4)
  await row.getByTestId("job-cancel").click()
  await expect(row).toContainText("Cancelled", { timeout: 15_000 })
  await page.waitForTimeout(PAUSE_MS * 2)
  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()
  await expect(page.getByTestId("data-folder")).not.toBeInViewport()
})
