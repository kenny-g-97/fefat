import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// Reproduce of step 5.10 (D-126) against the seeded server: `demo-run-01` made again as a
// `reproduce` job from its pinned version and data, its trades' hash matching the saved run's
// (Done means 2 for a synthetic run, as the run page shows it; the job's own test is
// python/tests/server/test_http_run_reproductions.py).

const REPRODUCTION_TIMEOUT = 90_000

const job = z.looseObject({
  id: z.string(),
  kind: z.string(),
  status: z.string(),
  payload: z.looseObject({ reproduces: z.string().optional() }),
  result: z.looseObject({ verdict: z.string() }).nullable(),
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
  const line = page.getByTestId("reproduction")
  await expect(line).toContainText(
    "Reproduced: the trades match the saved run's"
  )
  await expect(page.getByTestId("reproduce-run")).toBeEnabled()
  await expect(page.getByTestId("reproduction-hash")).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-reproduced")

  await page.reload()
  await expect(line).toContainText(
    "Reproduced: the trades match the saved run's"
  )
  expect(errors).toEqual([])
})
