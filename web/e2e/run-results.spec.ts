import type { Page, Route } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import {
  edgeText,
  figureText,
  moneyText,
  shareText,
} from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// A finished run's results of step 5.7 against the seeded server: every figure the page shows is
// the API's (Done means 1, its other half in python/tests/server/test_http_run_results.py), read
// here with the spec's own formatting. The seed's three sessions give few trades, so the fuller
// states, a fidelity check, red flags, figures that are none, are drawn from answers the spec
// gives.

const outcome = z.looseObject({
  trades: z.number(),
  wins: z.number(),
  pnl: z.string(),
})
const outcomes = z.record(z.string(), outcome)

const period = z.looseObject({
  fidelity: z.string(),
  trades: z.number(),
  pnl: z.string(),
  max_drawdown: z.string(),
})
const rerun = z.looseObject({
  outcome: period,
  trades_delta: z.number(),
  pnl_delta: z.string(),
  max_drawdown_delta: z.string(),
})
const fidelityCheck = z.discriminatedUnion("kind", [
  z.looseObject({
    kind: z.literal("checked"),
    baseline: period,
    at_one_second: rerun.nullable(),
    at_one_minute: rerun,
  }),
  z.looseObject({ kind: z.literal("refused") }),
])

const statistics = z.looseObject({
  currency: z.string(),
  capital: z.string(),
  pnl_share: z.number(),
  metrics: z.looseObject({
    pnl: z.string(),
    fidelity_check: fidelityCheck.nullable().optional(),
    trades: z.looseObject({
      trades: z.number(),
      wins: z.number(),
      losses: z.number(),
      win_rate: z.number().nullable(),
      profit_factor: z.number().nullable(),
      expectancy: z.number().nullable(),
      expectancy_r: z.number().nullable(),
    }),
    daily: z.looseObject({ days: z.number(), sharpe: z.number().nullable() }),
    drawdown: z.looseObject({
      max_drawdown: z.string(),
      max_drawdown_share: z.number(),
      peak: z.string().nullable(),
      trough: z.string().nullable(),
      longest_drawdown_days: z.number(),
    }),
    breakdowns: z.object({
      exit_reason: outcomes,
      hour: outcomes,
      weekday: outcomes,
      year: outcomes,
      fidelity: outcomes,
    }),
    robustness: z.looseObject({
      total_score: z.number(),
      verdict: z.string(),
      fragile_to_slippage: z.boolean(),
      pnl_at_plus_one_tick: z.string(),
      dimensions: z.array(
        z.looseObject({
          name: z.string(),
          score: z.number(),
          max_score: z.number(),
        })
      ),
      red_flags: z.array(
        z.looseObject({ severity: z.string(), message: z.string() })
      ),
    }),
  }),
})

const equity = z.object({
  capital: z.number(),
  time: z.array(z.number()),
  equity: z.array(z.number()),
  drawdown: z.array(z.number()),
})

const histogram = z.object({
  lower: z.array(z.number()),
  upper: z.array(z.number()),
  trades: z.array(z.number()),
})

const distributions = z.object({
  pnl: histogram,
  r_multiple: histogram,
  trades_without_r_multiple: z.number(),
  mae_ticks: histogram,
  mfe_ticks: histogram,
  holding_minutes: histogram,
})

const listed = z.object({ runs: z.array(z.object({ run_key: z.string() })) })

const VERDICTS: Readonly<Record<string, string>> = {
  deploy_grade_evidence: "Deploy-grade evidence",
  refine: "Refine",
  abandon: "Abandon",
}

const HISTOGRAMS = [
  "pnl",
  "r_multiple",
  "mae_ticks",
  "mfe_ticks",
  "holding_minutes",
] as const

async function theSeededKey(page: Page): Promise<string> {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const seeded = listed.parse(await answer.json()).runs.at(-1)
  if (seeded === undefined) {
    throw new Error("Expected the seed's saved run of demo, got none.")
  }
  return seeded.run_key
}

async function resultsOf(page: Page, key: string) {
  const [stats, curve, histograms] = await Promise.all([
    page.request.get(`/v1/runs/${key}/stats`),
    page.request.get(`/v1/runs/${key}/equity`),
    page.request.get(`/v1/runs/${key}/distribution`),
  ])
  return {
    stats: statistics.parse(await stats.json()),
    curve: equity.parse(await curve.json()),
    histograms: distributions.parse(await histograms.json()),
  }
}

/** A figure as the page writes it, or None where the API gives none. */
function ratioText(value: number | null): string {
  return value === null ? "None" : figureText(value)
}

/** A change of a count, with its sign above zero. */
function signedCount(change: number): string {
  return change > 0 ? `+${change}` : String(change)
}

/** A change of money as the page writes it, with its sign above zero. */
function signedMoney(change: string): string {
  return Number(change) > 0 ? `+${moneyText(change)}` : moneyText(change)
}

/** What the page's bars say of each bin, its range and its count. */
function binWords(bins: z.infer<typeof histogram>): readonly string[] {
  return bins.trades.map((count, at) => {
    const noun = count === 1 ? "trade" : "trades"
    return `${edgeText(bins.lower[at])} to ${edgeText(bins.upper[at])}: ${count} ${noun}`
  })
}

/** Answer the run's three results from `change`d copies of what the server answers. */
async function withAnswers(
  page: Page,
  key: string,
  change: (body: Record<string, unknown>, result: string) => void
) {
  await page.route(
    (url) =>
      url.pathname.startsWith(`/v1/runs/${key}/`) &&
      !url.pathname.endsWith("/cancel"),
    async (route: Route) => {
      const answered = await route.fetch()
      const body = z
        .record(z.string(), z.unknown())
        .parse(await answered.json())
      const result = new URL(route.request().url()).pathname.split("/").at(-1)
      change(body, result === undefined ? "" : result)
      await route.fulfill({ response: answered, json: body })
    }
  )
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" })
})

test("every figure of a finished run's page is the API's", async ({
  loggedIn: page,
}) => {
  // Done means 1: DOM equals API.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { stats, curve, histograms } = await resultsOf(page, key)
  const { metrics } = stats
  const { trades, drawdown, daily, robustness } = metrics

  await page.goto(`/runs/run?key=${key}`)

  const kpi = (id: string) => page.getByTestId(`kpi-${id}`)
  await expect(kpi("pnl")).toContainText(moneyText(metrics.pnl))
  await expect(kpi("pnl")).toContainText(`Net P&L, ${stats.currency}`)
  await expect(kpi("pnl")).toContainText(
    `${shareText(stats.pnl_share)} of the capital`
  )
  await expect(kpi("profit-factor")).toContainText(
    ratioText(trades.profit_factor)
  )
  await expect(kpi("expectancy")).toContainText(
    trades.expectancy_r === null
      ? "None"
      : `${figureText(trades.expectancy_r)} R`
  )
  if (trades.expectancy !== null) {
    await expect(kpi("expectancy")).toContainText(
      `${figureText(trades.expectancy)} a trade`
    )
  }
  await expect(kpi("win-rate")).toContainText(
    trades.win_rate === null ? "None" : shareText(trades.win_rate)
  )
  await expect(kpi("win-rate")).toContainText(
    `${trades.wins} of ${trades.trades}`
  )
  await expect(kpi("drawdown")).toContainText(moneyText(drawdown.max_drawdown))
  await expect(kpi("drawdown")).toContainText(
    `${shareText(drawdown.max_drawdown_share)} of the capital`
  )
  await expect(kpi("sharpe")).toContainText(ratioText(daily.sharpe))
  await expect(kpi("trades")).toContainText(String(trades.trades))
  await expect(kpi("trades")).toContainText(`${trades.wins} win`)
  for (const [level, group] of Object.entries(metrics.breakdowns.fidelity)) {
    await expect(
      kpi("fidelity").getByTestId(`kpi-fidelity-${level}`)
    ).toHaveText(new RegExp(`${group.trades}$`))
  }

  const card = page.getByRole("region", { name: "Robustness" })
  await expect(card.getByTestId("robustness-total")).toHaveText(
    `${robustness.total_score} of 100`
  )
  await expect(card.getByTestId("robustness-verdict")).toHaveText(
    `Verdict: ${VERDICTS[robustness.verdict]}`
  )
  await expect(card.getByTestId("robustness-fragile")).toHaveCount(
    robustness.fragile_to_slippage ? 1 : 0
  )
  await expect(card.getByTestId("robustness-score")).toHaveText(
    robustness.dimensions.map((each) => `${each.score} of ${each.max_score}`)
  )
  await expect(card.getByTestId("robustness-sample")).toContainText(
    String(trades.trades)
  )
  await expect(card.getByTestId("robustness-plus-tick")).toContainText(
    moneyText(robustness.pnl_at_plus_one_tick)
  )
  await expect(card.getByTestId("robustness-flag")).toHaveText(
    robustness.red_flags.map(
      (flag) => new RegExp(flag.message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    )
  )

  await expect(page.getByTestId("equity-figure")).toHaveText(
    figureText(curve.equity[curve.equity.length - 1])
  )
  await expect(page.getByTestId("equity-drawdown")).toHaveText(
    figureText(curve.drawdown[curve.drawdown.length - 1])
  )

  for (const [table, groups] of Object.entries(metrics.breakdowns)) {
    const rows = page
      .getByTestId(`breakdown-${table}`)
      .getByTestId("breakdown-row")
    await expect(rows).toHaveCount(Object.keys(groups).length)
    for (const [at, group] of Object.values(groups).entries()) {
      const cells = rows.nth(at).getByRole("cell")
      await expect(cells.nth(1)).toHaveText(String(group.trades))
      await expect(cells.nth(2)).toHaveText(String(group.wins))
      await expect(cells.nth(3)).toHaveText(moneyText(group.pnl))
    }
  }

  await expect(page.getByTestId("equity-spell")).toHaveText(
    `Deepest fall from ${drawdown.peak} to ${drawdown.trough}. Longest spell under a peak: ${drawdown.longest_drawdown_days} ${drawdown.longest_drawdown_days === 1 ? "day" : "days"}.`
  )

  const check = metrics.fidelity_check
  if (check?.kind !== "checked") {
    throw new Error("Expected the seeded run's fidelity check, got none.")
  }
  const checkRows = page.getByTestId("fidelity-check").getByRole("row")
  const baselineCells = checkRows.nth(1).getByRole("cell")
  await expect(baselineCells.nth(1)).toHaveText(String(check.baseline.trades))
  await expect(baselineCells.nth(3)).toHaveText(moneyText(check.baseline.pnl))
  await expect(baselineCells.nth(5)).toHaveText(
    moneyText(check.baseline.max_drawdown)
  )
  const reruns = [check.at_one_second, check.at_one_minute].flatMap((each) =>
    each === null ? [] : [each]
  )
  await expect(checkRows).toHaveCount(2 + reruns.length)
  for (const [at, each] of reruns.entries()) {
    const cells = checkRows.nth(2 + at).getByRole("cell")
    await expect(cells.nth(1)).toHaveText(String(each.outcome.trades))
    await expect(cells.nth(2)).toHaveText(signedCount(each.trades_delta))
    await expect(cells.nth(3)).toHaveText(moneyText(each.outcome.pnl))
    await expect(cells.nth(4)).toHaveText(signedMoney(each.pnl_delta))
    await expect(cells.nth(5)).toHaveText(moneyText(each.outcome.max_drawdown))
    await expect(cells.nth(6)).toHaveText(signedMoney(each.max_drawdown_delta))
  }

  for (const name of HISTOGRAMS) {
    const bars = page.getByTestId(`histogram-${name}`).getByRole("listitem")
    const words = await bars.evaluateAll((each) =>
      each.map((bar) => bar.getAttribute("aria-label"))
    )
    expect(words, name).toEqual(binWords(histograms[name]))
  }
  await expect(page.getByTestId("equity-chart")).toBeVisible()
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-results")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-results-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("a finished run's page reads in both themes, under the motion floor", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("key-figures")).toBeVisible()
  await expect(page.getByTestId("histogram-pnl")).toBeVisible()
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
})

test("the results stand first, with Parameters and Settings at the foot", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)

  const figures = page.getByTestId("key-figures")
  await expect(figures).toBeVisible()
  await expect(page.getByTestId("histogram-pnl")).toBeVisible()
  const status = await page.getByTestId("run-page-status").boundingBox()
  const firstFigure = await figures.boundingBox()
  const settings = await page.getByTestId("run-settings").boundingBox()
  const lastHistogram = await page
    .getByTestId("histogram-holding_minutes")
    .boundingBox()
  if (
    status === null ||
    firstFigure === null ||
    settings === null ||
    lastHistogram === null
  ) {
    throw new Error(
      "Expected the page's sections drawn, got one without a box."
    )
  }
  expect(status.y).toBeLessThan(firstFigure.y)
  expect(firstFigure.y).toBeLessThan(800)
  expect(lastHistogram.y).toBeLessThan(settings.y)
  await expect(page.getByText("will appear here")).toHaveCount(0)
})

test("the arrow keys step the equity's readout a decision at a time", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { curve } = await resultsOf(page, key)
  const last = curve.equity.length - 1
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  const figure = page.getByTestId("equity-figure")
  const drawdown = page.getByTestId("equity-drawdown")
  await expect(chart.locator("canvas").first()).toBeVisible()

  await chart.focus()
  await page.keyboard.press("Home")
  await expect(figure).toHaveText(figureText(curve.equity[0]))
  await expect(drawdown).toHaveText(figureText(curve.drawdown[0]))
  await page.keyboard.press("ArrowRight")
  await expect(figure).toHaveText(figureText(curve.equity[1]))
  await page.keyboard.press("ArrowLeft")
  await expect(figure).toHaveText(figureText(curve.equity[0]))
  await page.keyboard.press("End")
  await expect(figure).toHaveText(figureText(curve.equity[last]))
  await page.keyboard.press("ArrowLeft")
  await expect(figure).toHaveText(figureText(curve.equity[last - 1]))
  await page.keyboard.press("Escape")
  await expect(figure).toHaveText(figureText(curve.equity[last]))
  expect(errors).toEqual([])
})

test("the pointer on the chart moves the readout, and leaving it gives the last decision back", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { curve } = await resultsOf(page, key)
  const last = figureText(curve.equity[curve.equity.length - 1])
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.scrollIntoViewIfNeeded()
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart drawn, got no box.")
  }

  const atRest = await page.getByTestId("equity-time").innerText()

  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3)
  await expect(page.getByTestId("equity-time")).not.toHaveText(atRest)
  await page.mouse.move(box.x + box.width / 2, box.y - 60)

  await expect(page.getByTestId("equity-figure")).toHaveText(last)
})

test("the page draws what the seed cannot: a check, flags, figures that are none", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { stats: real } = await resultsOf(page, key)
  const run = {
    fidelity: "1m",
    eras: [],
    trades: 21,
    pnl: "1190.500000",
    max_drawdown: "845.250000",
  }
  const hours = Object.fromEntries(
    Array.from({ length: 24 }, (_, hour) => [
      String(hour),
      { trades: hour + 1, wins: hour, pnl: `${(hour - 10) * 25}.500000` },
    ])
  )
  await withAnswers(page, key, (body, result) => {
    if (result !== "stats") {
      return
    }
    body.metrics = {
      ...real.metrics,
      trades: {
        ...real.metrics.trades,
        profit_factor: null,
        expectancy_r: null,
      },
      daily: { ...real.metrics.daily, sharpe: null },
      breakdowns: { ...real.metrics.breakdowns, hour: hours },
      robustness: {
        ...real.metrics.robustness,
        fragile_to_slippage: true,
        red_flags: [
          { id: "small_sample", severity: "high", message: "Only 3 trades." },
          {
            id: "short_test_period",
            severity: "medium",
            message: "Only 1 years tested.",
          },
        ],
      },
      fidelity_check: {
        kind: "checked",
        first: "2026-03-05",
        last: "2026-03-09",
        baseline: { ...run, fidelity: "trades", trades: 22 },
        at_one_second: null,
        at_one_minute: {
          outcome: run,
          trades_delta: -1,
          pnl_delta: "-59.500000",
          max_drawdown_delta: "12.750000",
          fill_prices: [],
          unmatched_trades: 1,
          extra_trades: 0,
        },
      },
    }
  })

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("kpi-profit-factor")).toContainText("None")
  await expect(page.getByTestId("kpi-profit-factor")).toContainText(
    "No losing trade"
  )
  await expect(page.getByTestId("kpi-expectancy")).toContainText("None")
  await expect(page.getByTestId("kpi-expectancy")).toContainText(
    "No trade with a stop"
  )
  await expect(page.getByTestId("kpi-sharpe")).toContainText("None")
  await expect(page.getByTestId("robustness-fragile")).toHaveText(
    "Fragile to slippage"
  )
  await expect(page.getByTestId("robustness-flag")).toHaveCount(2)
  await expect(page.getByTestId("robustness-flag").first()).toContainText(
    "High"
  )
  const check = page.getByTestId("fidelity-check")
  await expect(check.getByRole("row")).toHaveCount(3)
  await expect(check).toContainText("-59.50")
  await expect(check).toContainText("+12.75")
  await expect(
    page.getByTestId("breakdown-hour").getByTestId("breakdown-row")
  ).toHaveCount(24)
  await expect(page.getByTestId("breakdown-hour")).toContainText("09:00")
  await expect(page.getByTestId("histogram-pnl")).toBeVisible()
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-results-full")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("a check the engine refused says why", async ({ loggedIn: page }) => {
  const key = await theSeededKey(page)
  const { stats: real } = await resultsOf(page, key)
  await withAnswers(page, key, (body, result) => {
    if (result === "stats") {
      body.metrics = {
        ...real.metrics,
        fidelity_check: {
          kind: "refused",
          first: "2026-03-05",
          last: "2026-03-09",
          fidelity: "1s",
          refused: "A trade date holds no level at or coarser than it.",
        },
      }
    }
  })

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("fidelity-check")).toContainText(
    "A trade date holds no level at or coarser than it."
  )
})

test("a run another engine saved keeps its page and says why it has no results", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const refusal =
    "Expected a run of engine version 9, got one of version 8: run it again with this engine."
  await page.route(`**/v1/runs/${key}/stats`, (route) =>
    route.fulfill(problemAnswer(409, refusal))
  )

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("run-results-refused")).toHaveText(refusal)
  await expect(page.getByTestId("run-page-status")).toHaveText("Succeeded")
  await expect(page.getByTestId("run-settings")).toBeVisible()
  await expect(page.getByTestId("key-figures")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0)
  await page.mouse.move(700, 36)
  await screenshot(page, "run-results-refused")
  expect(errors.filter((each) => !each.includes("409"))).toEqual([])
})

test("a section that cannot load fails alone and offers Try again", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  let refuse = true
  await page.route(`**/v1/runs/${key}/distribution`, async (route) => {
    if (refuse) {
      await route.fulfill(problemAnswer(500, "The server failed."))
      return
    }
    await route.continue()
  })

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Distributions" })
  await expect(card).toContainText("The server failed.")
  await expect(page.getByTestId("key-figures")).toBeVisible()
  await expect(page.getByTestId("equity-figure")).toBeVisible()
  refuse = false
  await card.getByRole("button", { name: "Try again" }).click()
  await expect(page.getByTestId("histogram-pnl")).toBeVisible()
})

test("a run with no trades says so in place of its figures", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { stats: real } = await resultsOf(page, key)
  const empty = { lower: [], upper: [], trades: [] }
  await withAnswers(page, key, (body, result) => {
    if (result === "distribution") {
      Object.assign(body, {
        pnl: empty,
        r_multiple: empty,
        mae_ticks: empty,
        mfe_ticks: empty,
        holding_minutes: empty,
        trades_without_r_multiple: 0,
      })
    }
    if (result === "stats") {
      body.metrics = {
        ...real.metrics,
        pnl: "0.000000",
        trades: {
          trades: 0,
          wins: 0,
          losses: 0,
          win_rate: null,
          profit_factor: null,
          expectancy: null,
          expectancy_ticks: null,
          expectancy_r: null,
          average_win: null,
          average_loss: null,
          mae_mfe_efficiency: null,
        },
        breakdowns: {
          exit_reason: {},
          hour: {},
          weekday: {},
          year: {},
          fidelity: {},
        },
      }
    }
  })

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("kpi-win-rate")).toContainText("None")
  await expect(page.getByTestId("kpi-win-rate")).toContainText("No trades")
  await expect(page.getByTestId("kpi-fidelity")).toContainText("None")
  await expect(page.getByTestId("breakdowns-empty")).toBeVisible()
  await expect(page.getByTestId("distributions-empty")).toBeVisible()
  expect(errors).toEqual([])
})
