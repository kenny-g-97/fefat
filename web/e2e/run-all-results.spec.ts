import type { Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import {
  countText,
  durationText,
  figureMoney,
  figureText,
  moneyText,
  shareText,
} from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// A run's results in full of step 5.22 against the seeded server: every figure of the page is the
// API's (Done means 1, its other halves in python/tests/server/test_http_run_results.py and
// python/tests/test_backtest_results_by_side.py), read here with the spec's own formatting. The
// seeded breakout trades long alone, so a run of both sides is drawn from an answer the spec
// gives, its figures worked out by hand so that they add up.

const side = z.looseObject({
  trades: z.number(),
  wins: z.number(),
  losses: z.number(),
  win_rate: z.number().nullable(),
  net_pnl: z.string(),
  gross_profit: z.string(),
  gross_loss: z.string(),
  profit_factor: z.number().nullable(),
  expectancy: z.number().nullable(),
  expectancy_r: z.number().nullable(),
  average_win: z.number().nullable(),
  average_loss: z.number().nullable(),
  win_loss_ratio: z.number().nullable(),
  fees: z.string(),
  funding: z.string().nullable(),
  slippage: z.string(),
  trades_per_day: z.number().nullable(),
  average_minutes_held: z.number().nullable(),
  average_mae_ticks: z.number().nullable(),
  average_mfe_ticks: z.number().nullable(),
  max_drawdown: z.string(),
  longest_drawdown_days: z.number(),
  sharpe: z.number().nullable(),
})
type Side = z.infer<typeof side>
const bySide = z.looseObject({
  all_trades: side,
  long: side.nullable(),
  short: side.nullable(),
})
type BySide = z.infer<typeof bySide>
const statistics = z.looseObject({
  currency: z.string(),
  metrics: z.looseObject({
    trades: z.looseObject({}),
    drawdown: z.looseObject({}),
    daily: z.looseObject({}),
    breakdowns: z.looseObject({}),
  }),
})

const NONE = "None"

function ratio(value: number | null): string {
  return value === null ? NONE : figureText(value)
}

function average(value: number | null, currency: string): string {
  return value === null ? NONE : figureMoney(value, currency)
}

function ticks(value: number | null): string {
  return value === null ? NONE : `${figureText(value)} ticks`
}

/** Each row of the table by its id, with its figure of a side as the page writes it. */
const ROWS: readonly (readonly [
  string,
  (each: Side, currency: string) => string,
])[] = [
  ["net-pnl", (each, currency) => moneyText(each.net_pnl, currency)],
  ["gross-profit", (each, currency) => moneyText(each.gross_profit, currency)],
  ["gross-loss", (each, currency) => moneyText(each.gross_loss, currency)],
  ["profit-factor", (each) => ratio(each.profit_factor)],
  ["trades", (each) => each.trades.toLocaleString("en-US")],
  ["wins", (each) => each.wins.toLocaleString("en-US")],
  ["losses", (each) => each.losses.toLocaleString("en-US")],
  [
    "win-rate",
    (each) => (each.win_rate === null ? NONE : shareText(each.win_rate)),
  ],
  ["trades-per-day", (each) => ratio(each.trades_per_day)],
  ["expectancy", (each, currency) => average(each.expectancy, currency)],
  [
    "expectancy-r",
    (each) =>
      each.expectancy_r === null ? NONE : `${figureText(each.expectancy_r)} R`,
  ],
  ["average-win", (each, currency) => average(each.average_win, currency)],
  ["average-loss", (each, currency) => average(each.average_loss, currency)],
  ["win-loss-ratio", (each) => ratio(each.win_loss_ratio)],
  [
    "time-in-market",
    (each) =>
      each.average_minutes_held === null
        ? NONE
        : durationText(each.average_minutes_held),
  ],
  ["average-mae", (each) => ticks(each.average_mae_ticks)],
  ["average-mfe", (each) => ticks(each.average_mfe_ticks)],
  ["fees", (each, currency) => moneyText(each.fees, currency)],
  ["slippage", (each, currency) => moneyText(each.slippage, currency)],
  ["max-drawdown", (each, currency) => moneyText(each.max_drawdown, currency)],
  ["longest-spell", (each) => countText(each.longest_drawdown_days, "day")],
  ["sharpe", (each) => ratio(each.sharpe)],
]

const CLOSED =
  "A side's max drawdown, longest spell under a peak, and Sharpe are of its closed trades, walked from the capital in the order they closed; those of all trades mark open trades to market."

/** The seeded run's results by side and its statistics, as the server answers them. */
async function answersOf(page: Page, key: string) {
  const [results, stats] = await Promise.all([
    page.request.get(`/v1/runs/${key}/results`),
    page.request.get(`/v1/runs/${key}/stats`),
  ])
  return {
    sides: bySide.parse(await results.json()),
    currency: statistics.parse(await stats.json()).currency,
  }
}

/** Every row of the table holds `answer`'s figures in its three columns, in order. */
async function expectTheTable(page: Page, answer: BySide, currency: string) {
  const sides = [answer.all_trades, answer.long, answer.short]
  for (const [id, written] of ROWS) {
    const cells = page.getByTestId(`by-side-${id}`).getByRole("cell")
    await expect(cells, id).toHaveText(
      sides.map((each) => (each === null ? NONE : written(each, currency)))
    )
  }
}

const LONG = {
  trades: 14,
  wins: 8,
  losses: 6,
  win_rate: 8 / 14,
  net_pnl: "900.000000",
  gross_profit: "2400.000000",
  gross_loss: "-1500.000000",
  profit_factor: 1.6,
  expectancy: 900 / 14,
  expectancy_r: 0.21,
  average_win: 300,
  average_loss: -250,
  win_loss_ratio: 1.2,
  fees: "80.360000",
  funding: null,
  slippage: "175.000000",
  trades_per_day: 7,
  average_minutes_held: 47.5,
  average_mae_ticks: 5.5,
  average_mfe_ticks: 9.25,
  max_drawdown: "612.500000",
  longest_drawdown_days: 1,
  sharpe: 2.31,
}
const SHORT = {
  trades: 10,
  wins: 4,
  losses: 6,
  win_rate: 0.4,
  net_pnl: "-470.000000",
  gross_profit: "1150.000000",
  gross_loss: "-1620.000000",
  profit_factor: 1150 / 1620,
  expectancy: -47,
  expectancy_r: -0.15,
  average_win: 287.5,
  average_loss: -270,
  win_loss_ratio: 287.5 / 270,
  fees: "57.400000",
  funding: null,
  slippage: "125.000000",
  trades_per_day: 5,
  average_minutes_held: 38.2,
  average_mae_ticks: 6.1,
  average_mfe_ticks: 7.4,
  max_drawdown: "845.000000",
  longest_drawdown_days: 2,
  sharpe: -1.12,
}
/** A run of 24 trades over the seeded run's two trade dates, its sides those above, the sums
 * theirs. */
const BOTH_SIDES = {
  all_trades: {
    trades: 24,
    wins: 12,
    losses: 12,
    win_rate: 0.5,
    net_pnl: "430.000000",
    gross_profit: "3550.000000",
    gross_loss: "-3120.000000",
    profit_factor: 3550 / 3120,
    expectancy: 430 / 24,
    expectancy_r: 0.06,
    average_win: 3550 / 12,
    average_loss: -260,
    win_loss_ratio: 3550 / 12 / 260,
    fees: "137.760000",
    funding: null,
    slippage: "300.000000",
    trades_per_day: 12,
    average_minutes_held: (14 * 47.5 + 10 * 38.2) / 24,
    average_mae_ticks: (14 * 5.5 + 10 * 6.1) / 24,
    average_mfe_ticks: (14 * 9.25 + 10 * 7.4) / 24,
    max_drawdown: "690.000000",
    longest_drawdown_days: 2,
    sharpe: 0.42,
  },
  long: LONG,
  short: SHORT,
}

/** The seeded run answered as the run of both sides above: its results by side, and its
 * statistics changed to match, so that the KPI cards read the same run. */
async function withBothSides(page: Page, key: string) {
  const every = BOTH_SIDES.all_trades
  await page.route(`**/v1/runs/${key}/results`, (route) =>
    route.fulfill({ json: BOTH_SIDES })
  )
  await page.route(`**/v1/runs/${key}/stats`, async (route) => {
    const answered = await route.fetch()
    const body = statistics.parse(await answered.json())
    const { metrics } = body
    await route.fulfill({
      response: answered,
      json: {
        ...body,
        pnl_share: 430 / 50_000,
        metrics: {
          ...metrics,
          pnl: every.net_pnl,
          trades: {
            ...metrics.trades,
            trades: every.trades,
            wins: every.wins,
            losses: every.losses,
            win_rate: every.win_rate,
            profit_factor: every.profit_factor,
            expectancy: every.expectancy,
            expectancy_r: every.expectancy_r,
          },
          drawdown: {
            ...metrics.drawdown,
            max_drawdown: every.max_drawdown,
            max_drawdown_share: 690 / 50_000,
          },
          daily: { ...metrics.daily, sharpe: every.sharpe },
          breakdowns: {
            ...metrics.breakdowns,
            fidelity: { "1m": { trades: 24, wins: 12, pnl: every.net_pnl } },
          },
        },
      },
    })
  })
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" })
})

test("every figure of a run's results in full is the API's", async ({
  loggedIn: page,
}) => {
  // Done means 1: DOM equals API, on the seeded run, which made no short trade.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { sides, currency } = await answersOf(page, key)
  expect(sides.long).not.toBeNull()
  expect(sides.short).toBeNull()

  await page.goto(`/runs/run?key=${key}`)
  const onTheRunPage = page.getByTestId("key-figures")
  await expect(onTheRunPage).toContainText(
    moneyText(sides.all_trades.net_pnl, currency)
  )
  const kpiCards = await onTheRunPage.innerText()
  await page.getByTestId("all-results").click()

  await expect(page).toHaveURL(`/runs/run/results?key=${key}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "All results"
  )
  // The eight KPI cards as the run page shows them, whose figures run-results.spec.ts holds to
  // the API, and the run's key, which tells it apart from another run of its version.
  await expect
    .poll(() => page.getByTestId("key-figures").innerText())
    .toBe(kpiCards)
  await expect(page.getByTestId("run-key")).toHaveText(key.slice(0, 12))
  await expectTheTable(page, sides, currency)
  await expect(page.getByTestId("by-side-funding")).toHaveCount(0)
  await expect(
    page.getByText(
      "This run made no short trade, so the Short column reads None."
    )
  ).toBeVisible()
  await expect(page.getByTestId("results-by-side-note")).toHaveText(CLOSED)
  await page.mouse.move(700, 36)
  await screenshot(page, "run-all-results")
  expect(errors).toEqual([])
})

test("a run of both sides reads each side's figures, money in its sign's colour", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency } = await answersOf(page, key)
  await withBothSides(page, key)

  await page.goto(`/runs/run/results?key=${key}`)

  await expectTheTable(page, BOTH_SIDES, currency)
  await expect(page.getByTestId("results-by-side-note")).toHaveText(CLOSED)
  await expect(page.getByText(/made no (long|short)? ?trade/)).toHaveCount(0)
  await expect(page.getByTestId("kpi-pnl")).toContainText(
    moneyText("430", currency)
  )
  const pnl = page.getByTestId("by-side-net-pnl").getByRole("cell")
  await expect(pnl.nth(1)).toHaveClass(/text-positive/)
  await expect(pnl.nth(2)).toHaveClass(/text-negative/)
  const fees = page.getByTestId("by-side-fees").getByRole("cell")
  await expect(fees.nth(0)).not.toHaveClass(/text-(positive|negative)/)
  await expect(fees.nth(0)).toHaveClass(/text-foreground(?!-)/)
  await expect(
    page.getByTestId("by-side-net-pnl").getByRole("rowheader")
  ).toHaveText("Net P&L")
  // The design review: five sets of rows, set apart, the side columns on equal tracks.
  await expect(
    page.getByTestId("results-by-side").locator("tbody")
  ).toHaveCount(5)
  const widths = await page
    .getByTestId("results-by-side")
    .locator("thead th")
    .evaluateAll((heads) =>
      heads.slice(1).map((head) => head.getBoundingClientRect().width)
    )
  expect(new Set(widths).size).toBe(1)
  await page.mouse.move(700, 36)
  await screenshot(page, "run-all-results-both-sides")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-all-results-both-sides-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("a run's results in full read in both themes, under the motion floor", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const key = await theSeededKey(page)
  await withBothSides(page, key)

  await page.goto(`/runs/run/results?key=${key}`)

  await expect(page.getByTestId("results-by-side")).toBeVisible()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
})

test("Back to the run, then Back to Runs, keep the list as it was filtered", async ({
  loggedIn: page,
}) => {
  // Succeeded runs alone, since a run of demo that failed has no results to open.
  await page.goto("/runs?strategy=demo&status=succeeded")
  await expect(page.getByTestId("run-strategy").first()).toHaveText("demo")
  await page.getByTestId("run-row").last().click()
  await expect(page.getByTestId("run-page-status")).toBeVisible()

  await page.getByTestId("all-results").click()
  await expect(page.getByTestId("results-by-side")).toBeVisible()
  await page.getByRole("link", { name: "Back to the run" }).click()

  await expect(page.getByTestId("run-page-status")).toBeVisible()
  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page).toHaveURL(/strategy=demo/)
  await expect(page).toHaveURL(/status=succeeded/)
})

test("All results and Back to the run show the keyboard's focus", async ({
  loggedIn: page,
}) => {
  // The quality floor on the page's own controls (the UI verification): each reached by the
  // keyboard takes the app's outline.
  await page.emulateMedia({ reducedMotion: "reduce" })
  const key = await theSeededKey(page)
  await page.goto(`/runs/run?key=${key}`)
  const allResults = page.getByTestId("all-results")
  await allResults.focus()
  await page.keyboard.press("Shift+Tab")
  await page.keyboard.press("Tab")
  await expect(allResults).toBeFocused()
  await expect(allResults).toHaveCSS("outline-style", "solid")

  await page.keyboard.press("Enter")
  const back = page.getByRole("link", { name: "Back to the run" })
  await expect(page.getByTestId("results-by-side")).toBeVisible()
  await back.focus()
  await page.keyboard.press("Shift+Tab")
  await page.keyboard.press("Tab")
  await expect(back).toBeFocused()
  await expect(back).toHaveCSS("outline-style", "solid")
})

test("a run whose figures by side are refused says why under its KPI cards", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const refusal =
    "Expected a run of engine version 9, got one of version 8: run it again with this engine."
  await page.route(`**/v1/runs/${key}/results`, (route) =>
    route.fulfill(problemAnswer(409, refusal))
  )

  await page.goto(`/runs/run/results?key=${key}`)

  await expect(page.getByTestId("run-results-refused")).toHaveText(refusal)
  await expect(page.getByTestId("key-figures")).toBeVisible()
  await expect(page.getByTestId("results-by-side")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0)
  expect(errors.filter((each) => !each.includes("409"))).toEqual([])
})

test("an address that names no run says so", async ({ loggedIn: page }) => {
  await page.goto("/runs/run/results")

  await expect(page.getByRole("alert")).toHaveText(
    "This address names no run. Choose one on the Runs page."
  )
  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page).toHaveURL("/runs")
})
