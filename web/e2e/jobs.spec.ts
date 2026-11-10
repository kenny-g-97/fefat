import type { Request } from "@playwright/test"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs, progressOf, startDemoJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The jobs of step 4.4 against `fefat up`'s pool: the settings page starts a demo job, the
// home page's card and the top bar's drawer show its progress live, a reload keeps it, and
// Cancel stops it (Done means 3, and the builder's check), in the look web/DESIGN.md gives the
// top bar, its buttons, the bar, and Cancel; the drawer shows every status, the active jobs
// first, an empty list, and its own failure; a refused start and a list that cannot be read say
// why, the card failing on its own. A worker of the pool starts a second or more after the
// first job, so the first wait is long. Each test cancels what it started.

const STARTED = "2026-11-09T10:00:00Z"
const ENDED = "2026-11-09T10:01:00Z"

function aJob(
  id: string,
  status: string,
  changes: Readonly<Record<string, unknown>> = {}
) {
  return {
    id,
    kind: "demo",
    payload: { seconds: 60 },
    status,
    progress: 0,
    message: null,
    attempt: 1,
    max_attempts: 3,
    worker_pid: null,
    lease_expires_at: null,
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: STARTED,
    started_at: null,
    finished_at: null,
    ...changes,
  }
}

/** One job of each status, newest first as the server lists them, the ended among the active. */
const EVERY_STATUS = [
  aJob("succeeded", "succeeded", {
    progress: 100,
    message: "Counted 60 of 60",
    finished_at: ENDED,
  }),
  aJob("running", "running", { progress: 40, message: "Counted 24 of 60" }),
  aJob("failed", "failed", {
    progress: 10,
    message: "Counted 6 of 60",
    finished_at: ENDED,
    error: "The worker 4242 stopped answering after 3 attempts.",
  }),
  aJob("cancelling", "running", {
    progress: 20,
    message: "Counted 12 of 60",
    cancel_requested_at: ENDED,
  }),
  aJob("queued", "queued"),
  aJob("cancelled", "cancelled", {
    progress: 5,
    message: "Counted 3 of 60",
    finished_at: ENDED,
  }),
  aJob("timed-out", "timed_out", {
    progress: 50,
    message: "Counted 30 of 60",
    finished_at: ENDED,
    error: "The job ran past its time.",
  }),
]

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
  // A job's stream is open only while the job is active, or the browser's six connections to
  // the server would run out after a few jobs: none is left once the job is cancelled.
  const streams = new Set<Request>()
  page.on("request", (request) => {
    if (request.url().includes("/v1/streams/")) {
      streams.add(request)
    }
  })
  page.on("requestfinished", (request) => streams.delete(request))
  page.on("requestfailed", (request) => streams.delete(request))
  await page.emulateMedia({ reducedMotion: "reduce" })
  const indicator = page.getByTestId("jobs-indicator")
  const drawer = page.getByRole("dialog", { name: "Jobs" })
  const row = drawer.getByTestId("job-row").first()
  const fill = row.locator('[data-slot="progress-indicator"]')

  await page.goto("/settings")
  await page.getByRole("button", { name: "Run demo job" }).click()
  await expect(page.getByRole("status")).toHaveText("Demo job queued")
  await expect(indicator).toHaveAccessibleName(/^Jobs, 1 (queued|running)$/)

  await page.goto("/")
  const card = page.getByRole("region", { name: "Running jobs" })
  await expect
    .poll(() => progressOf(card.getByRole("progressbar")), { timeout: 30_000 })
    .toBeGreaterThan(0)
  await expect(card.getByTestId("running-job")).toContainText("Demo job")
  await expect(indicator).toHaveAccessibleName("Jobs, 1 running")
  await screenshot(page, "home-running-job")

  await indicator.click()
  await expect(drawer).toBeVisible()
  await expect(row).toContainText("Demo job")
  await expect(row).toContainText("Running")
  const before = await progressOf(row.getByRole("progressbar"))
  expect(before).toBeGreaterThan(0)
  // The look of web/DESIGN.md in the dark theme: the solid 72 px top bar, the skill's icon
  // button in heading text, the bar's brand fill on its track, and Cancel in the purple.
  const topBar = page.getByTestId("top-bar")
  await expect(topBar).toHaveCSS("position", "sticky")
  await expect(topBar).toHaveCSS("height", "72px")
  await expect(topBar).toHaveCSS("background-color", "rgb(5, 5, 5)")
  await expect(indicator).toHaveCSS("background-color", "rgb(17, 17, 17)")
  await expect(indicator).toHaveCSS("border-color", "rgb(26, 26, 26)")
  await expect(indicator).toHaveCSS("color", "rgb(237, 237, 237)")
  await expect(drawer.getByRole("button", { name: "Close" })).toHaveCSS(
    "color",
    "rgb(237, 237, 237)"
  )
  await expect(row.getByRole("progressbar")).toHaveCSS(
    "background-color",
    "rgb(26, 26, 26)"
  )
  await expect(fill).toHaveCSS("background-color", "rgb(252, 115, 77)")
  await expect(row.getByTestId("job-cancel")).toHaveCSS(
    "color",
    "rgb(168, 85, 247)"
  )
  // Reduced motion stops the drawer's slide and the bar's.
  await expect(drawer).toHaveCSS("animation-duration", "0s")
  await expect(fill).toHaveCSS("transition-duration", "0s")
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
  const resumed = await progressOf(row.getByRole("progressbar"))
  expect(resumed).toBeGreaterThanOrEqual(before)
  // And it moves on, through the stream the reload opened anew.
  await expect
    .poll(() => progressOf(row.getByRole("progressbar")), { timeout: 10_000 })
    .toBeGreaterThan(resumed)

  await row.getByTestId("job-cancel").click()
  await expect(row).toContainText("Cancelled", { timeout: 15_000 })
  await expect.poll(() => streams.size).toBe(0)
  await expect(row.getByRole("progressbar")).toHaveCount(0)
  await expect(indicator).toHaveAccessibleName("Jobs")
  await expect(card.getByText("No jobs running.")).toBeVisible()
  await screenshot(page, "jobs-drawer-cancelled")

  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()
  await expect(indicator).toBeFocused()
  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
  expect(errors).toEqual([])
})

test("a hidden tab leaves its connections to the shown one", async ({
  loggedIn: page,
}) => {
  // The Phase 4 exit's reviews: Chromium keeps six connections to one host for all the tabs
  // of the browser, so two tabs that followed three jobs each held all six, and every other
  // request of both waited until a reload; a hidden tab now follows no stream.
  let streams = 0
  page.context().on("request", (request: Request) => {
    if (request.url().includes("/v1/streams/")) {
      streams += 1
    }
  })
  await startDemoJobs(page.request, 3)
  const other = await page.context().newPage()
  await page.goto("/")
  await other.goto("/")
  await expect.poll(() => streams).toBeGreaterThanOrEqual(6)

  await other.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden" })
    document.dispatchEvent(new Event("visibilitychange"))
  })
  const answered = await page.evaluate(() =>
    Promise.race([
      fetch("/v1/version").then((response) => String(response.status)),
      new Promise<string>((resolve) =>
        setTimeout(() => resolve("stalled"), 5_000)
      ),
    ])
  )

  expect(answered).toBe("200")
  await other.close()
})

test("the streams of jobs that ended close while every connection is taken", async ({
  loggedIn: page,
}) => {
  // Two shown tabs that follow three jobs each still hold all six connections: a stream closed
  // only once a new list showed its job ended, and that list waited for a connection, so the
  // tabs stayed stuck after the jobs had ended; a stream now closes at its job's end.
  let streams = 0
  page.context().on("request", (request: Request) => {
    if (request.url().includes("/v1/streams/")) {
      streams += 1
    }
  })
  await startDemoJobs(page.request, 3)
  const other = await page.context().newPage()
  await page.goto("/")
  await other.goto("/")
  await expect.poll(() => streams).toBeGreaterThanOrEqual(6)

  await cancelActiveJobs(page.request)
  const answered = await page.evaluate(() =>
    Promise.race([
      fetch("/v1/version").then((response) => String(response.status)),
      new Promise<string>((resolve) =>
        setTimeout(() => resolve("stalled"), 10_000)
      ),
    ])
  )

  expect(answered).toBe("200")
  await other.close()
})

test("the drawer shows every status, the active jobs first, an empty list, and its own failure", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.route("**/v1/jobs", (route) =>
    route.fulfill({ json: EVERY_STATUS })
  )
  const indicator = page.getByTestId("jobs-indicator")
  const drawer = page.getByRole("dialog", { name: "Jobs" })
  const rows = drawer.getByTestId("job-row")
  await page.goto("/")
  await expect(indicator).toHaveAccessibleName("Jobs, 2 running, 1 queued")

  await indicator.click()
  await expect(rows).toHaveCount(EVERY_STATUS.length)
  const badges = [
    "Running",
    "Cancelling",
    "Queued",
    "Succeeded",
    "Failed",
    "Cancelled",
    "Timed out",
  ]
  for (const [index, badge] of badges.entries()) {
    await expect(rows.nth(index)).toContainText(badge)
  }
  await expect(rows.nth(1).getByTestId("job-cancel")).toBeDisabled()
  const card = page.getByRole("region", { name: "Running jobs" })
  await expect(card.getByTestId("running-job")).toHaveText([
    /Counted 24 of 60/,
    /Cancelling/,
    /Queued/,
  ])
  await screenshot(page, "jobs-drawer-statuses")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await screenshot(page, "jobs-drawer-statuses-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  await page.unroute("**/v1/jobs")
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: [] }))
  await page.reload()
  await indicator.click()
  await expect(drawer).toContainText("No jobs yet.")

  await page.unroute("**/v1/jobs")
  await page.route("**/v1/jobs", (route) =>
    route.fulfill(
      problemAnswer(500, "The jobs could not be read, for this test.")
    )
  )
  await page.reload()
  await indicator.click()
  await expect(drawer.getByRole("alert")).toHaveText(
    "The jobs could not be read, for this test."
  )
  await expect(drawer.getByRole("button", { name: "Try again" })).toBeVisible()
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
