import type { Page } from "@playwright/test"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { strategyFromTemplate } from "./support/strategies.ts"

// Launching runs from the strategy page (step 5.6), on the seeded ES through the real pool and the
// executor. It runs in a project of its own after the delete's, since a saved run changes what the
// delete's card counts, and last, MES being gone by then, whose absence its last test reads.

// The builder's check as a clip: a launch followed to its page.
test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const RUN_TIMEOUT = 120_000

async function openTheDialog(page: Page) {
  await page.goto("/strategies/strategy?name=demo")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  return dialog
}

test("a run launched from the strategy page reaches 100% and lands on its page", async ({
  loggedIn: page,
}) => {
  // Done means 1: another lookback makes a run the seed did not, which the job has to make.
  const errors = consoleErrors(page)
  const dialog = await openTheDialog(page)
  await dialog.getByLabel("lookback").fill("6")
  await dialog.getByLabel("lookback").blur()

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(/\/runs\/run\?/)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")
  await expect(page).toHaveURL(/key=[0-9a-f]{64}/, { timeout: RUN_TIMEOUT })
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  await expect(page.getByTestId("run-cached")).toHaveCount(0)
  await expect(page.getByTestId("run-key")).toBeVisible()
  await expect(page.getByRole("region", { name: "Parameters" })).toContainText(
    "6"
  )
  const key = new URL(page.url()).searchParams.get("key")
  const run = await (await page.request.get(`/v1/runs/${key}`)).json()
  const job = await (await page.request.get(`/v1/jobs/${run.job_id}`)).json()
  expect(job.progress).toBe(100)
  await page.mouse.move(700, 36)
  await screenshot(page, "run-launched")
  expect(errors).toEqual([])
})

test("the same run launched again opens the saved run with its Cached badge", async ({
  loggedIn: page,
}) => {
  // Done means 2: the request is found saved, so the page opens on it at once, no job run.
  const before = await page.request.get("/v1/jobs")
  const jobsBefore = (await before.json()).length
  const dialog = await openTheDialog(page)
  await dialog.getByLabel("lookback").fill("6")
  await dialog.getByLabel("lookback").blur()

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(/key=[0-9a-f]{64}/)
  await expect(page.getByTestId("run-cached")).toHaveText("Cached")
  await expect(page.getByText("FEAT found this run saved")).toBeVisible()
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  const after = await page.request.get("/v1/jobs")
  expect((await after.json()).length).toBe(jobsBefore)
  await page.mouse.move(700, 36)
  await screenshot(page, "run-cached")
})

test("a job whose run proves saved under another row ends on that run", async ({
  loggedIn: page,
}) => {
  // The seed ran demo from 03-05, the dialog's window is the data's 03-06: another request, whose
  // job finds the seed's run saved by its key, removes its own row, and names the seed's.
  const listed = await page.request.get("/v1/runs", {
    params: { strategy: "demo" },
  })
  const seeded = (await listed.json()).runs.at(-1).run_key
  const dialog = await openTheDialog(page)

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(`/runs/run?key=${seeded}`, {
    timeout: RUN_TIMEOUT,
  })
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  await expect(page.getByTestId("run-cached")).toHaveText("Cached")
})

test("Run with stress asks for the run at one and at two more ticks", async ({
  loggedIn: page,
}) => {
  const dialog = await openTheDialog(page)
  await dialog.getByLabel("lookback").fill("9")
  await dialog.getByLabel("lookback").blur()

  await dialog.getByTestId("run-stress").click()

  await expect(page).toHaveURL(/\/runs\?strategy=demo/)
  await expect(page.getByTestId("runs-stressed")).toContainText(
    "at 1 and at 2 more ticks"
  )
  const slippages = page.getByTestId("run-slippage")
  await expect(slippages.filter({ hasText: "2 ticks" })).toHaveCount(1, {
    timeout: RUN_TIMEOUT,
  })
  await expect(slippages.filter({ hasText: "3 ticks" })).toHaveCount(1)
  await expect(page.getByTestId("run-pnl")).not.toHaveCount(0, {
    timeout: RUN_TIMEOUT,
  })
  await page.mouse.move(700, 36)
  await screenshot(page, "runs-stressed")

  // The line stays while the filters change, so that the list does not jump under the pointer.
  await page.getByLabel("Status").click()
  await page.getByRole("option", { name: "Succeeded" }).click()
  await expect(page).toHaveURL(/status=succeeded/)
  await expect(page.getByTestId("runs-stressed")).toBeVisible()
})

test("a strategy on data FEAT does not hold cannot run, and the dialog says why", async ({
  loggedIn: page,
}) => {
  // The delete's project removed MES, the templates' instrument, before this one.
  await strategyFromTemplate(page.request, "no_data_yet", "breakout")
  await page.goto("/strategies/strategy?name=no_data_yet")

  await page.getByTestId("run-backtest").click()

  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByRole("alert")).toContainText(
    "FEAT holds no data of MES."
  )
  await expect(dialog.getByRole("link", { name: "Import data" })).toBeVisible()
  await expect(dialog.getByTestId("run-launch")).toHaveCount(0)
})
