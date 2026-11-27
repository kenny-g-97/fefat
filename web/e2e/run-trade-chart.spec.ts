import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { chartReady, lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The trade review chart of step 5.9 against the seeded server: selecting a trade in the table
// centres the chart on it and pins its entry marker's tooltip at the row's entry time and
// price (Done means 1); Previous and Next step through the table's trades, kept in the page's
// address with the selection; a link names a trade the filters hide; the chart draws the price,
// the volume, and a pane a feature; Explain shows the replay's timeline beside the chart. In
// UTC, so that the spec writes the table's instants without the app's formatter.
test.use({ timezoneId: "UTC" })

const trade = z.looseObject({
  trade: z.number(),
  entry_order: z.number(),
  entry_ts: z.string(),
  entry_price: z.string(),
})
const tradePage = z.object({ trades: z.array(trade), total: z.number() })

/** The first page of the seeded run's trades in the table's own order, oldest entry first, and
 * how many there are. */
async function pageOf(page: Page, key: string) {
  const answer = await page.request.get(`/v1/runs/${key}/trades`)
  expect(answer.status()).toBe(200)
  return tradePage.parse(await answer.json())
}

async function tradesOf(page: Page, key: string) {
  return (await pageOf(page, key)).trades
}

async function totalOf(page: Page, key: string) {
  return (await pageOf(page, key)).total
}

/** An instant of the API to the second, as the table writes it in UTC. */
function second(iso: string): string {
  return iso.slice(0, 19).replace("T", " ")
}

/** The text a cell shows, its padding of spaces trimmed, as the tooltip shows the same figure. */
async function shownText(cell: Locator): Promise<string> {
  const text = await cell.textContent()
  return text === null ? "" : text.trim()
}

async function openTrades(page: Page, key: string, asked = ""): Promise<void> {
  await page.goto(`/runs/run/trades?key=${key}${asked}`)
  await expect(page.getByTestId("trade-row").first()).toBeVisible()
  await chartReady(page)
}

test("selecting trade 3 pins its entry marker's tooltip at the row's entry time and price", async ({
  loggedIn: page,
}) => {
  // Done means 1: open the demo run, select trade 3, the entry marker tooltip equals the table
  // row's entry time and price, no console errors.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const third = (await tradesOf(page, key))[2]
  await openTrades(page, key)
  const row = page.getByTestId("trade-row").nth(2)

  await row.click()

  await expect(page).toHaveURL(new RegExp(`trade=${third.trade}(&|$)`))
  await chartReady(page)
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-centred-on",
    String(third.trade)
  )
  const tooltip = page.getByTestId("entry-marker-tooltip")
  const cells = row.locator("td")
  const [entry, price] = [
    await shownText(cells.nth(0)),
    await shownText(cells.nth(1)),
  ]
  expect([entry, price]).toEqual([second(third.entry_ts), third.entry_price])
  await expect(tooltip.getByTestId("marker-time")).toHaveText(entry)
  await expect(tooltip.getByTestId("marker-price")).toHaveText(price)
  const chart = await page.getByTestId("price-chart").boundingBox()
  const pinned = await tooltip.boundingBox()
  expect(chart).not.toBeNull()
  expect(pinned).not.toBeNull()
  if (chart !== null && pinned !== null) {
    expect(pinned.x).toBeGreaterThanOrEqual(chart.x)
    expect(pinned.x + pinned.width).toBeLessThanOrEqual(chart.x + chart.width)
    expect(pinned.y).toBeGreaterThanOrEqual(chart.y)
  }
  await expect(page.getByTestId("trade-entry")).toHaveText(entry)
  await expect(page.getByTestId("trade-position")).toHaveText(
    `3 of ${await totalOf(page, key)}`
  )
  await page.mouse.move(0, 0)
  await screenshot(page, "run-trade-chart")
  expect(errors).toEqual([])
})

test("the chart draws the price, the volume, and a pane for each of the strategy's features", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await openTrades(page, key, "&trade=2")

  await expect(page.getByTestId("price-chart")).toHaveAttribute(
    "data-panes",
    "4"
  )
  await expect(page.getByTestId("readout-feature-highest")).toBeVisible()
  await expect(page.getByTestId("readout-feature-atr")).toBeVisible()
})

test("Previous and Next step through the table's trades, kept in the address and the table", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const trades = await tradesOf(page, key)
  await openTrades(page, key)
  await page.getByTestId("trade-row").nth(2).click()

  await page.getByTestId("next-trade").click()

  await expect(page).toHaveURL(new RegExp(`trade=${trades[3].trade}(&|$)`))
  const fourth = page.locator('[data-testid="trade-row"][data-index="3"]')
  await expect(fourth).toHaveAttribute("aria-selected", "true")
  await expect(page.getByTestId("trade-position")).toHaveText(
    `4 of ${await totalOf(page, key)}`
  )
  await page.getByTestId("previous-trade").click()
  await page.getByTestId("previous-trade").click()
  await expect(page).toHaveURL(new RegExp(`trade=${trades[1].trade}(&|$)`))
  await expect(
    page.locator('[data-testid="trade-row"][data-index="1"]')
  ).toHaveAttribute("aria-selected", "true")
  await expect(
    page.getByTestId("entry-marker-tooltip").getByTestId("marker-time")
  ).toHaveText(second(trades[1].entry_ts))
})

test("a link opens the chart on its trade, even one the table's filters hide", async ({
  loggedIn: page,
}) => {
  // BACKLOG's "The selected trade in the address": a reload or a link keeps the selection.
  const key = await theSeededKey(page)
  const third = (await tradesOf(page, key))[2]

  await openTrades(page, key, `&pnl_sign=positive&trade=${third.trade}`)

  await expect(
    page.getByTestId("entry-marker-tooltip").getByTestId("marker-price")
  ).toHaveText(third.entry_price)
  await expect(page.getByTestId("trade-position")).toHaveText(
    "Not in the table"
  )
  await expect(
    page.locator('[data-testid="trade-row"][aria-selected="true"]')
  ).toHaveCount(0)
})

test("the chart stays drawn across a look at the SQL tab", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await openTrades(page, key, "&trade=2")

  await page.getByTestId("tab-sql").click()
  await page.getByTestId("tab-trades").click()

  await expect(page.getByTestId("entry-marker-tooltip")).toBeVisible()
  await chartReady(page)
})

test("Explain shows the trade's replay as a timeline beside the chart", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const third = (await tradesOf(page, key))[2]
  await openTrades(page, key, `&trade=${third.trade}`)

  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/explain/${third.entry_order}`) &&
      response.request().method() === "POST"
  )
  await page.getByTestId("explain-trade").click()

  expect((await started).status()).toBe(202)
  const panel = page.getByTestId("explanation-panel")
  const filled = panel.locator(
    '[data-testid="explained-event"][data-kind="filled"]'
  )
  // The replay runs in a worker of the server's pool, as a job.
  await expect(filled.first()).toBeVisible({ timeout: 30_000 })
  await expect(filled.first().getByTestId("explained-event-time")).toHaveText(
    second(third.entry_ts)
  )
  await page.mouse.move(0, 0)
  await screenshot(page, "run-trade-chart-explained")
  await page.getByRole("button", { name: "Close the explanation" }).click()
  await expect(panel).toBeHidden()
})

test("the trade review draws in the light theme too", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await openTrades(page, key, "&trade=2")
  await expect(page.getByTestId("entry-marker-tooltip")).toBeVisible()

  await lightThemeDrawn(page, ["price-chart"])

  await page.mouse.move(0, 0)
  await screenshot(page, "run-trade-chart-light")
})
