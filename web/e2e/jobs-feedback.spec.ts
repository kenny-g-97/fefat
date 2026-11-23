import type { Page } from "@playwright/test"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  aJob,
  cancelActiveJobs,
  progressOf,
  startDemoJobs,
} from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// Step 5.19: one stream per tab carries every job, a job tells how it ended wherever you are, and
// the drawer's rows hold still under the pointer. The list and the stream are answered by the
// spec where a state cannot be made to order, as a failure; Run again runs a real demo job.

const LIST = "**/v1/jobs"
const STREAM = "**/v1/streams/jobs"
const ENDED = "2026-11-09T10:01:00Z"
const FAILED_WORDS =
  "This job stopped answering after 3 attempts. Run it again, and restart FEAT if it stops the same way."

type ListedJob = ReturnType<typeof aJob>

/** Answer the list with what the returned holder's `jobs` says at each read. */
async function listAnswered(page: Page, jobs: readonly ListedJob[]) {
  const answer = { jobs }
  await page.route(LIST, (route) => route.fulfill({ json: answer.jobs }))
  return answer
}

/** The window getting the focus, which asks for the list. */
async function windowFocused(page: Page): Promise<void> {
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
}

function drawerOf(page: Page) {
  return page.getByRole("dialog", { name: "Jobs" })
}

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("one stream moves five active jobs", async ({ loggedIn: page }) => {
  // Done means 1: a fifth active job is live too, over one connection. Only the first read of
  // the list is answered, so that the stream's events alone can move the bars.
  const ids = ["one", "two", "three", "four", "five"]
  let reads = 0
  await page.route(LIST, async (route) => {
    reads += 1
    if (reads === 1) {
      await route.fulfill({
        json: ids.map((id) => aJob(id, "running", { progress: 5 })),
      })
    }
  })
  const streams = new Set<string>()
  page.on("request", (request) => {
    if (request.url().includes("/v1/streams/")) {
      streams.add(new URL(request.url()).pathname)
    }
  })
  const reports = ids
    .map((id, index) => {
      const percent = (index + 1) * 10
      const said = { job_id: id, percent, message: `Counted ${percent}` }
      return `id: ${index + 1}\nevent: progress\ndata: ${JSON.stringify(said)}\n\n`
    })
    .join("")
  await page.route(STREAM, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: reports,
    })
  )

  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const rows = drawerOf(page).getByTestId("job-row")

  await expect(rows).toHaveCount(5)
  for (const index of ids.keys()) {
    await expect
      .poll(() => progressOf(rows.nth(index).getByRole("progressbar")))
      .toBe((index + 1) * 10)
  }
  expect([...streams]).toEqual(["/v1/streams/jobs"])
})

test("the jobs button carries a failure dot until the drawer opens", async ({
  loggedIn: page,
}) => {
  // Done means 3: the dot, its label, and the shell's polite words on the job's end.
  await page.emulateMedia({ reducedMotion: "reduce" })
  const answer = await listAnswered(page, [
    aJob("watched", "running", { kind: "backtest", progress: 60 }),
  ])
  await page.route(STREAM, (route) => route.abort())
  const indicator = page.getByTestId("jobs-indicator")
  const dot = page.getByTestId("jobs-failure-dot")
  await page.goto("/")
  await expect(indicator).toHaveAccessibleName("Jobs, 1 running")
  await expect(dot).toHaveCount(0)

  answer.jobs = [
    aJob("watched", "failed", {
      kind: "backtest",
      progress: 60,
      finished_at: ENDED,
      error: `${FAILED_WORDS}\nThe log's last line`,
    }),
  ]
  await windowFocused(page)

  await expect(dot).toBeVisible()
  await expect(indicator).toHaveAccessibleName("Jobs, Backtest failed")
  await expect(indicator).toHaveAttribute("title", "Jobs, Backtest failed")
  await expect(page.getByTestId("jobs-said")).toHaveText("Backtest failed")
  await expect(page.getByTestId("jobs-said")).toHaveAttribute(
    "aria-live",
    "polite"
  )
  await expect(dot).toHaveCSS("background-color", "rgb(255, 77, 109)")
  await screenshot(page, "jobs-failure-dot")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  await indicator.click()

  const error = drawerOf(page).getByTestId("job-error")
  await expect(error).toContainText(FAILED_WORDS)
  await expect(error).toHaveCSS("white-space", "pre-wrap")
  await expect(dot).toHaveCount(0)
  await expect(indicator).toHaveAccessibleName("Jobs")
  await expect(
    drawerOf(page).getByRole("button", { name: "Close" })
  ).toHaveAttribute("title", "Close")
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth
    )
  ).toBe(true)
})

test("the drawer opens on a failure below the running jobs", async ({
  loggedIn: page,
}) => {
  // The dot goes as the drawer opens, so the row it stood for has to be in view.
  const running = Array.from({ length: 9 }, (_, index) =>
    aJob(`running-${index}`, "running", { progress: 10 })
  )
  const answer = await listAnswered(page, [
    ...running,
    aJob("watched", "running", { progress: 60 }),
  ])
  await page.route(STREAM, (route) => route.abort())
  const indicator = page.getByTestId("jobs-indicator")
  await page.goto("/")
  await expect(indicator).toHaveAccessibleName("Jobs, 10 running")

  answer.jobs = [
    ...running,
    aJob("watched", "failed", {
      progress: 60,
      finished_at: ENDED,
      error: FAILED_WORDS,
    }),
  ]
  await windowFocused(page)
  await expect(page.getByTestId("jobs-failure-dot")).toBeVisible()
  await indicator.click()

  await expect(drawerOf(page).getByTestId("job-error")).toBeInViewport()
})

test("a cancelled job raises no failure dot, and a first read says nothing", async ({
  loggedIn: page,
}) => {
  const answer = await listAnswered(page, [
    aJob("old-failure", "failed", { finished_at: ENDED }),
    aJob("watched", "running", { progress: 10 }),
  ])
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  await expect(page.getByTestId("jobs-indicator")).toHaveAccessibleName(
    "Jobs, 1 running"
  )

  answer.jobs = [
    aJob("old-failure", "failed", { finished_at: ENDED }),
    aJob("watched", "cancelled", { progress: 10, finished_at: ENDED }),
  ]
  await windowFocused(page)

  await expect(page.getByTestId("jobs-said")).toHaveText("Demo job cancelled")
  await expect(page.getByTestId("jobs-failure-dot")).toHaveCount(0)
})

test("a row reads Reconnecting while its stream waits", async ({
  loggedIn: page,
}) => {
  // Done means 3.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await listAnswered(page, [
    aJob("watched", "running", { progress: 40, message: "Counted 24 of 60" }),
    aJob("done", "succeeded", {
      progress: 100,
      message: "Counted 60 of 60",
      finished_at: ENDED,
    }),
  ])
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const rows = drawerOf(page).getByTestId("job-row")

  await expect(rows.first()).toContainText("Reconnecting")
  await expect(rows.first()).not.toContainText("Counted 24 of 60")
  await expect(rows.nth(1)).toContainText("Counted 60 of 60")
  await screenshot(page, "jobs-drawer-reconnecting")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  // After three waits, about seven seconds, it asks what to check.
  await expect(rows.first()).toContainText(
    "Reconnecting: is fefat up still running?",
    { timeout: 15_000 }
  )

  await page.unroute(STREAM)

  await expect(rows.first()).toContainText("Counted 24 of 60", {
    timeout: 15_000,
  })
  await expect(rows.first()).not.toContainText("Reconnecting")
})

test("a read of the list that fails leaves the rows in the drawer", async ({
  loggedIn: page,
}) => {
  // With the server down, the rows must stay to say they are reconnecting.
  let reads = 0
  await page.route(LIST, (route) => {
    reads += 1
    return reads === 1
      ? route.fulfill({
          json: [aJob("watched", "running", { progress: 40 })],
        })
      : route.fulfill(problemAnswer(502, "The server did not answer."))
  })
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  const indicator = page.getByTestId("jobs-indicator")
  await expect(indicator).toHaveAccessibleName("Jobs, 1 running")
  await indicator.click()
  const before = reads

  await windowFocused(page)

  await expect.poll(() => reads).toBeGreaterThan(before)
  const row = drawerOf(page).getByTestId("job-row").first()
  await expect(row).toContainText("Reconnecting")
  await expect(drawerOf(page).getByRole("alert")).toHaveCount(0)
})

test("a stream refused once the session ended leads to the login", async ({
  loggedIn: page,
}) => {
  await listAnswered(page, [aJob("watched", "running", { progress: 40 })])
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const row = drawerOf(page).getByTestId("job-row").first()
  await expect(row).toContainText("Reconnecting")

  const refused = { status: 401, json: { detail: "The session ended." } }
  await page.route("**/v1/me", (route) => route.fulfill(refused))
  await page.unroute(STREAM)
  await page.route(STREAM, (route) => route.fulfill(refused))

  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
})

test("Run again queues a cancelled job, which runs and shows live", async ({
  loggedIn: page,
}) => {
  // Done means 3, and the undo of a Cancel, on a real job of the pool.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await startDemoJobs(page.request, 1)
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const rows = drawerOf(page).getByTestId("job-row")
  const first = rows.first()
  await expect
    .poll(() => progressOf(first.getByRole("progressbar")), { timeout: 30_000 })
    .toBeGreaterThan(0)

  await first.getByTestId("job-cancel").click()
  await expect(first).toContainText("Cancelled", { timeout: 15_000 })
  const runAgain = first.getByTestId("job-run-again")
  await expect(runAgain).toBeEnabled()
  await expect(runAgain).toHaveCSS("color", "rgb(168, 85, 247)")
  await page.mouse.move(0, 0)
  await screenshot(page, "jobs-drawer-run-again")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // The list holds still under the pointer, so the new job's row comes once it leaves.
  const listed = await rows.count()
  await runAgain.click()
  await expect(first.getByTestId("job-queued-again")).toHaveText(
    /^(Queued|Running) again$/
  )
  await expect(rows).toHaveCount(listed)
  await page.mouse.move(0, 0)

  await expect(rows).toHaveCount(listed + 1)
  await expect(first).not.toContainText("Cancelled")
  await expect
    .poll(() => progressOf(first.getByRole("progressbar")), { timeout: 30_000 })
    .toBeGreaterThan(0)
  await expect(rows.nth(1)).toContainText(/(Queued|Running) again/)
})

test("Run again from the keyboard moves the focus to what it did", async ({
  loggedIn: page,
}) => {
  const watched = aJob("watched", "cancelled", { finished_at: ENDED })
  const next = aJob("next", "queued")
  const answer = await listAnswered(page, [watched])
  await page.route("**/v1/jobs/watched/run-again", (route) => {
    answer.jobs = [next, watched]
    return route.fulfill({ status: 202, json: next })
  })
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const drawer = drawerOf(page)

  await drawer.getByTestId("job-run-again").focus()
  await page.keyboard.press("Enter")

  await expect(drawer.getByTestId("job-queued-again")).toBeFocused()
})

test("a double click on Cancel, or a late click on its place, never runs the job again", async ({
  loggedIn: page,
}) => {
  // The reviews of step 5.19: Run again stands away from Cancel's place, and a double click acts
  // once wherever its second click lands.
  await page.emulateMedia({ reducedMotion: "reduce" })
  const watched = aJob("watched", "queued")
  const cancelled = aJob("watched", "cancelled", { finished_at: ENDED })
  const answer = await listAnswered(page, [watched])
  await page.route(STREAM, (route) => route.abort())
  let cancels = 0
  await page.route("**/v1/jobs/watched/cancel", (route) => {
    cancels += 1
    answer.jobs = [cancelled]
    return route.fulfill({ json: cancelled })
  })
  let runsAgain = 0
  await page.route("**/v1/jobs/watched/run-again", (route) => {
    runsAgain += 1
    return route.fulfill({ status: 202, json: aJob("next", "queued") })
  })
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const row = drawerOf(page).getByTestId("job-row").first()
  const cancel = row.getByTestId("job-cancel")
  const place = await cancel.boundingBox()
  if (place === null) {
    throw new Error("Expected Cancel drawn on the row, got nothing.")
  }

  await cancel.dblclick()
  await expect(row).toContainText("Cancelled")
  await page.mouse.click(place.x + place.width / 2, place.y + place.height / 2)

  expect(runsAgain).toBe(0)
  expect(cancels).toBe(1)
  const runAgain = row.getByTestId("job-run-again")
  await runAgain.dispatchEvent("click", { detail: 2 })
  expect(runsAgain).toBe(0)

  await runAgain.click()
  await expect(row.getByTestId("job-queued-again")).toBeVisible()
  expect(runsAgain).toBe(1)
})

test("the drawer's rows hold their place while the pointer is over the list", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const older = aJob("older", "running", { progress: 20, message: "Older" })
  const newer = aJob("newer", "running", { progress: 30, message: "Newer" })
  const answer = await listAnswered(page, [newer, older])
  await page.route(STREAM, (route) => route.abort())
  await page.goto("/")
  await page.getByTestId("jobs-indicator").click()
  const rows = drawerOf(page).getByTestId("job-row")
  await expect(rows).toHaveCount(2)
  const cancelBelow = rows.nth(1).getByTestId("job-cancel")
  const before = await cancelBelow.boundingBox()
  await page.getByTestId("job-list").hover()

  answer.jobs = [
    aJob("started", "queued"),
    aJob("newer", "failed", {
      progress: 30,
      finished_at: ENDED,
      error: `${FAILED_WORDS}\nA second line\nA third line\nA fourth line`,
    }),
    { ...older, progress: 25 },
  ]
  await windowFocused(page)

  await expect(rows.first()).toContainText("Failed")
  await expect(rows.first().getByTestId("job-held-error")).toBeVisible()
  await expect(rows.first().getByTestId("job-error")).toHaveCount(0)
  await expect(rows).toHaveCount(2)
  await expect
    .poll(() => progressOf(rows.nth(1).getByRole("progressbar")))
    .toBe(25)
  expect(await cancelBelow.boundingBox()).toEqual(before)

  await page.mouse.move(0, 0)

  await expect(rows).toHaveCount(3)
  await expect(rows.first()).toContainText("Queued")
  await expect(rows.nth(1)).toContainText("Running")
  await expect(rows.nth(2)).toContainText("Failed")
  await expect(rows.nth(2).getByTestId("job-error")).toBeVisible()
})
