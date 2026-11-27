import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"
import { strategyFromTemplate } from "./support/strategies.ts"

// Launching runs from the strategy page (step 5.6), on the seeded ES through the real pool and the
// executor. It runs in a project of its own after the delete's, since a saved run changes what the
// delete's card counts, and last, MES being gone by then, whose absence its last test reads.

// The builder's check as a clip: a launch followed to its page.
test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const RUN_TIMEOUT = 120_000

/** The Run backtest dialog of the seed's version 1 of demo, whose run is `demo-run-01`: its
 * version 2, a wider stop, is the latest since step 5.10. */
async function openTheDialog(page: Page) {
  await page.goto("/strategies/strategy?name=demo&version=1")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  return dialog
}

const estimateAsked = z.looseObject({
  settings: z.looseObject({ instrument: z.string().optional() }),
})

async function topOf(drawn: Locator) {
  const box = await drawn.boundingBox()
  if (box === null) {
    throw new Error("Expected a drawn element, got none.")
  }
  return box.y
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
  // Step 5.7: the run's results stand on the page it lands on.
  await expect(page.getByTestId("key-figures")).toBeVisible()
  await expect(page.getByTestId("histogram-pnl")).toBeVisible()
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

test("a strategy written for data FEAT lacks runs on the instrument chosen", async ({
  loggedIn: page,
}) => {
  // D-114: the template names MES, gone by now, and the run trades ES, as if the code named it.
  const errors = consoleErrors(page)
  await strategyFromTemplate(page.request, "written_for_mes", "breakout")
  await page.goto("/strategies/strategy?name=written_for_mes")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByRole("alert")).toHaveText(
    "FEAT holds no data of MES. Choose one it holds, or import MES's bars or ticks."
  )
  await expect(dialog.getByLabel("Instrument")).toBeFocused()
  const topWithoutData = await topOf(dialog.getByLabel("Instrument"))
  await page.mouse.move(700, 36)
  await screenshot(page, "run-dialog-no-data", [], "window")

  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "ES", exact: true }).click()

  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await expect(dialog.getByLabel("Instrument")).toBeFocused()
  // The form grows below the field, which stays under the pointer.
  expect(await topOf(dialog.getByLabel("Instrument"))).toBeCloseTo(
    topWithoutData,
    0
  )
  await expect(dialog.getByTestId("run-estimate")).toContainText(
    "Trades ES, not the code's MES: "
  )
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await expect(
    dialog.getByText("Version 1 of written_for_mes, written for MES in 5m bars")
  ).toBeVisible()
  // Another lookback than the other specs', so that the run is this strategy's own.
  await dialog.getByLabel("lookback").fill("7")
  await dialog.getByLabel("lookback").blur()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-dialog-instrument", [], "window")

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(/key=[0-9a-f]{64}/, { timeout: RUN_TIMEOUT })
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "written_for_mes"
  )
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  await expect(page.getByText(/^Version 1, ES in 5m bars, /)).toBeVisible()
  const instrument = page
    .getByTestId("run-settings")
    .getByRole("definition")
    .first()
  await expect(instrument).toHaveText("ES")
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-page-instrument")

  await page.getByRole("link", { name: "Back to Runs" }).click()
  const row = page.getByTestId("run-row").filter({ hasText: "written_for_mes" })
  await expect(row.getByTestId("run-parameters")).toContainText(
    "ES in 5m bars, lookback 7"
  )
  expect(errors).toEqual([])
})

test("a launch that finds the run saved under another version says which", async ({
  loggedIn: page,
}) => {
  // The template on ES at the lookback of this file's first test is the run demo made there.
  await page.goto("/strategies/strategy?name=written_for_mes")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "ES", exact: true }).click()
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await dialog.getByLabel("lookback").fill("6")
  await dialog.getByLabel("lookback").blur()

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(/key=[0-9a-f]{64}/, { timeout: RUN_TIMEOUT })
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")
  await expect(page.getByTestId("run-cached")).toHaveText("Cached")
  await expect(
    page.getByText(
      "FEAT found this run saved under demo, version 1, whose code gives the same signals, and opened it."
    )
  ).toBeVisible()
})

test("an instrument the server refuses, where the code's has no data, can be changed", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "refused_choice", "breakout")
  await page.route("**/v1/runs/estimate", async (route) => {
    const asked = estimateAsked.parse(route.request().postDataJSON())
    if (asked.settings.instrument === "BTCUSDT-PERP") {
      await route.fulfill(
        problemAnswer(400, "Expected an instrument it can read, got this one.")
      )
      return
    }
    await route.fallback()
  })
  await page.goto("/strategies/strategy?name=refused_choice")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByRole("alert")).toContainText(
    "FEAT holds no data of MES."
  )

  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "BTCUSDT-PERP" }).click()

  await expect(dialog.getByRole("alert")).toHaveText(
    "Expected an instrument it can read, got this one."
  )
  await expect(dialog.getByLabel("Instrument")).toHaveText("BTCUSDT-PERP")

  // Closed and opened on the refused choice, the field still stands.
  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await page.getByTestId("run-backtest").click()
  await expect(dialog.getByRole("alert")).toHaveText(
    "Expected an instrument it can read, got this one."
  )
  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "ES", exact: true }).click()

  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await expect(dialog.getByRole("alert")).toHaveCount(0)
})

test("an instrument whose data has gone can still be changed back", async ({
  loggedIn: page,
}) => {
  // The store answers it holds nothing at all: the code's own and the choice stay offered.
  await strategyFromTemplate(page.request, "emptied_store", "breakout")
  await page.route("**/v1/runs/estimate", async (route) => {
    const asked = estimateAsked.parse(route.request().postDataJSON())
    if (asked.settings.instrument !== "ES") {
      await route.fallback()
      return
    }
    await route.fulfill({
      json: {
        state: "no_data",
        instrument: "ES",
        timeframe: "5m",
        instruments: [],
      },
    })
  })
  await page.goto("/strategies/strategy?name=emptied_store")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "ES", exact: true }).click()
  await expect(dialog.getByRole("alert")).toHaveText(
    "FEAT holds no data of ES. Import its bars or ticks, then run this strategy."
  )

  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "MES", exact: true }).click()

  await expect(dialog.getByRole("alert")).toContainText(
    "FEAT holds no data of MES."
  )
})
