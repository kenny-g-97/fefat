import type { Page, Route } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import {
  edgeMoney,
  edgeText,
  figureMoney,
  figureText,
  moneyText,
  shareText,
} from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

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

/** The run's three results, and how the equity's readout writes an amount of its currency. */
async function resultsOf(page: Page, key: string) {
  const [stats, curve, histograms] = await Promise.all([
    page.request.get(`/v1/runs/${key}/stats`),
    page.request.get(`/v1/runs/${key}/equity`),
    page.request.get(`/v1/runs/${key}/distribution`),
  ])
  const read = statistics.parse(await stats.json())
  return {
    stats: read,
    curve: equity.parse(await curve.json()),
    histograms: distributions.parse(await histograms.json()),
    readout: (amount: number) => figureMoney(amount, read.currency),
  }
}

/** A figure as the page writes it, or None where the API gives none. */
function ratioText(value: number | null): string {
  return value === null ? "None" : figureText(value)
}

/** A count with its noun, as the page writes it. */
function countText(count: number, noun: string, many = `${noun}s`): string {
  return `${count} ${count === 1 ? noun : many}`
}

/** A word of the API in sentence case, written here apart from the app. */
function wordText(word: string): string {
  const spaced = word.replaceAll("_", " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A fidelity as the page names it. */
function levelText(level: string): string {
  const named: Readonly<Record<string, string>> = {
    trades: "Trades",
    tbbo: "TBBO",
    "1s": "1-second bars",
    "1m": "1-minute bars",
  }
  return named[level]
}

/** A decision's instant in the browser's zone, as the readout writes it. */
function instantText(second: number): string {
  const at = new Date(second * 1000)
  const two = (value: number) => String(value).padStart(2, "0")
  const day = `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())}`
  return `${day} ${two(at.getHours())}:${two(at.getMinutes())}`
}

/** What each breakdown names its rows by, from the API's keys. */
const ROW_NAMES: Readonly<Record<string, (key: string) => string>> = {
  exit_reason: wordText,
  weekday: wordText,
  hour: (hour) => `${hour.padStart(2, "0")}:00`,
  year: (year) => year,
  fidelity: levelText,
}

/** What the chart's canvases hold now, to compare two moments of it. */
function chartPictures(page: Page): Promise<readonly string[]> {
  return page
    .getByTestId("equity-chart")
    .locator("canvas")
    .evaluateAll((canvases) =>
      canvases.map((canvas) =>
        canvas instanceof HTMLCanvasElement ? canvas.toDataURL() : ""
      )
    )
}

/** More pixels than a repaint moves at the end of a line, fewer than a crosshair covers. */
const FEW_PIXELS = 32

/** How many pixels differ between two pictures of the chart's canvas. */
function differingPixels(
  page: Page,
  one: readonly string[],
  other: readonly string[]
): Promise<number> {
  return page.evaluate(
    async ([first, second]) => {
      const pixels = async (source: string) => {
        const image = new Image()
        image.src = source
        await image.decode()
        const canvas = document.createElement("canvas")
        canvas.width = image.width
        canvas.height = image.height
        const context = canvas.getContext("2d")
        if (context === null) {
          throw new Error("Expected a 2D canvas to compare on, got none.")
        }
        context.drawImage(image, 0, 0)
        return context.getImageData(0, 0, image.width, image.height).data
      }
      const [a, b] = [await pixels(first), await pixels(second)]
      let differing = 0
      for (let at = 0; at < a.length; at += 4) {
        const same =
          a[at] === b[at] && a[at + 1] === b[at + 1] && a[at + 2] === b[at + 2]
        differing += same ? 0 : 1
      }
      return differing
    },
    [one[0], other[0]]
  )
}

/** A change of a count, with its sign above zero. */
function signedCount(change: number): string {
  return change > 0 ? `+${change}` : String(change)
}

/** A change of money in `currency` as the page writes it, with its sign above zero. */
function signedMoney(change: string, currency: string): string {
  const written = moneyText(change, currency)
  return Number(change) > 0 ? `+${written}` : written
}

/** What the page's bars say of each bin, its range, each edge written by `edge`, and its count. */
function binWords(
  bins: z.infer<typeof histogram>,
  edge: (value: number) => string
): readonly string[] {
  return bins.trades.map((count, at) => {
    const noun = count === 1 ? "trade" : "trades"
    return `${edge(bins.lower[at])} to ${edge(bins.upper[at])}: ${count} ${noun}`
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
  const { stats, curve, histograms, readout } = await resultsOf(page, key)
  const { metrics, currency } = stats
  const { trades, drawdown, daily, robustness } = metrics
  const money = (text: string) => moneyText(text, currency)

  await page.goto(`/runs/run?key=${key}`)

  // D-117: every cash value carries its currency's sign, and no label names the currency.
  const kpi = (id: string) => page.getByTestId(`kpi-${id}`)
  await expect(kpi("pnl")).toContainText(money(metrics.pnl))
  await expect(kpi("pnl")).toContainText("Net P&L")
  await expect(kpi("pnl")).not.toContainText(currency)
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
      `${readout(trades.expectancy)} a trade`
    )
  }
  await expect(kpi("win-rate")).toContainText(
    trades.win_rate === null ? "None" : shareText(trades.win_rate)
  )
  await expect(kpi("win-rate")).toContainText(
    `${trades.wins} of ${trades.trades}`
  )
  await expect(kpi("drawdown")).toContainText(money(drawdown.max_drawdown))
  await expect(kpi("drawdown")).toContainText(
    `${shareText(drawdown.max_drawdown_share)} of the capital`
  )
  await expect(kpi("sharpe")).toContainText(ratioText(daily.sharpe))
  await expect(kpi("sharpe")).toContainText(
    `Over ${countText(daily.days, "day")}`
  )
  await expect(kpi("trades")).toContainText(String(trades.trades))
  await expect(kpi("trades")).toContainText(
    `${countText(trades.wins, "win")}, ${countText(trades.losses, "loss", "losses")}`
  )
  for (const [level, group] of Object.entries(metrics.breakdowns.fidelity)) {
    await expect(
      kpi("fidelity").getByTestId(`kpi-fidelity-${level}`)
    ).toHaveText(`${levelText(level)}${group.trades}`)
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
  await expect(card.getByRole("meter")).toHaveCount(5)
  for (const [at, each] of robustness.dimensions.entries()) {
    await expect(card.getByRole("meter").nth(at)).toHaveAccessibleName(
      wordText(each.name)
    )
    await expect(card.getByRole("meter").nth(at)).toHaveAttribute(
      "aria-valuenow",
      String(each.score)
    )
  }
  await expect(card.getByTestId("robustness-sample")).toContainText(
    countText(trades.trades, "trade")
  )
  await expect(card.getByTestId("robustness-plus-tick")).toContainText(
    money(robustness.pnl_at_plus_one_tick)
  )
  await expect(card.getByTestId("robustness-flag")).toHaveText(
    robustness.red_flags.map(
      (flag) => new RegExp(flag.message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    )
  )

  await expect(page.getByTestId("equity-figure")).toHaveText(
    readout(curve.equity[curve.equity.length - 1])
  )
  await expect(page.getByTestId("equity-drawdown")).toHaveText(
    readout(curve.drawdown[curve.drawdown.length - 1])
  )
  await expect(page.getByTestId("equity-time")).toHaveText(
    instantText(curve.time[curve.time.length - 1])
  )

  for (const [table, groups] of Object.entries(metrics.breakdowns)) {
    const rows = page
      .getByTestId(`breakdown-${table}`)
      .getByTestId("breakdown-row")
    await expect(rows).toHaveCount(Object.keys(groups).length)
    for (const [at, [name, group]] of Object.entries(groups).entries()) {
      const cells = rows.nth(at).getByRole("cell")
      await expect(cells.nth(0)).toHaveText(ROW_NAMES[table](name))
      await expect(cells.nth(1)).toHaveText(String(group.trades))
      await expect(cells.nth(2)).toHaveText(String(group.wins))
      await expect(cells.nth(3)).toHaveText(money(group.pnl))
    }
  }

  await expect(page.getByTestId("equity-spell")).toHaveText(
    `Deepest fall from ${drawdown.peak} to ${drawdown.trough}. Longest spell under a peak: ${drawdown.longest_drawdown_days} ${drawdown.longest_drawdown_days === 1 ? "day" : "days"}.`
  )

  const check = metrics.fidelity_check
  if (check?.kind !== "checked") {
    throw new Error("Expected the seeded run's fidelity check, got none.")
  }
  await expect(
    page.getByRole("region", { name: "Fidelity check" })
  ).toContainText(`From ${check.first} to ${check.last}, each run from flat`)
  const checkRows = page.getByTestId("fidelity-check").getByRole("row")
  const baselineCells = checkRows.nth(1).getByRole("cell")
  await expect(baselineCells.nth(0)).toHaveText(
    `Baseline, ${levelText(check.baseline.fidelity)}`
  )
  await expect(baselineCells.nth(1)).toHaveText(String(check.baseline.trades))
  await expect(baselineCells.nth(3)).toHaveText(money(check.baseline.pnl))
  await expect(baselineCells.nth(5)).toHaveText(
    money(check.baseline.max_drawdown)
  )
  const reruns = [check.at_one_second, check.at_one_minute].flatMap((each) =>
    each === null ? [] : [each]
  )
  await expect(checkRows).toHaveCount(2 + reruns.length)
  for (const [at, each] of reruns.entries()) {
    const cells = checkRows.nth(2 + at).getByRole("cell")
    await expect(cells.nth(0)).toHaveText(
      `At ${levelText(each.outcome.fidelity)}`
    )
    await expect(cells.nth(1)).toHaveText(String(each.outcome.trades))
    await expect(cells.nth(2)).toHaveText(signedCount(each.trades_delta))
    await expect(cells.nth(3)).toHaveText(money(each.outcome.pnl))
    await expect(cells.nth(4)).toHaveText(signedMoney(each.pnl_delta, currency))
    await expect(cells.nth(5)).toHaveText(money(each.outcome.max_drawdown))
    await expect(cells.nth(6)).toHaveText(
      signedMoney(each.max_drawdown_delta, currency)
    )
  }

  for (const name of HISTOGRAMS) {
    const bars = page.getByTestId(`histogram-${name}`).getByRole("listitem")
    const words = await bars.evaluateAll((each) =>
      each.map((bar) => bar.getAttribute("aria-label"))
    )
    const edge =
      name === "pnl" ? (value: number) => edgeMoney(value, currency) : edgeText
    expect(words, name).toEqual(binWords(histograms[name], edge))
    const { lower, upper } = histograms[name]
    const axis = page.getByTestId(`histogram-${name}`).locator("p").last()
    await expect(axis).toContainText(edge(lower[0]))
    await expect(axis).toContainText(edge(upper[upper.length - 1]))
  }
  const crossesZero =
    histograms.pnl.lower[0] < 0 &&
    histograms.pnl.upper[histograms.pnl.upper.length - 1] > 0
  await expect(
    page.getByTestId("histogram-pnl").getByTestId("histogram-zero")
  ).toHaveCount(crossesZero ? 1 : 0)
  // The reviews of D-117: the measure in its caption without the currency, and its zero as money.
  await expect(
    page.getByTestId("histogram-pnl").locator("figcaption")
  ).toHaveText("Net P&L a trade")
  await expect(
    page.getByTestId("histogram-pnl").getByTestId("histogram-zero-label")
  ).toHaveText(edgeMoney(0, currency))
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
  const { curve, readout } = await resultsOf(page, key)
  const last = curve.equity.length - 1
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  const figure = page.getByTestId("equity-figure")
  const drawdown = page.getByTestId("equity-drawdown")
  await expect(chart.locator("canvas").first()).toBeVisible()

  await chart.focus()
  await page.keyboard.press("Home")
  await expect(figure).toHaveText(readout(curve.equity[0]))
  await expect(drawdown).toHaveText(readout(curve.drawdown[0]))
  await page.keyboard.press("ArrowRight")
  await expect(figure).toHaveText(readout(curve.equity[1]))
  await page.keyboard.press("ArrowLeft")
  await expect(figure).toHaveText(readout(curve.equity[0]))
  await page.keyboard.press("End")
  await expect(figure).toHaveText(readout(curve.equity[last]))
  await page.keyboard.press("ArrowLeft")
  await expect(figure).toHaveText(readout(curve.equity[last - 1]))
  await page.keyboard.press("Escape")
  await expect(figure).toHaveText(readout(curve.equity[last]))
  expect(errors).toEqual([])
})

test("the pointer on the chart moves the readout, and leaving it gives the last decision back", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { curve, readout } = await resultsOf(page, key)
  const last = readout(curve.equity[curve.equity.length - 1])
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
  await expect(check).toContainText("-$59.50")
  await expect(check).toContainText("+$12.75")
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

test("a currency without a sign follows each figure as its code, which keeps its card", async ({
  loggedIn: page,
}) => {
  // The reviews of D-117: a code stays with its figure, at 12 px after a stat's, so that a crypto
  // run's figures keep their cards and its readout reads in its code.
  const key = await theSeededKey(page)
  const { stats, curve } = await resultsOf(page, key)
  await withAnswers(page, key, (body, result) => {
    if (result === "stats") {
      body.currency = "USDT"
    }
  })

  await page.goto(`/runs/run?key=${key}`)

  const pnl = page.getByTestId("kpi-pnl")
  await expect(pnl).toContainText(moneyText(stats.metrics.pnl, "USDT"))
  await expect(pnl).not.toContainText("$")
  await expect(pnl.getByText("USDT", { exact: true })).toHaveCSS(
    "font-size",
    "12px"
  )
  for (const id of ["kpi-pnl", "kpi-drawdown"]) {
    const figure = page.getByTestId(id).locator("dd").first()
    expect(
      await figure.evaluate((each) => each.scrollWidth <= each.clientWidth),
      id
    ).toBe(true)
  }
  await expect(page.getByTestId("equity-figure")).toHaveText(
    figureMoney(curve.equity[curve.equity.length - 1], "USDT")
  )
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-results-code")
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
  await expect(
    page.getByRole("link", { name: "Back to its version" })
  ).toBeVisible()
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

test("the readout holds between the chart's panes, where no decision lies", async ({
  loggedIn: page,
}) => {
  // The design review: the band between the panes read as the pointer leaving.
  const key = await theSeededKey(page)
  const { curve, readout } = await resultsOf(page, key)
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.scrollIntoViewIfNeeded()
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart drawn, got no box.")
  }
  const figure = page.getByTestId("equity-figure")
  const atRest = readout(curve.equity[curve.equity.length - 1])
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.3)
  await expect(figure).not.toHaveText(atRest)
  const pointed = await figure.innerText()

  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.66)

  await expect(figure).toHaveText(pointed)
})

test("Escape and leaving the chart clear its crosshair and give the readout back", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { curve, readout } = await resultsOf(page, key)
  const last = readout(curve.equity[curve.equity.length - 1])
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  const figure = page.getByTestId("equity-figure")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await expect(figure).toHaveText(last)
  await expect.poll(() => chartPictures(page)).not.toEqual([""])
  const atRest = await chartPictures(page)
  const moved = async () =>
    differingPixels(page, atRest, await chartPictures(page))

  await chart.focus()
  await page.keyboard.press("Home")
  await expect(figure).toHaveText(readout(curve.equity[0]))
  await expect.poll(moved).toBeGreaterThan(FEW_PIXELS)
  await page.keyboard.press("Escape")
  await expect(figure).toHaveText(last)
  await expect.poll(moved).toBeLessThan(FEW_PIXELS)

  await page.keyboard.press("Home")
  await expect(figure).toHaveText(readout(curve.equity[0]))
  await expect.poll(moved).toBeGreaterThan(FEW_PIXELS)
  await page.keyboard.press("Tab")
  await expect(figure).toHaveText(last)
  await expect.poll(moved).toBeLessThan(FEW_PIXELS)
})

test("the chart keeps its reading while the window is away", async ({
  loggedIn: page,
}) => {
  // The design review: a trader who steps to a decision and switches to the charting platform to
  // compare it comes back to that decision.
  const key = await theSeededKey(page)
  const { curve, readout } = await resultsOf(page, key)
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  const figure = page.getByTestId("equity-figure")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.focus()
  await page.keyboard.press("Home")
  await expect(figure).toHaveText(readout(curve.equity[0]))

  await chart.evaluate((element) => {
    document.hasFocus = () => false
    element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }))
    Reflect.deleteProperty(document, "hasFocus")
  })

  await page.keyboard.press("ArrowRight")
  await expect(figure).toHaveText(readout(curve.equity[1]))
})

test("a key with Alt stays the browser's, and the chart repaints with the theme", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { curve, readout } = await resultsOf(page, key)
  const last = readout(curve.equity[curve.equity.length - 1])
  await page.goto(`/runs/run?key=${key}`)
  const chart = page.getByTestId("equity-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await expect.poll(() => chartPictures(page)).not.toEqual([""])

  const pressed = chart.evaluate((element) => {
    const key = new KeyboardEvent("keydown", {
      key: "ArrowLeft",
      altKey: true,
      bubbles: true,
      cancelable: true,
    })
    element.dispatchEvent(key)
    return key.defaultPrevented
  })
  expect(await pressed).toBe(false)
  await expect(page.getByTestId("equity-figure")).toHaveText(last)

  const dark = await chartPictures(page)
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await expect.poll(() => chartPictures(page)).not.toEqual(dark)
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await expect.poll(() => chartPictures(page)).toEqual(dark)
})

test("a bar of one trade shows beside a tall one, and marks keep a colour in a contrast theme", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await withAnswers(page, key, (body, result) => {
    if (result === "distribution") {
      body.pnl = { lower: [-2, -1, 0], upper: [-1, 0, 1], trades: [1, 0, 400] }
    }
  })
  await page.emulateMedia({ forcedColors: "active" })

  await page.goto(`/runs/run?key=${key}`)

  const bars = page
    .getByTestId("histogram-pnl")
    .locator('[data-slot="chart-mark"]')
  await expect(bars.first()).toBeVisible()
  const box = await bars.first().boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(2)
  const [mark, highlight] = await bars.first().evaluate((bar) => {
    const probe = document.createElement("span")
    probe.style.backgroundColor = "Highlight"
    document.body.append(probe)
    const wanted = getComputedStyle(probe).backgroundColor
    probe.remove()
    return [getComputedStyle(bar).backgroundColor, wanted]
  })
  expect(mark).toBe(highlight)
})

test("a section the server refuses says why, with no Try again", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const refusal =
    "The folder of this run is incomplete. Delete it, then run the backtest again."
  await page.route(`**/v1/runs/${key}/distribution`, (route) =>
    route.fulfill(problemAnswer(409, refusal))
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Distributions" })
  await expect(card.getByTestId("run-results-refused")).toHaveText(refusal)
  await expect(card.getByRole("button", { name: "Try again" })).toHaveCount(0)
  await expect(page.getByTestId("key-figures")).toBeVisible()
})

test("a run under way keeps its Status card and asks for no results", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const saved = z
    .looseObject({ strategy: z.looseObject({}) })
    .parse(await (await page.request.get(`/v1/runs/${key}`)).json())
  const asked: string[] = []
  page.on("request", (request) => asked.push(new URL(request.url()).pathname))
  await page.route("**/v1/runs/run-live", (route) =>
    route.fulfill({
      json: {
        ...saved,
        id: "run-live",
        state: "submitted",
        status: "running",
        progress: 40,
        message: "Running the engine",
        error: null,
        job_id: "job-live",
        cancel_requested_at: null,
      },
    })
  )

  await page.goto("/runs/run?id=run-live&job=job-live")

  await expect(page.getByRole("region", { name: "Status" })).toBeVisible()
  await expect(page.getByTestId("run-page-status")).toHaveText("Running")
  await expect(page.getByTestId("run-message")).toHaveText("Running the engine")
  await expect(page.getByTestId("run-page-cancel")).toBeVisible()
  await expect(page.getByTestId("run-settings")).toBeVisible()
  await expect(page.getByTestId("key-figures")).toHaveCount(0)
  expect(asked.filter((each) => each.endsWith("/stats"))).toEqual([])
})
