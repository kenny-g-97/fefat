import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey, theSeededRuns } from "./support/seeded-run.ts"

// Reproduce of step 5.10 (D-126) against the seeded server: `demo-run-01` made again as a
// `reproduce` job from its pinned version and data, its trades' hash matching the saved run's
// (Done means 2 for a synthetic run, as the run page shows it; the job's own test is
// python/tests/server/test_http_run_reproductions.py).

const REPRODUCTION_TIMEOUT = 90_000

test.use({ timezoneId: "UTC" })

const job = z.looseObject({
  id: z.string(),
  kind: z.string(),
  status: z.string(),
  payload: z.looseObject({ reproduces: z.string().optional() }),
  result: z.looseObject({ verdict: z.string() }).nullable(),
  finished_at: z.string().nullable(),
})

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("Reproduce makes the seeded run again and says its trades match", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  await page.goto(`/runs/run?key=${key}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")

  const asked = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/v1/runs/${key}/reproduce`) &&
      response.request().method() === "POST"
  )
  await page.getByTestId("reproduce-run").click()
  // The press's own job, since another spec's reproduction of this run may stand in the list.
  const queued = job.parse(await (await asked).json())
  expect([queued.kind, queued.payload.reproduces]).toEqual(["reproduce", key])
  await expect(page.getByTestId("reproduce-run")).toBeDisabled()

  await expect
    .poll(
      async () =>
        job.parse(
          await (await page.request.get(`/v1/jobs/${queued.id}`)).json()
        ).status,
      { timeout: REPRODUCTION_TIMEOUT }
    )
    .toBe("succeeded")
  const ended = job.parse(
    await (await page.request.get(`/v1/jobs/${queued.id}`)).json()
  )
  expect(ended.result?.verdict).toBe("matched")
  if (ended.finished_at === null) {
    throw new Error("Expected the reproduction's end, got none.")
  }
  // The verdict says when its job ended, to the minute in the browser's time zone, UTC here.
  const ending = ended.finished_at.slice(0, 16).replace("T", " ")
  const line = page.getByTestId("reproduction")
  await expect(line).toContainText(
    `Reproduced ${ending}: the trades match the saved run's, hash`
  )
  await expect(page.getByTestId("reproduce-run")).toBeEnabled()
  await expect(page.getByTestId("reproduction-hash")).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-reproduced")

  // A reload reads the run's newest reproduction, which another spec's may be.
  await page.reload()
  await expect(line).toContainText(
    /Reproduced [0-9-]+ [0-9:]+: the trades match the saved run's, hash/
  )
  expect(errors).toEqual([])
})

test("a run's page leaves no room for its reproduction until one is asked for", async ({
  loggedIn: page,
}) => {
  // Version 2's seeded run, which no spec reproduces, so that its line stands empty.
  const [, second] = await theSeededRuns(page)
  await page.goto(`/runs/run?key=${second}`)
  await expect(page.getByTestId("kpi-pnl")).toBeVisible()

  const gap = await page.getByTestId("reproduction").evaluate((region) => {
    const above = region.previousElementSibling
    const below = region.nextElementSibling
    if (above === null || below === null) {
      throw new Error(
        "Expected the status line above the reproduction's line and the results under it, got none."
      )
    }
    return (
      below.getBoundingClientRect().top - above.getBoundingClientRect().bottom
    )
  })

  // The column's 24 px alone, the empty line's own gap taken back (web/DESIGN.md, Reproduce).
  expect(gap).toBeCloseTo(24, 0)
})
