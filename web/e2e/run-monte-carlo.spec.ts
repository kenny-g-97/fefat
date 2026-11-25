import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import {
  figureMoney,
  figureText,
  moneyText,
  shareText,
} from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The Monte Carlo card of steps 5.20 and 5.21 against the seeded server: every figure it shows,
// each chart's readout among them, is the API's (Done means 1, its other half in
// python/tests/server/test_http_run_results.py), written here with the spec's own formatting. The
// seed's run makes few trades, so a fan of many counts and smooth figures by percent are drawn from
// an answer the spec gives.

const percentiles = z.object({
  p5: z.string(),
  p25: z.string(),
  median: z.string(),
  p75: z.string(),
  p95: z.string(),
})

const fan = z.object({
  capital: z.number(),
  trades_made: z.array(z.number()),
  p5: z.array(z.number()),
  p25: z.array(z.number()),
  median: z.array(z.number()),
  p75: z.array(z.number()),
  p95: z.array(z.number()),
  own: z.array(z.number()),
})

const figureByPercent = z.object({
  at_percent: z.array(z.number()),
  own: z.number(),
})

const byPercent = z.object({
  net_pnl: figureByPercent,
  max_drawdown: figureByPercent,
  profit_factor: z.object({
    at_percent: z.array(z.number().nullable()),
    own: z.number().nullable(),
  }),
  average_mae_ticks: figureByPercent,
  average_mfe_ticks: figureByPercent,
})

const monteCarlo = z.object({
  kind: z.literal("resampled"),
  paths: z.number(),
  trades: z.number(),
  seed: z.number(),
  net_pnl: percentiles,
  max_drawdown: percentiles,
  own_net_pnl: z.string(),
  own_max_drawdown: z.string(),
  net_loss_share: z.number(),
  deeper_drawdown_share: z.number(),
  fan,
  by_percent: byPercent,
})

type Report = z.infer<typeof monteCarlo>
type ByPercent = Report["by_percent"]

const statistics = z.looseObject({ currency: z.string() })

/** Each figure the card charts against the percent of paths: the select's words for it, its name
 * in the readout, and what it counts in. */
const PATH_FIGURES = [
  { figure: "net_pnl", label: "Net P&L", named: "net P&L", unit: "money" },
  {
    figure: "max_drawdown",
    label: "Max drawdown",
    named: "max drawdown",
    unit: "money",
  },
  {
    figure: "profit_factor",
    label: "Profit factor",
    named: "profit factor",
    unit: "ratio",
  },
  {
    figure: "average_mae_ticks",
    label: "Avg. MAE",
    named: "average MAE",
    unit: "ticks",
  },
  {
    figure: "average_mfe_ticks",
    label: "Avg. MFE",
    named: "average MFE",
    unit: "ticks",
  },
] as const

type PathFigure = (typeof PATH_FIGURES)[number]

/** The percent whose path a figure's readout shows while nothing is pointed at. */
const RESTING_PERCENT = 50

/** The seeded run's Monte Carlo as the server draws it unless asked otherwise, and its currency. */
async function theMonteCarlo(page: Page, key: string) {
  const [stats, answer] = await Promise.all([
    page.request.get(`/v1/runs/${key}/stats`),
    page.request.get(`/v1/runs/${key}/monte-carlo`),
  ])
  return {
    currency: statistics.parse(await stats.json()).currency,
    report: monteCarlo.parse(await answer.json()),
  }
}

/** A count with its noun, as the page writes it. */
function countText(count: number, noun: string): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? noun : `${noun}s`}`
}

/** A figure of the paths as the readout writes it: money in the run's currency, a profit factor
 * at two decimals, ticks at two decimals with their unit, or None where a path has none. */
function pathFigureText(
  { unit }: PathFigure,
  value: number | null,
  currency: string
): string {
  if (value === null) {
    return "None"
  }
  if (unit === "money") {
    return figureMoney(value, currency)
  }
  return unit === "ticks" ? `${figureText(value)} ticks` : figureText(value)
}

/** Where the paths stand at `percent`, as the readout says it. */
function percentText(
  { named }: PathFigure,
  percent: number,
  value: number | null
): string {
  return value === null
    ? `The path at ${percent}% drew no losing trade, so it has no profit factor`
    : `${percent}% of paths at or under this ${named}`
}

/** The run's own figure, as the readout says it. */
function ownText(
  figure: PathFigure,
  own: number | null,
  currency: string
): string {
  return own === null
    ? "This run had no losing trade, so it has no profit factor"
    : `This run ${pathFigureText(figure, own, currency)}`
}

/** The entry of `PATH_FIGURES` the select names `label`. */
function pathFigure(label: PathFigure["label"]): PathFigure {
  const found = PATH_FIGURES.find((each) => each.label === label)
  if (found === undefined) {
    throw new Error(`Expected a figure of the paths, got ${label}.`)
  }
  return found
}

/** Choose `label` in the card's select of charts. */
async function chooseChart(
  page: Page,
  card: Locator,
  label: string
): Promise<void> {
  await card.getByRole("combobox", { name: "Chart", exact: true }).click()
  await page.getByRole("option", { name: label, exact: true }).click()
}

/** Expect the readout of `figure`'s chart at `percent`, and the run's own, to be the API's. */
async function expectPercentReadout(
  card: Locator,
  figure: PathFigure,
  shown: ByPercent[PathFigure["figure"]],
  percent: number,
  currency: string
): Promise<void> {
  const value = shown.at_percent[percent]
  await expect(card.getByTestId("percentile-figure")).toHaveText(
    pathFigureText(figure, value, currency)
  )
  await expect(card.getByTestId("percentile-words")).toHaveText(
    percentText(figure, percent, value)
  )
  await expect(card.getByTestId("percentile-own")).toHaveText(
    ownText(figure, shown.own, currency)
  )
}

/** A smooth climb from `low` at none of the paths to `high` at all of them, to the cent. */
function climb(low: number, high: number): number[] {
  return Array.from(
    { length: 101 },
    (_, percent) =>
      Math.round(
        (low + ((high - low) * (1 + Math.tanh((percent - 50) / 22))) / 2) * 100
      ) / 100
  )
}

/** A Monte Carlo of 240 trades whose fan widens as the root of the trades made, with the run's own
 * walk above its median and its figures by percent climbing smoothly, the paths' top four without
 * a profit factor, the figures a longer run would show, for the picture of a fuller card. */
function fullerReport(capital: number): Report {
  const trades = 240
  const made = Array.from({ length: trades + 1 }, (_, count) => count)
  const at = (spread: number) =>
    made.map(
      (count) =>
        Math.round(
          (capital + 9.5 * count + spread * 160 * Math.sqrt(count)) * 100
        ) / 100
    )
  const shown = {
    capital,
    trades_made: made,
    p5: at(-1.645),
    p25: at(-0.674),
    median: at(0),
    p75: at(0.674),
    p95: at(1.645),
    own: made.map(
      (count) =>
        Math.round((capital + 9.5 * count + 120 * Math.sin(count / 18)) * 100) /
        100
    ),
  }
  const net = (column: readonly number[]) =>
    (column[trades] - capital).toFixed(6)
  return {
    kind: "resampled",
    paths: 1000,
    trades,
    seed: 0,
    net_pnl: {
      p5: net(shown.p5),
      p25: net(shown.p25),
      median: net(shown.median),
      p75: net(shown.p75),
      p95: net(shown.p95),
    },
    max_drawdown: {
      p5: "612.500000",
      p25: "1048.750000",
      median: "1460.000000",
      p75: "2012.250000",
      p95: "3105.500000",
    },
    own_net_pnl: net(shown.own),
    own_max_drawdown: "1730.250000",
    net_loss_share: 0.081,
    deeper_drawdown_share: 0.384,
    fan: shown,
    by_percent: {
      net_pnl: {
        at_percent: climb(-2450, 6900),
        own: shown.own[trades] - capital,
      },
      max_drawdown: { at_percent: climb(380, 4120), own: 1730.25 },
      profit_factor: {
        at_percent: climb(0.62, 3.4).map((factor, percent) =>
          percent > 96 ? null : factor
        ),
        own: 1.84,
      },
      average_mae_ticks: { at_percent: climb(6.2, 14.9), own: 9.4 },
      average_mfe_ticks: { at_percent: climb(10.5, 27.3), own: 18.75 },
    },
  }
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" })
})

test("every figure of the Monte Carlo card is the API's", async ({
  loggedIn: page,
}) => {
  // Done means 1 of steps 5.20 and 5.21: DOM equals API, each chart's readout among them.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const money = (text: string) => moneyText(text, currency)
  const readout = (amount: number) => figureMoney(amount, currency)
  const { fan: shown, net_pnl: net, max_drawdown: drawdown } = report
  const last = shown.trades_made.length - 1

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  // Each stat card's label, its figure, and its line, each read whole, so that no figure passes
  // for another standing in the same card.
  const stat = async (
    id: string,
    label: string,
    figure: string,
    line: string
  ) => {
    const found = card.getByTestId(`monte-carlo-${id}`)
    await expect(found.locator("dt")).toHaveText(label)
    await expect(found.locator("dd").first()).toHaveText(figure)
    await expect(found.locator("dd").nth(1)).toHaveText(line)
  }
  await stat(
    "net",
    "Median net P&L",
    money(net.median),
    `5th to 95th percentile: ${money(net.p5)} to ${money(net.p95)}`
  )
  await stat(
    "loss",
    "Chance of a net loss",
    shareText(report.net_loss_share),
    "Paths that ended below the capital"
  )
  await stat(
    "drawdown",
    "Median max drawdown",
    money(drawdown.median),
    `The run's own, of closed trades: ${money(report.own_max_drawdown)}`
  )
  await stat(
    "drawdown-95",
    "95th percentile max drawdown",
    money(drawdown.p95),
    `${shareText(report.deeper_drawdown_share)} of paths fell deeper than the run's own`
  )
  // D-117: every cash value carries its currency's sign, and no label names the currency.
  await expect(card).not.toContainText(currency)
  await expect(
    card.getByRole("combobox", { name: "Chart", exact: true })
  ).toHaveText("Equity")
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[last])
  )
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${shown.trades_made[last]} of ${countText(report.trades, "trade")}`
  )
  // Step 5.21: the run's own walk over the fan ends at its capital plus its net P&L.
  await expect(card.getByTestId("fan-own")).toHaveText(readout(shown.own[last]))
  expect(shown.own[last]).toBeCloseTo(
    shown.capital + Number(report.own_net_pnl),
    6
  )
  await expect(card.getByTestId("fan-inner")).toHaveText(
    `${readout(shown.p25[last])} to ${readout(shown.p75[last])}`
  )
  await expect(card.getByTestId("fan-outer")).toHaveText(
    `${readout(shown.p5[last])} to ${readout(shown.p95[last])}`
  )
  await expect(card.getByTestId("monte-carlo-note")).toHaveText(
    `${countText(report.paths, "path")} of ${countText(report.trades, "trade")}, drawn with replacement from seed ${report.seed}. Drawdowns are of closed trades, and a path keeps no streak across days.`
  )
  await expect(
    card.getByTestId("fan-chart").locator("canvas").first()
  ).toBeVisible()
  // The full page holds the equity chart too, which loads and draws on its own.
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo")
  await lightThemeDrawn(page, ["equity-chart", "fan-chart"])
  await screenshot(page, "run-monte-carlo-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // Step 5.21: each figure against the percent of paths, at the median path while nothing is
  // pointed at, beside the run's own.
  for (const figure of PATH_FIGURES) {
    await chooseChart(page, card, figure.label)
    await expectPercentReadout(
      card,
      figure,
      report.by_percent[figure.figure],
      RESTING_PERCENT,
      currency
    )
    await expect(
      card.getByTestId("percentile-chart").locator("canvas").first()
    ).toBeVisible()
    await expect(card.getByTestId("fan-chart")).toHaveCount(0)
  }
  await expect(card.getByTestId("monte-carlo-note")).toBeVisible()
  await chooseChart(page, card, "Max drawdown")
  await expect(
    card.getByTestId("percentile-chart").locator("canvas").first()
  ).toBeVisible()
  // The picture shows the chart at rest: the select gives up the focus its choice left it.
  await card.getByRole("combobox", { name: "Chart", exact: true }).blur()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo-max-drawdown")
  await lightThemeDrawn(page, ["equity-chart", "percentile-chart"])
  await screenshot(page, "run-monte-carlo-max-drawdown-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("the Monte Carlo card reads in both themes, under the motion floor", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const key = await theSeededKey(page)

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await expect(card.getByTestId("monte-carlo-figures")).toBeVisible()
  await expect(
    card.getByTestId("fan-chart").locator("canvas").first()
  ).toBeVisible()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await chooseChart(page, card, "Profit factor")
  await expect(card.getByTestId("percentile-words")).toBeVisible()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
})

test("the fan's keys step its readout through the counts of trades", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const readout = (amount: number) => figureMoney(amount, currency)
  const { fan: shown } = report
  const of = `of ${countText(report.trades, "trade")}`

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  const chart = card.getByTestId("fan-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.focus()
  await page.keyboard.press("Home")
  // The quality floor: the fan shows the keyboard's focus, the app's outline.
  await expect(chart).toHaveCSS("outline-style", "solid")
  await expect(card.getByTestId("fan-count")).toHaveText(`Median after 0 ${of}`)
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.capital)
  )
  await expect(card.getByTestId("fan-own")).toHaveText(readout(shown.capital))
  await page.keyboard.press("ArrowRight")
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${shown.trades_made[1]} ${of}`
  )
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[1])
  )
  await expect(card.getByTestId("fan-own")).toHaveText(readout(shown.own[1]))
  await page.keyboard.press("Escape")
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${report.trades} ${of}`
  )
})

test("the pointer on the fan moves its readout to the API's figures there, and leaving gives the last back", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const readout = (amount: number) => figureMoney(amount, currency)
  const { fan: shown } = report
  const last = shown.trades_made.length - 1
  await page.goto(`/runs/run?key=${key}`)
  const card = page.getByRole("region", { name: "Monte Carlo" })
  const chart = card.getByTestId("fan-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.scrollIntoViewIfNeeded()
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the fan drawn, got no box.")
  }
  const count = card.getByTestId("fan-count")

  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5)
  await expect(count).not.toHaveText(
    `Median after ${shown.trades_made[last]} of ${countText(report.trades, "trade")}`
  )

  const pointedCount = /^Median after ([\d,]+) of /.exec(
    await count.innerText()
  )
  if (pointedCount === null) {
    throw new Error("Expected the readout to name a count of trades, got none.")
  }
  const at = shown.trades_made.indexOf(
    Number(pointedCount[1].replaceAll(",", ""))
  )
  expect(at).toBeGreaterThan(0)
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[at])
  )
  await expect(card.getByTestId("fan-own")).toHaveText(readout(shown.own[at]))
  await expect(card.getByTestId("fan-inner")).toHaveText(
    `${readout(shown.p25[at])} to ${readout(shown.p75[at])}`
  )
  await expect(card.getByTestId("fan-outer")).toHaveText(
    `${readout(shown.p5[at])} to ${readout(shown.p95[at])}`
  )
  await page.mouse.move(box.x + box.width / 2, box.y - 60)
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[last])
  )
})

test("a figure's chart steps its readout through the percents by the keys and the pointer", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const figure = pathFigure("Max drawdown")
  const shown = report.by_percent.max_drawdown

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await chooseChart(page, card, figure.label)
  const chart = card.getByTestId("percentile-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await chart.focus()
  await page.keyboard.press("ArrowRight")
  // From the median path, where the readout rests.
  await expectPercentReadout(card, figure, shown, 51, currency)
  await page.keyboard.press("End")
  await expectPercentReadout(card, figure, shown, 100, currency)
  await page.keyboard.press("Home")
  await expectPercentReadout(card, figure, shown, 0, currency)
  await page.keyboard.press("Escape")
  await expectPercentReadout(card, figure, shown, RESTING_PERCENT, currency)

  await chart.scrollIntoViewIfNeeded()
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart drawn, got no box.")
  }
  const words = card.getByTestId("percentile-words")
  await page.mouse.move(box.x + box.width * 0.85, box.y + box.height * 0.5)
  await expect(words).not.toHaveText(
    percentText(figure, RESTING_PERCENT, shown.at_percent[RESTING_PERCENT])
  )
  const pointedPercent = /^(\d+)% of paths/.exec(await words.innerText())
  if (pointedPercent === null) {
    throw new Error("Expected the readout to name a percent, got none.")
  }
  const percent = Number(pointedPercent[1])
  expect(percent).toBeGreaterThan(RESTING_PERCENT)
  await expectPercentReadout(card, figure, shown, percent, currency)
  await page.mouse.move(box.x + box.width / 2, box.y - 60)
  await expectPercentReadout(card, figure, shown, RESTING_PERCENT, currency)
})

test("a path without a profit factor stands above every other, and the readout says why", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency, report: seeded } = await theMonteCarlo(page, key)
  const fuller = fullerReport(seeded.fan.capital)
  const figure = pathFigure("Profit factor")
  const shown = fuller.by_percent.profit_factor
  await page.route(`**/v1/runs/${key}/monte-carlo`, (route) =>
    route.fulfill({ json: fuller })
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await chooseChart(page, card, figure.label)
  const chart = card.getByTestId("percentile-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await expectPercentReadout(card, figure, shown, RESTING_PERCENT, currency)
  await chart.focus()
  await page.keyboard.press("End")
  // The paths' top four drew no losing trade: their profit factor is none, ranked above the rest.
  await expectPercentReadout(card, figure, shown, 100, currency)
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await expectPercentReadout(card, figure, shown, 96, currency)
  await chart.blur()
  await expectPercentReadout(card, figure, shown, RESTING_PERCENT, currency)
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo-profit-factor")
  expect(errors).toEqual([])
})

test("a run without a losing trade says that no path has a profit factor", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const figure = pathFigure("Profit factor")
  const shown = {
    at_percent: report.by_percent.profit_factor.at_percent.map(() => null),
    own: null,
  }
  const flawless = {
    ...report,
    by_percent: { ...report.by_percent, profit_factor: shown },
  }
  await page.route(`**/v1/runs/${key}/monte-carlo`, (route) =>
    route.fulfill({ json: flawless })
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await chooseChart(page, card, figure.label)
  await expectPercentReadout(card, figure, shown, RESTING_PERCENT, currency)
  await expect(card.getByTestId("percentile-none")).toHaveText(
    "No path drew a losing trade, so none has a profit factor."
  )
  await expect(card.getByTestId("percentile-chart")).toHaveCount(0)
})

test("a run of one trade says why it has no Monte Carlo", async ({
  loggedIn: page,
}) => {
  // Done means 3 of step 5.20: the card says the server's why in its place.
  const key = await theSeededKey(page)
  const reason =
    "This run made 1 trade, and a Monte Carlo draws from at least 2."
  await page.route(`**/v1/runs/${key}/monte-carlo`, (route) =>
    route.fulfill({ json: { kind: "too_few_trades", trades: 1, reason } })
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await expect(card.getByTestId("monte-carlo-too-few")).toHaveText(reason)
  await expect(card.getByTestId("monte-carlo-figures")).toHaveCount(0)
  await expect(card.getByTestId("fan-chart")).toHaveCount(0)
  await expect(
    card.getByRole("combobox", { name: "Chart", exact: true })
  ).toHaveCount(0)
})

test("while the paths are drawn the card says so and keeps its room", async ({
  loggedIn: page,
}) => {
  // The design review: a long run's paths take seconds, and the cards under them must not jump.
  const key = await theSeededKey(page)
  let release = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**/v1/runs/${key}/monte-carlo`, async (route) => {
    await held
    await route.continue()
  })

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  const drawing = card.getByRole("status")
  await expect(drawing).toHaveText("Drawing paths", { timeout: 1000 })
  const room = await drawing.boundingBox()
  expect(room?.height).toBeGreaterThanOrEqual(700)
  release()
  await expect(card.getByTestId("monte-carlo-figures")).toBeVisible()
  await expect(card.getByTestId("monte-carlo-drawing")).toHaveCount(0)
})

test("a fuller Monte Carlo draws its fan over every count", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency, report: seeded } = await theMonteCarlo(page, key)
  const fuller = fullerReport(seeded.fan.capital)
  await page.route(`**/v1/runs/${key}/monte-carlo`, (route) =>
    route.fulfill({ json: fuller })
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  await expect(card.getByTestId("fan-count")).toHaveText(
    "Median after 240 of 240 trades"
  )
  await expect(card.getByTestId("monte-carlo-net")).toContainText(
    moneyText(fuller.net_pnl.median, currency)
  )
  await expect(card.getByTestId("fan-figure")).toHaveText(
    figureMoney(fuller.fan.median[240], currency)
  )
  await expect(card.getByTestId("fan-own")).toHaveText(
    figureMoney(fuller.fan.own[240], currency)
  )
  await expect(
    card.getByTestId("fan-chart").locator("canvas").first()
  ).toBeVisible()
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo-full")
  expect(errors).toEqual([])
})
