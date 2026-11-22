import type { Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
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

// The Runs list, the run page, the Run backtest dialog, and Home's cards of step 5.6, against the
// seeded server, reading its one saved run and saving none: the specs that launch runs stand in
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

/** A figure as the page writes the API's decimal text. */
function moneyText(text: string): string {
  const [whole, fraction] = text.split(".")
  const sign = whole.startsWith("-") ? "-" : ""
  const digits = whole.replace("-", "").replace(/\B(?=(\d{3})+$)/g, ",")
  return `${sign}${digits}.${fraction.replace(/0+$/, "").padEnd(2, "0")}`
}

async function openTheDialog(page: Page) {
  await page.goto("/strategies/strategy?name=demo")
  await page.getByTestId("run-backtest").click()
  const dialog = page.getByRole("dialog", { name: "Run backtest" })
  await expect(dialog.getByTestId("run-coverage")).toBeVisible()
  return dialog
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
    },
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
  await expect(row.getByTestId("run-pnl")).toHaveText(
    moneyText(seeded.key_metrics.pnl)
  )
  await expect(row.getByTestId("run-trades")).toHaveText(
    String(seeded.key_metrics.trades)
  )
  await expect(row.getByTestId("run-drawdown")).toHaveText(
    moneyText(seeded.key_metrics.max_drawdown)
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
  await expect(settings).toContainText(seeded.settings.fee_table)
  const parameters = page.getByRole("region", { name: "Parameters" })
  await expect(parameters).toContainText("lookback")
  await expect(parameters).toContainText("12")
  await page.mouse.move(700, 36)
  await screenshot(page, "run-page")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-page-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page).toHaveURL("/runs")
  expect(errors).toEqual([])
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
  await expect(dialog.getByTestId("run-estimate")).toHaveText(
    `${answer.sessions} sessions, ${answer.bars.toLocaleString("en-US")} bars, ${answer.ticks.toLocaleString("en-US")} ticks`
  )
  await expect(dialog.getByTestId("run-launch")).toBeEnabled()
  await expect(dialog.getByLabel("Contract")).toBeFocused()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await screenshot(page, "run-dialog")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-dialog-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

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
    moneyText(seeded.key_metrics.pnl)
  )
  await expect(recent.getByTestId("recent-verdict").last()).toHaveText(
    /Deploy-grade evidence|Refine|Abandon/
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
