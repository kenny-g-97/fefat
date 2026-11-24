import type { Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { figureMoney, moneyText, shareText } from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The Monte Carlo card of step 5.20 against the seeded server: every figure it shows is the API's
// (Done means 1, its other half in python/tests/server/test_http_run_results.py), written here with
// the spec's own formatting. The seed's run makes few trades, so a fan of many counts is drawn
// from an answer the spec gives.

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
})

type Report = z.infer<typeof monteCarlo>

const statistics = z.looseObject({ currency: z.string() })

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

/** A Monte Carlo of 240 trades whose fan widens as the root of the trades made, the figures a
 * longer run would show, for the picture of a fuller card. */
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
    own_net_pnl: "2280.000000",
    own_max_drawdown: "1730.250000",
    net_loss_share: 0.081,
    deeper_drawdown_share: 0.384,
    fan: shown,
  }
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" })
})

test("every figure of the Monte Carlo card is the API's", async ({
  loggedIn: page,
}) => {
  // Done means 1 of step 5.20: DOM equals API.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency, report } = await theMonteCarlo(page, key)
  const money = (text: string) => moneyText(text, currency)
  const readout = (amount: number) => figureMoney(amount, currency)
  const { fan: shown, net_pnl: net, max_drawdown: drawdown } = report
  const last = shown.trades_made.length - 1

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Monte Carlo" })
  const stat = (id: string) => card.getByTestId(`monte-carlo-${id}`)
  await expect(stat("net")).toContainText("Median net P&L")
  await expect(stat("net")).toContainText(money(net.median))
  await expect(stat("net")).toContainText(
    `5th to 95th percentile: ${money(net.p5)} to ${money(net.p95)}`
  )
  await expect(stat("loss")).toContainText("Chance of a net loss")
  await expect(stat("loss")).toContainText(shareText(report.net_loss_share))
  await expect(stat("drawdown")).toContainText("Median max drawdown")
  await expect(stat("drawdown")).toContainText(money(drawdown.median))
  await expect(stat("drawdown")).toContainText(
    `The run's own, of closed trades: ${money(report.own_max_drawdown)}`
  )
  await expect(stat("drawdown-95")).toContainText(
    "95th percentile max drawdown"
  )
  await expect(stat("drawdown-95")).toContainText(money(drawdown.p95))
  await expect(stat("drawdown-95")).toContainText(
    `${shareText(report.deeper_drawdown_share)} of paths fell deeper than the run's own`
  )
  // D-117: every cash value carries its currency's sign, and no label names the currency.
  await expect(card).not.toContainText(currency)
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[last])
  )
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${shown.trades_made[last]} of ${countText(report.trades, "trade")}`
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
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-monte-carlo-light")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
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
  await expect(card.getByTestId("fan-count")).toHaveText(`Median after 0 ${of}`)
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.capital)
  )
  await page.keyboard.press("ArrowRight")
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${shown.trades_made[1]} ${of}`
  )
  await expect(card.getByTestId("fan-figure")).toHaveText(
    readout(shown.median[1])
  )
  await page.keyboard.press("Escape")
  await expect(card.getByTestId("fan-count")).toHaveText(
    `Median after ${report.trades} ${of}`
  )
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
  await expect(
    card.getByTestId("fan-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-monte-carlo-full")
  expect(errors).toEqual([])
})
