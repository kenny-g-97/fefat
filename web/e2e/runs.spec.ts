import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { moneyText } from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  aJob,
  cancelActiveJobs,
  progressOf,
  startDemoJobs,
} from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The Runs list, the run page, the Run backtest dialog, and Home's cards of step 5.6, against the
// seeded server, reading its saved runs and saving none: the specs that launch runs stand in
// run-launch.spec.ts, after the delete's, which counts the saved runs. A run's progress comes from
// its job's stream, so Done means 3 follows a real demo job through a row answered by the spec,
// since a backtest on the three sessions of the fixtures ends within seconds.

const listed = z.object({
  runs: z.array(
    z.object({
      id: z.string(),
      run_key: z.string(),
      start: z.string(),
      end: z.string(),
      key_metrics: z.object({
        pnl: z.string(),
        trades: z.number(),
        max_drawdown: z.string(),
        verdict: z.string(),
      }),
      settings: z.object({
        fee_table: z.string(),
        provider: z.string(),
        capital: z.string(),
      }),
      currency: z.string(),
      fee: z.object({
        kind: z.literal("futures"),
        per_contract_side: z.string(),
      }),
    })
  ),
})

const estimated = z.object({
  sessions: z.number(),
  bars: z.number(),
  ticks: z.number(),
  held: z.object({ start: z.string(), end: z.string() }),
})

const strategies = z.array(
  z.object({
    name: z.string(),
    versions: z.array(z.object({ id: z.string() })),
  })
)

const identity = z.object({ csrf_token: z.string() })

const estimateAsked = z.looseObject({
  settings: z.object({
    instrument: z.string().optional(),
    provider: z.string().optional(),
    contract: z.string().optional(),
    fidelity: z.string().optional(),
  }),
})

const estimateAnswer = z.looseObject({ settings: z.looseObject({}) })

/** `GET /v1/runs`, whatever its filters and its page. */
const THE_LIST = (url: URL) => url.pathname === "/v1/runs"

/** The seeded run, `demo-run-01`, as the list gives it. */
async function theSeededRun(page: Page) {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const { runs } = listed.parse(await answer.json())
  const seeded = runs.at(-1)
  if (seeded === undefined) {
    throw new Error("Expected the seed's saved run of demo, got none.")
  }
  return seeded
}

/** The Run backtest dialog of the seed's version 1 of demo, whose run is `demo-run-01`: its
 * version 2, a wider stop, is the latest since step 5.10. */
async function openTheDialog(page: Page) {
  await page.goto("/strategies/strategy?name=demo&version=1")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByTestId("run-coverage")).toBeVisible()
  return dialog
}

async function boxOf(drawn: Locator) {
  const box = await drawn.boundingBox()
  if (box === null) {
    throw new Error("Expected a drawn element, got none.")
  }
  return box
}

/** A submission of the seeded strategy waiting on `jobId`, as the list and its page give it. */
function aSubmittedRow(
  seeded: Awaited<ReturnType<typeof theSeededRun>>,
  jobId: string
) {
  return {
    state: "submitted",
    id: "run-live",
    created_at: "2026-11-21T10:00:00Z",
    origin: "manual",
    parameters: { lookback: 24 },
    start: seeded.start,
    end: seeded.end,
    settings: {
      fidelity: "1m",
      latency_ms: 100,
      slippage_ticks: { market: 1, stop: 1 },
      limit_fill: "through",
      roll_handling: "transfer",
      fee_table: seeded.settings.fee_table,
      capital: "50000",
      replay: "skipping",
      provider: seeded.settings.provider,
      contract: null,
      instrument: "ES",
    },
    currency: seeded.currency,
    fee: seeded.fee,
    strategy: {
      strategy_id: "strategy-1",
      name: "demo",
      version_id: "version-1",
      version: 1,
      instrument: "ES",
      timeframe: "5m",
    },
    status: "queued",
    progress: 0,
    message: null,
    error: null,
    job_id: jobId,
    cancel_requested_at: null,
  }
}

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

test("the list shows a saved run's figures as the API gives them", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const seeded = await theSeededRun(page)

  await page.goto("/runs")

  const row = page.getByTestId("run-row").last()
  await expect(row.getByTestId("run-strategy")).toHaveText("demo")
  await expect(row.getByTestId("run-status")).toHaveText("Succeeded")
  await expect(row).toContainText(seeded.start)
  await expect(row).toContainText(seeded.end)
  await expect(row.getByTestId("run-slippage")).toHaveText("1 tick")
  await expect(row.getByTestId("run-parameters")).toContainText("lookback 12")
  // D-117: a row's money carries its currency's sign.
  await expect(row.getByTestId("run-pnl")).toHaveText(
    moneyText(seeded.key_metrics.pnl, seeded.currency)
  )
  await expect(row.getByTestId("run-trades")).toHaveText(
    String(seeded.key_metrics.trades)
  )
  await expect(row.getByTestId("run-drawdown")).toHaveText(
    moneyText(seeded.key_metrics.max_drawdown, seeded.currency)
  )
  await page.mouse.move(700, 36)
  await screenshot(page, "runs-list")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "runs-list-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await row.click()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")
  await expect(page).toHaveURL(`/runs/run?key=${seeded.run_key}`)
  expect(errors).toEqual([])
})

test("the filters stay in the address and say when no run matches", async ({
  loggedIn: page,
}) => {
  await page.goto("/runs")
  await expect(page.getByTestId("run-row").first()).toBeVisible()

  await page.getByLabel("Status").click()
  await page.getByRole("option", { name: "Failed" }).click()

  await expect(page).toHaveURL(/status=failed/)
  await expect(page.getByTestId("run-row")).toHaveCount(0)
  await expect(page.getByText("No run matches these filters.")).toBeVisible()

  await page.reload()
  await expect(page.getByLabel("Status")).toHaveText("Failed")
  await expect(page.getByText("No run matches these filters.")).toBeVisible()

  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page).toHaveURL("/runs")
  await expect(page.getByTestId("run-row").first()).toBeVisible()

  await page.getByLabel("Strategy").click()
  await page.getByRole("option", { name: "No saved version" }).click()
  await expect(page).toHaveURL(/versioned=false/)
  await expect(page.getByText("No run matches these filters.")).toBeVisible()

  await page.getByRole("button", { name: "Clear filters" }).click()
  await page.getByLabel("Strategy").click()
  await page.getByRole("option", { name: "demo" }).click()
  await expect(page).toHaveURL(/strategy=demo/)
  await expect(page.getByTestId("run-strategy").first()).toHaveText("demo")

  // Back to Runs returns to the list as it was filtered.
  await page.getByTestId("run-row").first().click()
  await expect(page.getByTestId("run-page-status")).toBeVisible()
  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page).toHaveURL(/strategy=demo/)
  await expect(page.getByLabel("Strategy")).toHaveText("demo")
})

test("Show more reads the next page, and a list it cannot read fails alone", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const real = await (await page.request.get("/v1/runs")).json()
  const one = z.object({ runs: z.array(z.unknown()) }).parse(real).runs[0]
  const asked: (string | null)[] = []
  await page.route(THE_LIST, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor")
    asked.push(cursor)
    return route.fulfill({
      json:
        cursor === null
          ? { runs: [one], next_cursor: "next-page" }
          : {
              runs: [
                {
                  ...z.object({}).passthrough().parse(one),
                  id: "older",
                  run_key: "b".repeat(64),
                },
              ],
              next_cursor: null,
            },
    })
  })
  await page.goto("/runs")
  await expect(page.getByTestId("run-row")).toHaveCount(1)

  await page.getByTestId("runs-more").click()

  await expect(page.getByTestId("run-row")).toHaveCount(2)
  await expect(page.getByTestId("runs-more")).toHaveCount(0)
  expect(asked).toContain("next-page")
  await page.unroute(THE_LIST)

  await page.route(THE_LIST, (route) =>
    route.fulfill(
      problemAnswer(500, "The runs could not be read, for this test.")
    )
  )
  await page.goto("/runs")
  await expect(page.getByRole("alert")).toHaveText(
    "The runs could not be read, for this test."
  )
  await expect(
    page.getByRole("heading", { level: 1, name: "Runs" })
  ).toBeVisible()
  await page.unroute(THE_LIST)
  await page.getByRole("button", { name: "Try again" }).click()
  await expect(page.getByTestId("run-row").last()).toContainText(seeded.end)
})

test("a running row follows its job live, a reload keeps it, and Cancel stops it", async ({
  loggedIn: page,
}) => {
  // Done means 3: the row's bar moves with the job's stream, and comes back after a reload.
  await startDemoJobs(page.request, 1)
  const jobs = z
    .array(z.object({ id: z.string() }))
    .parse(await (await page.request.get("/v1/jobs")).json())
  const jobId = jobs[0].id
  const seeded = await theSeededRun(page)
  const row = aSubmittedRow(seeded, jobId)
  await page.route(THE_LIST, (route) =>
    route.fulfill({ json: { runs: [row], next_cursor: null } })
  )
  let cancelled = false
  await page.route("**/v1/runs/run-live/cancel", async (route) => {
    cancelled = true
    const { csrf_token } = identity.parse(
      await (await page.request.get("/v1/me")).json()
    )
    await page.request.post(`/v1/jobs/${jobId}/cancel`, {
      headers: { "X-CSRF-Token": csrf_token },
    })
    await route.fulfill({
      json: {
        ...row,
        status: "running",
        cancel_requested_at: "2026-11-21T10:00:01Z",
      },
    })
  })
  await page.emulateMedia({ reducedMotion: "reduce" })

  await page.goto("/runs")
  const listedRow = page.getByTestId("run-row")
  const bar = listedRow.getByRole("progressbar")
  await expect
    .poll(() => progressOf(bar), { timeout: 30_000 })
    .toBeGreaterThan(0)
  const before = await progressOf(bar)
  await expect
    .poll(() => progressOf(bar), { timeout: 15_000 })
    .toBeGreaterThan(before)
  await expect(listedRow.getByTestId("run-status")).toHaveText("Running")
  await screenshot(page, "runs-list-running")

  const moved = await progressOf(bar)
  await page.reload()
  await expect
    .poll(
      () => progressOf(page.getByTestId("run-row").getByRole("progressbar")),
      {
        timeout: 15_000,
      }
    )
    .toBeGreaterThanOrEqual(moved)

  await page.getByTestId("run-cancel").click()
  await expect.poll(() => cancelled).toBe(true)
  await expect(page.getByTestId("run-status")).toHaveText(
    /Cancelling|Cancelled/,
    {
      timeout: 15_000,
    }
  )
})

test("a run that ended without a result still opens from its row", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const failed = {
    ...aSubmittedRow(seeded, "job-ended"),
    status: "failed",
    error: "Expected a level the store holds.",
  }
  await page.route(THE_LIST, (route) =>
    route.fulfill({ json: { runs: [failed], next_cursor: null } })
  )

  await page.goto("/runs")

  const row = page.getByTestId("run-row")
  await expect(row).toContainText(failed.error)
  await expect(row.getByTestId("run-arrow")).toBeVisible()
  await expect(page.getByTestId("run-cancel")).toHaveCount(0)
})

test("a saved run's page shows its status, its key, and every setting", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const seeded = await theSeededRun(page)

  await page.goto(`/runs/run?key=${seeded.run_key}`)

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("demo")
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  await expect(page.getByTestId("run-key")).toHaveText(
    seeded.run_key.slice(0, 12)
  )
  await expect(page.getByTestId("run-cached")).toHaveCount(0)
  const settings = page.getByTestId("run-settings")
  await expect(settings).toContainText(seeded.settings.provider)
  // D-117: the fee table with what it charges the instrument, and the capital in its currency.
  const charge = moneyText(seeded.fee.per_contract_side, seeded.currency)
  await expect(settings).toContainText(
    `Commissions and fees${seeded.settings.fee_table}Per contract per side${charge}`
  )
  await expect(settings).toContainText(
    `Capital${moneyText(seeded.settings.capital, seeded.currency)}`
  )
  // Words stand beside their labels: only figures align right.
  await expect(settings.getByText("Spliced", { exact: true })).not.toHaveCSS(
    "text-align",
    "right"
  )
  // The two columns keep one pitch, whichever holds more rows.
  const secondLeft = await boxOf(
    settings.locator("dl").first().locator("dt").nth(1)
  )
  const secondRight = await boxOf(
    settings.locator("dl").last().locator("dt").nth(1)
  )
  expect(Math.abs(secondRight.y - secondLeft.y)).toBeLessThanOrEqual(2)
  // A run's row keeps the time it was asked for, which is not when it was saved.
  await expect(page.getByText(/^Created /)).toBeVisible()
  const parameters = page.getByRole("region", { name: "Parameters" })
  await expect(parameters).toContainText("lookback")
  await expect(parameters).toContainText("12")
  // The chart loads apart: its picture waits for it, so that the page's picture holds it.
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-page")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-page-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page).toHaveURL("/runs")
  expect(errors).toEqual([])
})

test("a perpetual's run lists its fee's maker and taker rates, and its capital in its code", async ({
  loggedIn: page,
}) => {
  // The reviews of D-117: the Settings card's row of a crypto fee, and a currency without a sign.
  const seeded = await theSeededRun(page)
  const row = z.looseObject({ settings: z.looseObject({}) })
  await page.route(`**/v1/runs/${seeded.run_key}`, async (route) => {
    const answered = await route.fetch()
    const body = row.parse(await answered.json())
    await route.fulfill({
      response: answered,
      json: {
        ...body,
        currency: "USDT",
        fee: { kind: "crypto", maker_bps: "2", taker_bps: "5" },
        settings: {
          ...body.settings,
          instrument: "BTCUSDT-PERP",
          fee_table: "binance-default",
        },
      },
    })
  })

  await page.goto(`/runs/run?key=${seeded.run_key}`)

  const settings = page.getByTestId("run-settings")
  await expect(settings).toContainText(
    "Commissions and feesbinance-defaultMaker, taker2 bps, 5 bps"
  )
  await expect(settings).toContainText(
    `Capital${moneyText(seeded.settings.capital, "USDT")}`
  )
})

test("an address that names no run says so", async ({ loggedIn: page }) => {
  await page.goto("/runs/run")
  await expect(page.getByRole("alert")).toContainText("names no run")
  await page.goto(`/runs/run?key=${"e".repeat(64)}`)
  await expect(page.getByRole("alert")).toContainText("no such run")
})

test("the dialog shows what the data holds and what the run would read", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  const versions = strategies.parse(
    await (await page.request.get("/v1/strategies")).json()
  )
  const demo = versions.find((each) => each.name === "demo")
  if (demo === undefined) {
    throw new Error("Expected the seeded strategy demo, got none.")
  }
  const { csrf_token } = identity.parse(
    await (await page.request.get("/v1/me")).json()
  )
  const answer = estimated.parse(
    await (
      await page.request.post("/v1/runs/estimate", {
        data: { strategy_version_id: demo.versions[0].id },
        headers: { "X-CSRF-Token": csrf_token },
      })
    ).json()
  )

  const dialog = await openTheDialog(page)

  await expect(dialog.getByTestId("run-coverage")).toHaveText(
    `synthetic holds ES from ${answer.held.start} to ${answer.held.end}`
  )
  await expect(dialog.getByLabel("From", { exact: true })).toHaveValue(
    answer.held.start
  )
  await expect(dialog.getByLabel("To", { exact: true })).toHaveValue(
    answer.held.end
  )
  // The seed's ES fills on its trades alone, so the line leaves the bars out.
  expect(answer.bars).toBe(0)
  await expect(dialog.getByTestId("run-estimate")).toHaveText(
    `${answer.sessions} sessions, ${answer.ticks.toLocaleString("en-US")} ticks`
  )
  await expect(dialog.getByTestId("run-stress-note")).toHaveText(
    "Run with stress also runs it at 1 and at 2 more ticks of slippage"
  )
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await expect(dialog.getByLabel("Instrument")).toBeFocused()
  // Whole range stands level with the dates, and a parameter fills its column as a select does.
  const from = await boxOf(dialog.getByLabel("From", { exact: true }))
  const wholeRange = await boxOf(dialog.getByTestId("run-whole-range"))
  expect(wholeRange.y).toBeCloseTo(from.y, 0)
  const fidelity = await boxOf(dialog.getByLabel("Fidelity"))
  const lookback = await boxOf(dialog.getByLabel("lookback"))
  expect(lookback.width).toBeCloseTo(fidelity.width, 0)
  // The dates stand on the columns of the row above them.
  const instrument = await boxOf(dialog.getByLabel("Instrument"))
  expect(from.width).toBeCloseTo(instrument.width, 0)
  // At the window's full height the pinned foot covers no field.
  const foot = await boxOf(dialog.locator("footer"))
  expect(lookback.y + lookback.height).toBeLessThan(foot.y)
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await screenshot(page, "run-dialog", [], "window")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-dialog-light", [], "window")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // In a short window the fields scroll under what the run would read and its buttons.
  await page.setViewportSize({ width: 1280, height: 520 })
  await dialog.getByLabel("Contract").scrollIntoViewIfNeeded()
  await expect(dialog.getByTestId("run-estimate")).toBeInViewport({ ratio: 1 })
  await expect(dialog.getByTestId("run-launch")).toBeInViewport({ ratio: 1 })
  // A field the focus reaches stands clear of the foot, even one the window already shows.
  await page.setViewportSize({ width: 1280, height: 650 })
  await dialog.evaluate((content) => content.scrollTo(0, 0))
  await dialog.getByLabel("lookback").focus()
  const focused = await boxOf(dialog.getByLabel("lookback"))
  const pinned = await boxOf(dialog.locator("footer"))
  expect(focused.y + focused.height).toBeLessThanOrEqual(pinned.y)
  // A tall window keeps the dialog near its top, so that a long form gets its height.
  await page.setViewportSize({ width: 1280, height: 1000 })
  expect((await boxOf(dialog)).y).toBeLessThanOrEqual(32)
  await page.setViewportSize({ width: 1280, height: 800 })

  // Asked for more contrast, the scrim is solid.
  await page.emulateMedia({ reducedMotion: "reduce", contrast: "more" })
  const scrim = await page
    .locator('[data-slot="dialog-overlay"]')
    .evaluate((overlay) => getComputedStyle(overlay).backgroundColor)
  const ground = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor
  )
  expect(scrim).toBe(ground)
  await page.emulateMedia({
    reducedMotion: "reduce",
    contrast: "no-preference",
  })

  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await expect(page.getByTestId("run-backtest")).toBeFocused()
  expect(errors).toEqual([])
})

test("the dialog refuses a date the data does not hold, and a window without data", async ({
  loggedIn: page,
}) => {
  const dialog = await openTheDialog(page)
  const launch = dialog.getByTestId("run-launch")
  await expect(launch).toBeEnabled()

  await dialog.getByLabel("From", { exact: true }).fill("2026-03-01")
  await dialog.getByLabel("From", { exact: true }).blur()

  await expect(dialog).toContainText(
    "Choose a date from 2026-03-06 to 2026-03-09, the data this run reads."
  )
  await expect(dialog.getByLabel("From", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  await expect(launch).toBeDisabled()
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Choose dates the data holds"
  )

  await dialog.getByLabel("From", { exact: true }).fill("not a date")
  await dialog.getByLabel("From", { exact: true }).blur()
  await expect(dialog).toContainText("Type a date such as 2026-03-06.")
  await expect(launch).toBeDisabled()
  // That refusal is From's: To keeps its own date.
  await expect(dialog.getByLabel("To", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "false"
  )

  await dialog.getByTestId("run-whole-range").click()
  await expect(dialog.getByLabel("From", { exact: true })).toHaveValue(
    "2026-03-06"
  )
  await expect(launch).toBeEnabled()

  await dialog.getByLabel("From", { exact: true }).fill("2026-03-09")
  await dialog.getByLabel("From", { exact: true }).blur()
  await dialog.getByLabel("To", { exact: true }).fill("2026-03-06")
  await dialog.getByLabel("To", { exact: true }).blur()
  await expect(dialog).toContainText("Choose an end on or after 2026-03-09.")
  await expect(launch).toBeDisabled()
  // The field says it: a window that runs backwards is not sent for the server to refuse too.
  await expect(dialog.getByTestId("run-estimate-refusal")).toHaveCount(0)
  await dialog.getByTestId("run-whole-range").click()
  await expect(launch).toBeEnabled()

  await page.route("**/v1/runs/estimate", async (route) => {
    const real = await route.fetch()
    const body = z
      .object({})
      .passthrough()
      .parse(await real.json())
    await route.fulfill({ json: { ...body, sessions: 0, bars: 0, ticks: 0 } })
  })
  await dialog.getByLabel("To", { exact: true }).fill("2026-03-08")
  await dialog.getByLabel("To", { exact: true }).blur()
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "This window holds no data"
  )
  await expect(launch).toBeDisabled()
  await expect(dialog.getByTestId("run-stress")).toBeDisabled()
})

test("what the dialog holds outlives closing it, and a refusal of the data stands in it", async ({
  loggedIn: page,
}) => {
  const dialog = await openTheDialog(page)

  await dialog.getByLabel("lookback").fill("24")
  await dialog.getByLabel("Slippage on market orders, ticks").fill("3")
  await dialog.getByLabel("Slippage on market orders, ticks").blur()
  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await page.getByTestId("run-backtest").click()

  await expect(dialog.getByLabel("lookback")).toHaveValue("24")
  await dialog.getByLabel("lookback").fill("many")
  await page.keyboard.press("Escape")
  await page.getByTestId("run-backtest").click()
  await expect(dialog).toContainText("Type a whole number, such as 12.")
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Correct the parameter refused above"
  )
  await dialog.getByLabel("lookback").fill("24")
  await expect(
    dialog.getByLabel("Slippage on market orders, ticks")
  ).toHaveValue("3")

  await page.route("**/v1/runs/estimate", (route) =>
    route.fulfill(
      problemAnswer(
        400,
        "Expected a level at or coarser than 1m on 2026-03-06, for this test."
      )
    )
  )
  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()

  await expect(dialog.getByTestId("run-estimate-refusal")).toContainText(
    "Expected a level at or coarser than 1m"
  )
  await expect(dialog.getByTestId("run-launch")).toBeDisabled()
  await expect(dialog.getByLabel("From", { exact: true })).toBeVisible()
  // The refusal stands in the pinned foot, which would otherwise cover it.
  await expect(
    dialog.locator("footer").getByTestId("run-estimate-refusal")
  ).toBeVisible()

  // Opened again on the choice refused, its fields stand, so that it can be changed back.
  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await page.getByTestId("run-backtest").click()
  await expect(dialog.getByTestId("run-estimate-refusal")).toContainText(
    "Expected a level at or coarser than 1m"
  )
  await page.unroute("**/v1/runs/estimate")
  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "Auto" }).click()
  await expect(dialog.getByTestId("run-estimate-refusal")).toHaveCount(0)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
})

test("the dialog picks the data by provider and contract, and says when no fee table prices it", async ({
  loggedIn: page,
}) => {
  // The seed holds ES from one provider: a second is answered here, its data the first's.
  const asked: z.infer<typeof estimateAsked>[] = []
  let priced = true
  let refused: string | null = null
  let noDates = false
  await page.route("**/v1/runs/estimate", async (route) => {
    const request = estimateAsked.parse(route.request().postDataJSON())
    asked.push(request)
    const { provider, ...others } = request.settings
    if (provider !== undefined && provider === refused) {
      await route.fulfill(
        problemAnswer(400, `Expected a provider of ES, got ${provider}.`)
      )
      return
    }
    const real = await route.fetch({
      postData: JSON.stringify({ ...request, settings: others }),
    })
    const body = estimateAnswer.parse(await real.json())
    await route.fulfill({
      json: {
        ...body,
        providers: ["synthetic", "vendor"],
        ...(priced ? {} : { fee_tables: [] }),
        ...(noDates
          ? { held: null, window: null, sessions: 0, bars: 0, ticks: 0 }
          : {}),
        settings: {
          ...body.settings,
          provider: provider === undefined ? "synthetic" : provider,
        },
      },
    })
  })
  const dialog = await openTheDialog(page)

  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "ESH2026" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "synthetic holds ESH2026"
  )
  expect(asked.at(-1)?.settings.contract).toBe("ESH2026")
  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()
  await expect.poll(() => asked.at(-1)?.settings.fidelity).toBe("1m")

  await dialog.getByLabel("Data").click()
  await page.getByRole("option", { name: "vendor" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "vendor holds ES from"
  )
  expect(asked.at(-1)?.settings.provider).toBe("vendor")
  // Another provider holds other contracts and levels, so both choices go back.
  expect(asked.at(-1)?.settings.contract).toBeUndefined()
  expect(asked.at(-1)?.settings.fidelity).toBeUndefined()
  await expect(dialog.getByLabel("Contract")).toHaveText("Spliced")
  await expect(dialog.getByLabel("Fidelity")).toHaveText("Auto")

  // A provider refused stays chosen, so that the one before it can be chosen again.
  refused = "synthetic"
  await dialog.getByLabel("Data").click()
  await page.getByRole("option", { name: "synthetic" }).click()
  await expect(dialog.getByTestId("run-estimate-refusal")).toContainText(
    "Expected a provider of ES"
  )
  await expect(dialog.getByLabel("Data")).toHaveText("synthetic")
  await dialog.getByLabel("Data").click()
  await page.getByRole("option", { name: "vendor" }).click()
  await expect(dialog.getByTestId("run-estimate-refusal")).toHaveCount(0)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()

  // A provider whose data cannot make the series says so, and the form stays to choose again.
  noDates = true
  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "ESH2026" }).click()
  await expect(dialog.getByTestId("run-coverage")).toHaveText(
    "vendor cannot make ESH2026 in 5m bars from the data it holds. Choose other data."
  )
  await expect(dialog.getByTestId("run-launch")).toBeDisabled()
  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "Spliced" }).click()
  await expect(dialog.getByTestId("run-coverage")).toHaveText(
    "vendor cannot make ES in 5m bars from the data it holds. Choose one contract or other data."
  )
  noDates = false
  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "ESH2026" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "vendor holds ESH2026 from"
  )
  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "Spliced" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "vendor holds ES from"
  )

  priced = false
  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()

  // The design review of D-117: a fact, since nothing can be chosen.
  await expect(dialog.getByTestId("run-no-fee-table")).toHaveText(
    "FEAT has no commissions and fees for ES, so a run could not count its costs."
  )
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "No commissions and fees for ES"
  )
  await expect(dialog.getByTestId("run-launch")).toBeDisabled()
})

test("the dialog chooses the instrument a run trades, and reads that instrument's data", async ({
  loggedIn: page,
}) => {
  // D-114: the seed holds ES, which demo's code names, and MES and the perpetual beside it.
  const errors = consoleErrors(page)
  const asked: z.infer<typeof estimateAsked>[] = []
  await page.route("**/v1/runs/estimate", async (route) => {
    asked.push(estimateAsked.parse(route.request().postDataJSON()))
    await route.fallback()
  })
  const dialog = await openTheDialog(page)
  const written = dialog.getByText(
    "Version 1 of demo, written for ES in 5m bars"
  )
  await expect(written).toBeVisible()
  await expect(dialog.getByLabel("Instrument")).toHaveText("ES")
  expect(asked.at(-1)?.settings.instrument).toBeUndefined()

  await dialog.getByLabel("Contract").click()
  await page.getByRole("option", { name: "ESH2026" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "synthetic holds ESH2026"
  )
  await dialog.getByLabel("Instrument").click()
  await expect(page.getByRole("option")).toHaveText([
    "BTCUSDT-PERP",
    "ES",
    "MES",
  ])
  await page.getByRole("option", { name: "MES", exact: true }).click()

  // Another instrument has its own contracts, so the one chosen goes back to Spliced.
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "synthetic holds MES from"
  )
  expect(asked.at(-1)?.settings.instrument).toBe("MES")
  expect(asked.at(-1)?.settings.contract).toBeUndefined()
  await expect(dialog.getByLabel("Contract")).toHaveText("Spliced")
  await expect(written).toBeVisible()
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  // The choice outlives the dialog's closing, so the line beside Run says it.
  await expect(dialog.getByTestId("run-estimate")).toContainText(
    "Trades MES, not the code's ES: "
  )

  // A perpetual has no contract to choose, and the fee table follows it.
  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "BTCUSDT-PERP" }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "synthetic holds BTCUSDT-PERP from"
  )
  await expect(dialog.getByLabel("Contract")).toHaveCount(0)
  const fees = dialog.getByLabel("Commissions and fees")
  const crypto =
    "Maker 2 bps, taker 5 bps of each trade's value: maker for a limit order that rested on the book"
  await expect(fees).toHaveText("binance-default")
  await expect(dialog.getByTestId("run-fee-note")).toHaveText(crypto)
  // The line under the field is its description, so that a screen reader hears the charge.
  await expect(fees).toHaveAccessibleDescription(crypto)

  // The code's own instrument, chosen again: its estimate is the first one, still fresh, and the
  // run names it, so that a parameter of the code cannot trade another than the dialog shows.
  await dialog.getByLabel("Instrument").click()
  await page.getByRole("option", { name: "ES", exact: true }).click()
  await expect(dialog.getByTestId("run-coverage")).toContainText(
    "synthetic holds ES from"
  )
  // D-117: the commissions and fees name each table's charge on the run's last day, March 2026
  // paying the tables' first schedule, as the engine charges it (F-FEE-01).
  const futures =
    "$2.87 per contract per side: commission plus exchange, clearing, and NFA fees"
  await expect(fees).toHaveText("retail-default")
  await expect(dialog.getByTestId("run-fee-note")).toHaveText(futures)
  await expect(fees).toHaveAccessibleDescription(futures)
  await expect(dialog.getByLabel("Fidelity")).toHaveAccessibleDescription(
    /^Each date fills on/
  )
  await fees.click()
  await expect(page.getByRole("option")).toHaveText([
    "retail-default, $2.87 per contract per side",
    "prop-topstep, $1.89 per contract per side",
  ])
  await page.mouse.move(700, 36)
  await screenshot(page, "run-dialog-fees", [], "window")
  await page.keyboard.press("Escape")
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await expect(dialog.getByTestId("run-estimate")).not.toContainText("Trades")
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  const seeded = await theSeededRun(page)
  const sent: unknown[] = []
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { state: "saved", run_key: seeded.run_key } })
  })

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(`/runs/run?key=${seeded.run_key}`)
  expect(sent).toHaveLength(1)
  expect(estimateAsked.parse(sent[0]).settings.instrument).toBe("ES")
  expect(errors).toEqual([])
})

test("a press on Run while the estimate is read is kept, and sends the new date", async ({
  loggedIn: page,
}) => {
  // Pressing Run leaves the date's field, which asks a new estimate before the press ends.
  const seeded = await theSeededRun(page)
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  const sent: unknown[] = []
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { state: "saved", run_key: seeded.run_key } })
  })
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/runs/estimate", async (route) => {
    await released
    await route.fallback()
  })

  await dialog.getByLabel("To", { exact: true }).fill("2026-03-06")
  await dialog.getByTestId("run-launch").click()

  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Looking the run up"
  )
  expect(sent).toEqual([])
  release()
  await expect(page).toHaveURL(`/runs/run?key=${seeded.run_key}`)
  expect(sent).toHaveLength(1)
  expect(z.object({ end: z.string() }).parse(sent[0]).end).toBe("2026-03-06")
})

test("a press kept for the estimate is given up when the draft changes or the dialog closes", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  const sent: unknown[] = []
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { state: "saved", run_key: seeded.run_key } })
  })
  let release = () => {}
  let released = Promise.resolve()
  const holdEstimates = () => {
    released = new Promise<void>((resolve) => {
      release = resolve
    })
  }
  await page.route("**/v1/runs/estimate", async (route) => {
    await released
    await route.fallback()
  })

  holdEstimates()
  await dialog.getByLabel("To", { exact: true }).fill("2026-03-06")
  await dialog.getByTestId("run-launch").click()
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Looking the run up"
  )
  await dialog.getByLabel("lookback").fill("20")
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Reading your latest change"
  )
  release()
  await expect(dialog.getByTestId("run-waiting")).toHaveText("")
  expect(sent).toEqual([])

  // Back on dates already read, whose answer is cached: closing still gives the press up.
  holdEstimates()
  await dialog.getByLabel("To", { exact: true }).fill("2026-03-09")
  await dialog.getByTestId("run-launch").click()
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Looking the run up"
  )
  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  release()
  await page.waitForTimeout(500)
  expect(sent).toEqual([])
})

test("a press given up when its read fails stays given up after Try again", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  const sent: unknown[] = []
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { state: "saved", run_key: seeded.run_key } })
  })
  let failing = true
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/runs/estimate", async (route) => {
    if (!failing) {
      await route.fallback()
      return
    }
    await released
    await route.fulfill(
      problemAnswer(500, "The estimate failed, for this test.")
    )
  })

  await dialog.getByLabel("To", { exact: true }).fill("2026-03-06")
  await dialog.getByTestId("run-launch").click()
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Looking the run up"
  )
  release()
  const tryAgain = dialog.getByRole("button", { name: "Try again" })
  await expect(tryAgain).toBeVisible()
  failing = false
  await tryAgain.click()

  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await page.waitForTimeout(500)
  expect(sent).toEqual([])
  await expect(page).toHaveURL(/\/strategies\/strategy/)
})

test("a fidelity the data does not hold waits, and says so", async ({
  loggedIn: page,
}) => {
  // As after a choice from another instrument's list, made while its answer was read.
  await page.route("**/v1/runs/estimate", async (route) => {
    const asked = estimateAsked.parse(route.request().postDataJSON())
    if (asked.settings.fidelity !== "1m") {
      await route.fallback()
      return
    }
    const body = estimateAnswer.parse(await (await route.fetch()).json())
    await route.fulfill({ json: { ...body, levels: ["trades"] } })
  })
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()

  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()

  await expect(dialog.getByLabel("Fidelity")).toHaveText("Choose a level")
  await expect(dialog.getByTestId("run-fidelity-note")).toHaveText(
    "The data does not hold the level chosen"
  )
  await expect(dialog.getByTestId("run-waiting")).toHaveText(
    "Choose a fidelity the data holds"
  )
  await expect(dialog.getByTestId("run-launch")).toBeDisabled()

  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "Auto" }).click()
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
})

test("a launch that joins another version's run under way says which", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const row = aSubmittedRow(seeded, "job-of-the-other")
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    await route.fulfill({ status: 202, json: row })
  })
  await page.route("**/v1/runs/run-live", (route) =>
    route.fulfill({ json: row })
  )
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()

  await dialog.getByTestId("run-launch").click()

  await expect(page).toHaveURL(/\/runs\/run\?id=run-live/)
  await expect(page.getByTestId("run-found")).toHaveText(
    "FEAT followed this run under demo, version 1, whose code gives the same signals, rather than run it twice."
  )
})

test("ticks typed while an estimate is read stay, and the other side follows the fidelity", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const dialog = await openTheDialog(page)
  const sent: unknown[] = []
  await page.route(THE_LIST, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    sent.push(route.request().postDataJSON())
    await route.fulfill({ json: { state: "saved", run_key: seeded.run_key } })
  })
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/runs/estimate", async (route) => {
    await released
    const body = estimateAnswer.parse(await (await route.fetch()).json())
    await route.fulfill({
      json: {
        ...body,
        settings: { ...body.settings, slippage_ticks: { market: 0, stop: 0 } },
      },
    })
  })

  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()
  const market = dialog.getByLabel("Slippage on market orders, ticks")
  await market.fill("3")
  release()

  await expect(dialog.getByLabel("Slippage on stop orders, ticks")).toHaveValue(
    "0"
  )
  await expect(market).toHaveValue("3")
  await market.blur()
  await dialog.getByTestId("run-launch").click()
  await expect.poll(() => sent.length).toBe(1)
  expect(
    z
      .object({
        settings: z.object({
          slippage_ticks: z.object({ market: z.number(), stop: z.number() }),
        }),
      })
      .parse(sent[0]).settings.slippage_ticks
  ).toEqual({ market: 3, stop: 0 })
})

test("the dialog says the refusal of the last launch", async ({
  loggedIn: page,
}) => {
  await page.route(THE_LIST, (route) =>
    route.request().method() === "POST"
      ? route.fulfill(problemAnswer(400, "Expected a run this test refuses."))
      : route.fallback()
  )
  await page.route("**/v1/runs/stress", (route) =>
    route.fulfill(problemAnswer(400, "Expected a stress this test refuses."))
  )
  const dialog = await openTheDialog(page)

  await dialog.getByTestId("run-launch").click()
  await expect(dialog.getByTestId("run-refusal")).toHaveText(
    "Expected a run this test refuses."
  )

  await dialog.getByTestId("run-stress").click()
  await expect(dialog.getByTestId("run-refusal")).toHaveText(
    "Expected a stress this test refuses."
  )
})

test("an estimate the server cannot answer offers Try again, not another choice", async ({
  loggedIn: page,
}) => {
  const dialog = await openTheDialog(page)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  let failing = true
  await page.route("**/v1/runs/estimate", (route) =>
    failing
      ? route.fulfill(
          problemAnswer(500, "The server could not read the store.")
        )
      : route.fallback()
  )

  await dialog.getByLabel("Fidelity").click()
  await page.getByRole("option", { name: "1-minute bars" }).click()

  await expect(dialog.getByRole("alert")).toContainText(
    "The server could not read the store."
  )
  await expect(dialog.getByTestId("run-estimate-refusal")).toHaveCount(0)
  failing = false
  await dialog.getByRole("button", { name: "Try again" }).click()
  await expect(dialog.getByRole("alert")).toHaveCount(0)
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
})

test("a Cancel the server refuses says why in the row", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  const row = aSubmittedRow(seeded, "job-held")
  let ended = false
  await page.route("**/v1/jobs", (route) =>
    route.fulfill({
      json: [aJob("job-held", ended ? "failed" : "running", { progress: 40 })],
    })
  )
  await page.route("**/v1/streams/**", (route) => route.abort())
  await page.route(THE_LIST, (route) =>
    route.fulfill({ json: { runs: [row], next_cursor: null } })
  )
  await page.route("**/v1/runs/run-live/cancel", (route) =>
    route.fulfill(
      problemAnswer(409, "Expected a run under way, for this test.")
    )
  )

  await page.goto("/runs")
  await page.getByTestId("run-cancel").click()

  await expect(page.getByTestId("run-cancel-refusal")).toHaveText(
    "Expected a run under way, for this test."
  )
  await expect(page.getByTestId("run-cancel")).toBeEnabled()

  // Once the run has ended, no Cancel is left for the refusal to speak of.
  ended = true
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }))
  )
  await expect(page.getByTestId("run-status")).toHaveText("Failed")
  await expect(page.getByTestId("run-cancel-refusal")).toHaveCount(0)
})

test("a submission whose row gave way opens the run its job names", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  await page.route("**/v1/jobs/job-gone", (route) =>
    route.fulfill({
      json: aJob("job-gone", "succeeded", {
        kind: "backtest",
        result: { run_id: seeded.id, run_key: seeded.run_key },
      }),
    })
  )

  await page.goto("/runs/run?id=row-gone&job=job-gone")

  await expect(page).toHaveURL(`/runs/run?key=${seeded.run_key}`)
  await expect(page.getByTestId("run-cached")).toHaveText("Cached")
  const cached = await boxOf(page.getByTestId("run-cached"))
  const status = await boxOf(page.getByTestId("run-page-status"))
  expect(cached.height).toBeCloseTo(status.height, 0)
})

test("Home shows the newest runs with their verdict and three jobs, then a count", async ({
  loggedIn: page,
}) => {
  const seeded = await theSeededRun(page)
  await page.route("**/v1/jobs", (route) =>
    route.fulfill({
      json: ["a", "b", "c", "d", "e"].map((id) =>
        aJob(id, "running", { progress: 40, message: "Counted 24 of 60" })
      ),
    })
  )
  await page.route("**/v1/streams/**", (route) => route.abort())

  await page.goto("/")

  const recent = page.getByRole("region", { name: "Recent runs" })
  await expect(recent.getByTestId("recent-pnl").last()).toHaveText(
    moneyText(seeded.key_metrics.pnl, seeded.currency)
  )
  await expect(recent.getByTestId("recent-verdict").last()).toHaveText(
    /^Verdict: (Deploy-grade evidence|Refine|Abandon)$/
  )
  const card = page.getByRole("region", { name: "Running jobs" })
  await expect(card.getByTestId("running-job")).toHaveCount(3)
  await expect(card.getByTestId("running-jobs-more")).toHaveText(
    "2 more jobs in the jobs drawer"
  )
  await page.mouse.move(700, 36)
  await screenshot(page, "home-runs")

  await recent.getByTestId("recent-run").last().click()
  await expect(page).toHaveURL(`/runs/run?key=${seeded.run_key}`)
})
