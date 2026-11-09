import { lowContrast, lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs, progressOf } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The jobs of step 4.4 against `fefat up`'s pool: the settings page starts a demo job, the
// home page's card and the top bar's drawer show its progress live, a reload keeps it, and
// Cancel stops it (Done means 3, and the builder's check); a refused start and a list that
// cannot be read say why, the card failing on its own. A worker of the pool starts a second or
// more after the first job, so the first wait is long. Each test cancels what it started.

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("a demo job's progress shows live, survives a reload, and stops on Cancel", async ({
  loggedIn: page,
}) => {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  page.on("pageerror", (error) => errors.push(error.message))
  await page.emulateMedia({ reducedMotion: "reduce" })
  const indicator = page.getByTestId("jobs-indicator")
  const drawer = page.getByRole("dialog", { name: "Jobs" })
  const row = drawer.getByTestId("job-row").first()

  await page.goto("/settings")
  await page.getByRole("button", { name: "Run demo job" }).click()
  await expect(page.getByRole("status")).toHaveText("Demo job started")
  await expect(indicator).toHaveAccessibleName("Jobs, 1 running")

  await page.goto("/")
  const card = page.getByRole("region", { name: "Running jobs" })
  await expect
    .poll(() => progressOf(card.getByRole("progressbar")), { timeout: 30_000 })
    .toBeGreaterThan(0)
  await expect(card.getByTestId("running-job")).toContainText("Demo job")
  await screenshot(page, "home-running-job")

  await indicator.click()
  await expect(drawer).toBeVisible()
  await expect(row).toContainText("Demo job")
  await expect(row).toContainText("Running")
  const before = await progressOf(row.getByRole("progressbar"))
  expect(before).toBeGreaterThan(0)
  await screenshot(page, "jobs-drawer-running")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await screenshot(page, "jobs-drawer-running-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // The builder's check: the bar continues from where it was after a reload.
  await page.reload()
  await expect(
    page.getByRole("heading", { level: 1, name: "Home" })
  ).toBeVisible()
  await indicator.click()
  expect(await progressOf(row.getByRole("progressbar"))).toBeGreaterThanOrEqual(
    before
  )
  await expect
    .poll(() => progressOf(row.getByRole("progressbar")), { timeout: 10_000 })
    .toBeGreaterThan(before)

  await row.getByTestId("job-cancel").click()
  await expect(row).toContainText("Cancelled", { timeout: 15_000 })
  await expect(row.getByRole("progressbar")).toHaveCount(0)
  await expect(indicator).toHaveAccessibleName("Jobs")
  await expect(card.getByText("No jobs running.")).toBeVisible()
  await screenshot(page, "jobs-drawer-cancelled")

  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()
  await expect(indicator).toBeFocused()
  expect(await lowContrast(page, "focus ring")).toEqual([])
  expect(errors).toEqual([])
})

test("a demo job the server refuses says why", async ({ loggedIn: page }) => {
  await page.route("**/v1/jobs/demo", (route) =>
    route.fulfill(
      problemAnswer(500, "The server failed on purpose, for this test.")
    )
  )
  await page.goto("/settings")

  await page.getByRole("button", { name: "Run demo job" }).click()

  await expect(page.getByRole("alert")).toHaveText(
    "The server failed on purpose, for this test."
  )
})

test("the running-jobs card fails on its own and tries again", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/jobs", (route) =>
    route.fulfill(
      problemAnswer(500, "The jobs could not be read, for this test.")
    )
  )
  await page.goto("/")
  const card = page.getByRole("region", { name: "Running jobs" })

  await expect(card.getByRole("alert")).toHaveText(
    "The jobs could not be read, for this test."
  )
  await expect(
    page.getByRole("heading", { level: 1, name: "Home" })
  ).toBeVisible()
  await expect(page.getByRole("region", { name: "Recent runs" })).toBeVisible()

  await page.unroute("**/v1/jobs")
  await card.getByRole("button", { name: "Try again" }).click()

  await expect(card).toContainText("No jobs running.")
})
