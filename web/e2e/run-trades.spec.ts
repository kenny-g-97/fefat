import { readFile } from "node:fs/promises"
import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { durationText, figureText, moneyText } from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs, startDemoJobs } from "./support/jobs.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// The trade table of step 5.8 against the seeded server (Done means 2): every cell of the
// table is the API's trade, read here with the spec's own formatting; a header sorts and a
// filter narrows the trades as the API does, kept in the page's address, a sort chosen by the
// keys keeping its focus; a refused date clears once fixed, and Clear filters clears every
// field; a selected row emits `selectedTrade` with the API's trade; the column chooser hides
// and shows; both exports download the API's files; the SQL tab answers as the API does; only
// the rows near the view are drawn, the header and the entry column staying in view, one row in
// the tab order, and a page that fails keeping the rows read; a price of many places fits its
// column; and the contrast modes. In UTC, so that the spec writes the table's instants without
// the app's formatter.
test.use({ timezoneId: "UTC" })

const trade = z.looseObject({
  trade: z.number(),
  entry_order: z.number(),
  entry_ts: z.string(),
  entry_price: z.string(),
  exit_ts: z.string(),
  exit_price: z.string().nullable(),
  side: z.string(),
  lots: z.number(),
  pnl: z.string(),
  r_multiple: z.number().nullable(),
  held_minutes: z.number(),
  mae_ticks: z.number(),
  mfe_ticks: z.number(),
  exit_reason: z.string(),
  entry_contract: z.string(),
  fidelity: z.string(),
  ambiguous: z.boolean(),
})
type Trade = z.infer<typeof trade>
const tradePage = z.object({
  trades: z.array(trade),
  next_cursor: z.string().nullable(),
  total: z.number(),
})
type TradePage = z.infer<typeof tradePage>
const savedRun = z.looseObject({ currency: z.string().nullable() })
const queryAnswer = z.object({
  columns: z.array(z.object({ name: z.string(), type: z.string() })),
  rows: z.array(z.array(z.unknown())),
})
const identity = z.object({ csrf_token: z.string() })
const refusal = z.looseObject({ detail: z.string() })

/** The columns the table shows until the trader hides one, in its order. */
const SHOWN = [
  "Entry",
  "Entry price",
  "Exit",
  "Exit price",
  "Side",
  "Lots",
  "Net P&L",
  "R",
  "Held",
  "MAE ticks",
  "MFE ticks",
  "Exit reason",
  "Contract",
  "Fidelity",
  "Ambiguous",
]

async function tradesOf(
  page: Page,
  key: string,
  asked: Readonly<Record<string, string>> = {}
): Promise<TradePage> {
  const answer = await page.request.get(`/v1/runs/${key}/trades`, {
    params: asked,
  })
  expect(answer.status()).toBe(200)
  return tradePage.parse(await answer.json())
}

async function currencyOf(page: Page, key: string): Promise<string | null> {
  const answer = await page.request.get(`/v1/runs/${key}`)
  return savedRun.parse(await answer.json()).currency
}

/** An instant of the API to the second, as the table writes it in UTC. */
function second(iso: string): string {
  return iso.slice(0, 19).replace("T", " ")
}

function words(word: string): string {
  const spaced = word.replaceAll("_", " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function fidelityWords(fidelity: string): string {
  if (fidelity === "trades") {
    return "Trades"
  }
  const minutes = /^(\d+)m$/.exec(fidelity)
  if (minutes === null) {
    throw new Error(
      `Expected a fidelity of trades or minutes, got ${fidelity}.`
    )
  }
  return `${minutes[1]}-minute bars`
}

/** The cells of `shown`'s row as the table's own columns write them. */
function cellsOf(shown: Trade, currency: string | null): string[] {
  return [
    second(shown.entry_ts),
    shown.entry_price,
    second(shown.exit_ts),
    shown.exit_price ?? "None",
    words(shown.side),
    String(shown.lots),
    moneyText(shown.pnl, currency),
    shown.r_multiple === null ? "None" : figureText(shown.r_multiple),
    durationText(shown.held_minutes),
    shown.mae_ticks.toLocaleString("en-US"),
    shown.mfe_ticks.toLocaleString("en-US"),
    words(shown.exit_reason),
    shown.entry_contract,
    fidelityWords(shown.fidelity),
    shown.ambiguous ? "Yes" : "No",
  ]
}

/** Each drawn row's index in the trades read, from its own data attribute. */
async function drawnIndexes(page: Page): Promise<number[]> {
  return page
    .getByTestId("trade-row")
    .evaluateAll((rows) =>
      rows.map((row) => Number(row.getAttribute("data-index")))
    )
}

/** Every drawn row against the trade the API gives at its index. */
async function expectRowsOf(
  page: Page,
  expected: TradePage,
  currency: string | null
): Promise<void> {
  const rows = page.getByTestId("trade-row")
  await expect(rows.first()).toBeVisible()
  for (const index of await drawnIndexes(page)) {
    const row = page.locator(`[data-testid="trade-row"][data-index="${index}"]`)
    await expect(row.locator("td")).toHaveText(
      cellsOf(expected.trades[index], currency)
    )
  }
}

async function csrf(page: Page): Promise<Record<string, string>> {
  const me = identity.parse(await (await page.request.get("/v1/me")).json())
  return { "X-CSRF-Token": me.csrf_token }
}

function grid(page: Page): Locator {
  return page.getByTestId("trade-grid")
}

/** Listens in the page for the next `selectedTrade`, the listener in place once this resolves,
 * so that no action can come before it, and gives the trade it hears. */
async function listenForSelectedTrade(
  page: Page
): Promise<() => Promise<unknown>> {
  const listening = await page.evaluateHandle(() => ({
    heard: new Promise((resolve) => {
      window.addEventListener(
        "selectedTrade",
        (event) => resolve(event instanceof CustomEvent ? event.detail : null),
        { once: true }
      )
    }),
  }))
  return () => listening.evaluate((box) => box.heard)
}

/** The trades route answering 5,000 copies of the seeded run's first trade, each its own, 200 a
 * page, a page's cursor the number of its first trade; a page whose cursor `fails` holds
 * answers 500. The cursors asked, `first` for the first page, in the order asked. */
async function routeManyTrades(
  page: Page,
  key: string,
  fails: (cursor: string) => boolean = () => false
): Promise<string[]> {
  const template = (await tradesOf(page, key)).trades[0]
  const cursors: string[] = []
  await page.route(
    (url) => url.pathname === `/v1/runs/${key}/trades`,
    async (route) => {
      const cursor = new URL(route.request().url()).searchParams.get("cursor")
      cursors.push(cursor ?? "first")
      if (cursor !== null && fails(cursor)) {
        await route.fulfill({
          status: 500,
          json: { detail: "The trades could not be read. Try again." },
        })
        return
      }
      const start = cursor === null ? 0 : Number(cursor)
      const trades = Array.from({ length: 200 }, (_, at) => ({
        ...template,
        trade: start + at,
      }))
      const next = start + 200 < 5_000 ? String(start + 200) : null
      await route.fulfill({ json: { trades, next_cursor: next, total: 5_000 } })
    }
  )
  return cursors
}

test("every cell of the seeded run's trades is the API's, opened from the run's page", async ({
  loggedIn: page,
}) => {
  // Done means 2, its DOM half: the table equals the API, whose half python/tests/server holds.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const expected = await tradesOf(page, key)
  const currency = await currencyOf(page, key)

  await page.goto(`/runs/run?key=${key}`)
  await page.getByTestId("trades").click()

  await expect(page).toHaveURL(`/runs/run/trades?key=${key}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Trades")
  await expect(page.getByTestId("trades-count")).toHaveText(
    `${expected.total} trades`
  )
  await expect(page.getByRole("columnheader")).toHaveText(SHOWN)
  await expectRowsOf(page, expected, currency)
  await grid(page).evaluate((box) => box.scrollTo(0, box.scrollHeight))
  await expect(
    page.locator(`[data-index="${expected.trades.length - 1}"]`)
  ).toBeVisible()
  await expectRowsOf(page, expected, currency)
  await grid(page).evaluate((box) => box.scrollTo(0, 0))
  await screenshot(page, "run-trades")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "run-trades-light")
  expect(errors).toEqual([])
})

test("a header sorts the trades as the API does and says how, the worst MAE first", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const currency = await currencyOf(page, key)
  await page.goto(`/runs/run/trades?key=${key}`)
  const header = page.getByRole("columnheader", { name: "MAE ticks" })
  await expect(header).toHaveAttribute("aria-sort", "none")

  await page.getByTestId("sort-mae_ticks").click()

  await expect(page).toHaveURL(/sort=mae_ticks/)
  await expect(page).toHaveURL(/order=desc/)
  await expect(header).toHaveAttribute("aria-sort", "descending")
  await expectRowsOf(
    page,
    await tradesOf(page, key, { sort: "mae_ticks", order: "desc" }),
    currency
  )

  await page.getByTestId("sort-mae_ticks").click()

  await expect(header).toHaveAttribute("aria-sort", "ascending")
  await expectRowsOf(
    page,
    await tradesOf(page, key, { sort: "mae_ticks" }),
    currency
  )
  await expect(
    page.getByRole("columnheader", { name: "Entry", exact: true })
  ).toHaveAttribute("aria-sort", "none")
})

test("a sort chosen by the keys keeps its focus, and Enter again turns its order", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.goto(`/runs/run/trades?key=${key}`)
  await expect(page.getByTestId("trade-row").first()).toBeVisible()
  const sort = page.getByTestId("sort-mae_ticks")
  const header = page.getByRole("columnheader", { name: "MAE ticks" })

  await sort.focus()
  await page.keyboard.press("Enter")

  await expect(header).toHaveAttribute("aria-sort", "descending")
  await expect(sort).toBeFocused()

  await page.keyboard.press("Enter")

  await expect(header).toHaveAttribute("aria-sort", "ascending")
  await expect(sort).toBeFocused()
})

test("an order read before opens at its first row, wherever the grid was scrolled", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.goto(`/runs/run/trades?key=${key}`)
  const first = page.locator('[data-testid="trade-row"][data-index="0"]')
  await expect(first).toBeVisible()
  await page.getByTestId("sort-mae_ticks").click()
  await expect(page).toHaveURL(/sort=mae_ticks/)
  await page.getByTestId("sort-entry_ts").click()
  await expect(page).not.toHaveURL(/sort=/)
  await grid(page).evaluate((box) => box.scrollTo(0, box.scrollHeight))
  await expect(first).not.toBeInViewport()

  await page.getByTestId("sort-mae_ticks").click()

  await expect(page).toHaveURL(/sort=mae_ticks/)
  await expect(first).toBeInViewport()
})

test("a filter keeps the trades the API keeps, and the address keeps it through a reload", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const currency = await currencyOf(page, key)
  const every = await tradesOf(page, key)
  const losing = await tradesOf(page, key, { pnl_sign: "negative" })
  expect(losing.total).toBeGreaterThan(0)
  await page.goto(`/runs/run/trades?key=${key}`)

  await page.getByRole("combobox", { name: "P&L" }).click()
  await page.getByRole("option", { name: "Losing" }).click()

  await expect(page).toHaveURL(/pnl_sign=negative/)
  const count = `${losing.total} of ${every.total} trades`
  await expect(page.getByTestId("trades-count")).toHaveText(count)
  await expectRowsOf(page, losing, currency)

  await page.reload()

  await expect(page.getByTestId("trades-count")).toHaveText(count)
  await expect(page.getByRole("combobox", { name: "P&L" })).toHaveText("Losing")
  await expectRowsOf(page, losing, currency)
})

test("your check: the losing trades a stop closed, sorted by MAE, show the worst MAE first", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const currency = await currencyOf(page, key)
  const worst = await tradesOf(page, key, {
    pnl_sign: "negative",
    exit_reason: "stop",
    sort: "mae_ticks",
    order: "desc",
  })
  const excursions = worst.trades.map((shown) => shown.mae_ticks)
  expect(excursions.length).toBeGreaterThan(1)
  expect(excursions).toEqual([...excursions].sort((one, other) => other - one))
  await page.goto(`/runs/run/trades?key=${key}`)

  await page.getByRole("combobox", { name: "P&L" }).click()
  await page.getByRole("option", { name: "Losing" }).click()
  await page.getByRole("combobox", { name: "Exit reason" }).click()
  await page.getByRole("option", { name: "Stop" }).click()
  await page.getByTestId("sort-mae_ticks").click()

  await expect(page).toHaveURL(/pnl_sign=negative/)
  await expect(page).toHaveURL(/exit_reason=stop/)
  await expect(page).toHaveURL(/sort=mae_ticks/)
  await expect(page).toHaveURL(/order=desc/)
  const header = page.getByRole("columnheader", { name: "MAE ticks" })
  await expect(header).toHaveAttribute("aria-sort", "descending")
  await expectRowsOf(page, worst, currency)
  await header.scrollIntoViewIfNeeded()
  await expect(header).toBeInViewport()
  await screenshot(page, "run-trades-losing")
})

test("a date out of order is refused at its field, and no trade matches a day with none", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.goto(`/runs/run/trades?key=${key}`)
  const from = page.getByRole("textbox", { name: "From" })
  const to = page.getByRole("textbox", { name: "To" })

  await to.fill("2026-03-05")
  await to.press("Enter")
  await from.fill("2026-03-09")
  await from.press("Enter")

  await expect(page.getByText("Type a date on or before To.")).toBeVisible()
  await expect(page).not.toHaveURL(/start=/)

  await to.fill("2026-03-20")
  await to.press("Enter")

  await expect(page).toHaveURL(/start=2026-03-09/)
  await expect(page).toHaveURL(/end=2026-03-20/)
  await expect(page.getByText("Type a date on or before To.")).toHaveCount(0)

  await from.fill("2026-03-01")
  await from.press("Enter")
  await to.fill("2026-03-02")
  await to.press("Enter")

  await expect(page.getByTestId("trades-count")).toHaveText(
    "No trade matches these filters."
  )
  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page).not.toHaveURL(/start=|end=/)
})

test("a refused date clears once fixed, and Clear filters clears every field and goes to From", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const every = (await tradesOf(page, key)).total
  await page.goto(`/runs/run/trades?key=${key}`)
  const from = page.getByRole("textbox", { name: "From" })
  const to = page.getByRole("textbox", { name: "To" })
  const unreadable = page.getByText("Type a date such as 2026-03-05.")

  await from.fill("x")
  await from.press("Enter")

  await expect(unreadable).toBeVisible()
  await expect(from).toHaveAttribute("aria-invalid", "true")

  await from.fill("")
  await from.press("Enter")

  await expect(unreadable).toHaveCount(0)
  await expect(from).toHaveAttribute("aria-invalid", "false")

  await to.fill("2026-03-01")
  await to.press("Enter")
  await from.fill("x")
  await from.press("Enter")
  await expect(page.getByTestId("trades-count")).toHaveText(
    "No trade matches these filters."
  )

  await page.getByRole("button", { name: "Clear filters" }).click()

  await expect(from).toBeFocused()
  await expect(from).toHaveValue("")
  await expect(to).toHaveValue("")
  await expect(unreadable).toHaveCount(0)
  await expect(page.getByTestId("trades-count")).toHaveText(
    `${every.toLocaleString("en-US")} trades`
  )
})

test("an averaged exit price and a price under a millionth fit their columns whole", async ({
  loggedIn: page,
}) => {
  // A scale-out averages a trade's exits into many places, which every exit price lines up to.
  const key = await theSeededKey(page)
  const seeded = await tradesOf(page, key)
  const [averaged, tiny, ...rest] = seeded.trades
  const trades = [
    { ...averaged, exit_price: "5017.083333333333" },
    { ...tiny, entry_price: "0.000000123" },
    ...rest,
  ]
  await page.route(
    (url) => url.pathname === `/v1/runs/${key}/trades`,
    (route) => route.fulfill({ json: { ...seeded, trades } })
  )
  await page.goto(`/runs/run/trades?key=${key}`)
  const rows = page.getByTestId("trade-row")
  await expect(rows.nth(1)).toBeVisible()

  for (const column of ["Entry price", "Exit price"]) {
    const cells = rows.locator(`td:nth-child(${SHOWN.indexOf(column) + 1})`)
    const clipped = await cells.evaluateAll(
      (found) =>
        found.filter((cell) => cell.scrollWidth > cell.clientWidth).length
    )
    expect(clipped, column).toBe(0)
  }
  await expect(
    rows.nth(0).locator("td").nth(SHOWN.indexOf("Exit price"))
  ).toHaveText("5017.083333333333")
  await expect(
    rows.nth(1).locator("td").nth(SHOWN.indexOf("Entry price"))
  ).toHaveText("0.000000123")
})

test("selecting a row emits selectedTrade with the API's trade, and the keys move it", async ({
  loggedIn: page,
}) => {
  // The step's tests: Playwright selects a trade and asserts the event.
  const key = await theSeededKey(page)
  const expected = await tradesOf(page, key)
  await page.goto(`/runs/run/trades?key=${key}`)
  const rows = page.getByTestId("trade-row")
  await expect(rows.nth(2)).toBeVisible()

  const third = await listenForSelectedTrade(page)
  await rows.nth(2).click()

  expect(await third()).toEqual(expected.trades[2])
  await expect(rows.nth(2)).toHaveAttribute("aria-selected", "true")

  const fourth = await listenForSelectedTrade(page)
  await page.keyboard.press("ArrowDown")

  expect(await fourth()).toEqual(expected.trades[3])
  const next = page.locator('[data-testid="trade-row"][data-index="3"]')
  await expect(next).toHaveAttribute("aria-selected", "true")
  await expect(next).toBeFocused()
  await expect(rows.nth(2)).toHaveAttribute("aria-selected", "false")
  await screenshot(page, "run-trades-selected")
})

test("the column chooser hides and shows a column, and this browser keeps the choice", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.goto(`/runs/run/trades?key=${key}`)
  const fidelity = page.getByRole("columnheader", {
    name: "Fidelity",
    exact: true,
  })
  await expect(fidelity).toBeVisible()

  await page.getByTestId("column-chooser").click()
  await page
    .getByRole("menuitemcheckbox", { name: "Fidelity", exact: true })
    .click()
  await page.getByRole("menuitemcheckbox", { name: "Path fidelity" }).click()
  await screenshot(page, "run-trades-columns")
  await page.keyboard.press("Escape")

  await expect(fidelity).toHaveCount(0)
  await expect(
    page.getByRole("columnheader", { name: "Path fidelity" })
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole("columnheader", { name: "Path fidelity" })
  ).toBeVisible()
  await expect(fidelity).toHaveCount(0)

  await page.getByTestId("column-chooser").click()
  await page
    .getByRole("menuitem", { name: "Show the table's own columns" })
    .click()

  await expect(page.getByRole("columnheader")).toHaveText(SHOWN)
})

test("both exports download the files the API serves, the trades under the table's filter", async ({
  loggedIn: page,
}) => {
  // The Amendment of D-119: Playwright receives both files.
  const key = await theSeededKey(page)
  const losing = await tradesOf(page, key, { pnl_sign: "negative" })
  await page.goto(`/runs/run/trades?key=${key}&pnl_sign=negative`)

  const [trades] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("export-trades").click(),
  ])
  const [executions] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("export-executions").click(),
  ])

  expect(trades.suggestedFilename()).toBe(`demo-${key.slice(0, 12)}-trades.csv`)
  expect(executions.suggestedFilename()).toBe(
    `demo-${key.slice(0, 12)}-executions.csv`
  )
  const tradesFile = await readFile(await trades.path(), "utf-8")
  const served = await page.request.get(`/v1/runs/${key}/trades.csv`, {
    params: { pnl_sign: "negative" },
  })
  expect(tradesFile).toBe(await served.text())
  expect(tradesFile.trim().split("\n")).toHaveLength(losing.total + 1)
  const executionsFile = await readFile(await executions.path(), "utf-8")
  const fills = await page.request.get(`/v1/runs/${key}/executions.csv`)
  expect(executionsFile).toBe(await fills.text())
})

test("the SQL tab answers a query as the API does and says why it refuses a write", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const sql =
    "SELECT exit_reason, count(*) AS trades, sum(pnl) AS pnl FROM trades " +
    "GROUP BY exit_reason ORDER BY exit_reason"
  const write = "COPY (SELECT * FROM trades) TO 'trades.csv'"
  const headers = await csrf(page)
  const answer = queryAnswer.parse(
    await (
      await page.request.post(`/v1/runs/${key}/query`, {
        data: { sql },
        headers,
      })
    ).json()
  )
  const refused = await page.request.post(`/v1/runs/${key}/query`, {
    data: { sql: write },
    headers,
  })
  expect(refused.status()).toBe(400)
  await page.goto(`/runs/run/trades?key=${key}`)

  await page.getByTestId("tab-sql").click()
  await expect(page).toHaveURL(/tab=sql/)
  await page.getByTestId("run-sql").fill(sql)
  await page.getByRole("button", { name: "Run query" }).click()

  await expect(page.getByTestId("run-sql-count")).toHaveText(
    `${answer.rows.length} rows`
  )
  await expect(
    page.getByTestId("run-sql-answer").getByRole("columnheader")
  ).toHaveText(answer.columns.map((column) => column.name))
  const rows = page.getByTestId("run-sql-row")
  await expect(rows).toHaveCount(answer.rows.length)
  for (const [at, row] of answer.rows.entries()) {
    await expect(rows.nth(at).locator("td")).toHaveText(
      row.map((value) =>
        typeof value === "string" ? value : JSON.stringify(value)
      )
    )
  }
  await screenshot(page, "run-trades-sql")
  expect(errors).toEqual([])

  await page
    .getByTestId("run-sql")
    .fill(
      "SELECT count(*) AS trades, list(lots) AS lots, sum(pnl) AS pnl FROM trades"
    )
  await page.getByRole("button", { name: "Run query" }).click()

  await expect(page.getByTestId("run-sql-count")).toHaveText("1 row")
  expect(
    await page
      .getByTestId("run-sql-row")
      .first()
      .locator("td")
      .evaluateAll((cells) =>
        cells.map((cell) => getComputedStyle(cell).textAlign)
      )
  ).toEqual(["right", "left", "right"])

  await page.getByTestId("run-sql").fill(write)
  await page.getByTestId("run-sql").press("Control+Enter")

  await expect(page.getByTestId("run-sql-refusal")).toHaveText(
    refusal.parse(await refused.json()).detail
  )
  // The browser reports the refusal's 400 as it reports every answer of that status.
  expect(errors).toEqual([
    "Failed to load resource: the server responded with a status of 400 (Bad Request)",
  ])
})

test("only the rows near the view are drawn, and a scroll to the end reads the next page", async ({
  loggedIn: page,
}) => {
  // Done means 1's other half: 5,000 trades page through the table without loading them all.
  const key = await theSeededKey(page)
  const cursors = await routeManyTrades(page, key)
  await page.goto(`/runs/run/trades?key=${key}`)
  await expect(page.getByTestId("trades-count")).toHaveText("5,000 trades")
  expect(await page.getByTestId("trade-row").count()).toBeLessThan(60)
  expect(cursors).toEqual(["first"])

  await grid(page).evaluate((box) => box.scrollTo(0, box.scrollHeight))

  await expect.poll(() => cursors).toEqual(["first", "200"])
  await expect(page.locator('[data-index="199"]')).toBeVisible()
  expect(await page.getByTestId("trade-row").count()).toBeLessThan(60)
})

test("scrolled down and right, the header row and the entry column stay, and one row is tabbable", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await routeManyTrades(page, key)
  await page.goto(`/runs/run/trades?key=${key}`)
  await expect(page.getByTestId("trades-count")).toHaveText("5,000 trades")

  // 120 rows down, the row under the header is the 121st, whole.
  await grid(page).evaluate((box) => box.scrollTo(box.scrollWidth, 40 * 120))

  const row = page.locator('[data-testid="trade-row"][data-index="120"]')
  await expect(row).toBeInViewport()
  await expect(
    page.getByRole("columnheader", { name: "Entry", exact: true })
  ).toBeInViewport()
  await expect(
    page.getByRole("columnheader", { name: "Ambiguous" })
  ).toBeInViewport()
  await expect(row.locator("td").first()).toBeInViewport()
  await expect(
    row.locator("td").nth(SHOWN.indexOf("Entry price"))
  ).not.toBeInViewport()
  const tabbable = page.locator('[data-testid="trade-row"][tabindex="0"]')
  await expect(tabbable).toHaveCount(1)
  await expect(tabbable).toHaveAttribute("data-index", "120")
})

test("a page that fails to come keeps the rows read, and Try again reads it", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  let failing = true
  const cursors = await routeManyTrades(page, key, () => failing)
  await page.goto(`/runs/run/trades?key=${key}`)
  await expect(page.getByTestId("trades-count")).toHaveText("5,000 trades")

  await grid(page).evaluate((box) => box.scrollTo(0, box.scrollHeight))

  const again = page.getByRole("button", { name: "Try again" })
  await expect(again).toBeVisible()
  await expect(
    page.getByText("The trades could not be read. Try again.")
  ).toBeVisible()
  await expect(page.locator('[data-index="199"]')).toBeVisible()
  expect(cursors).toEqual(["first", "200"])

  failing = false
  await again.click()

  await expect(again).toHaveCount(0)
  await expect.poll(() => cursors).toEqual(["first", "200", "200"])
  await grid(page).evaluate((box) => box.scrollTo(0, box.scrollHeight))
  await expect.poll(() => cursors).toEqual(["first", "200", "200", "400"])
})

test("more contrast raises the hairlines and the body and subtle text in both themes", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const shown = async () => {
    await page.getByTestId("tab-trades").click()
    const cell = page.getByTestId("trade-row").first().locator("td").nth(1)
    const hairline = await cell.evaluate(
      (td) => getComputedStyle(td).borderBottomColor
    )
    const body = await cell.evaluate((td) => getComputedStyle(td).color)
    await page.getByTestId("tab-sql").click()
    const subtle = await page
      .locator("#run-sql-tables")
      .evaluate((line) => getComputedStyle(line).color)
    return { hairline, body, subtle }
  }
  await page.goto(`/runs/run/trades?key=${key}`)

  const plain = await shown()
  await page.emulateMedia({ contrast: "more" })
  const dark = await shown()
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  const light = await shown()

  expect(plain).toEqual({
    hairline: "rgb(26, 26, 26)",
    body: "rgb(136, 136, 136)",
    subtle: "rgb(124, 124, 124)",
  })
  expect(dark).toEqual({
    hairline: "rgb(85, 85, 85)",
    body: "rgb(184, 184, 184)",
    subtle: "rgb(163, 163, 163)",
  })
  expect(light).toEqual({
    hairline: "rgb(154, 154, 154)",
    body: "rgb(61, 61, 61)",
    subtle: "rgb(77, 77, 77)",
  })
})

test("in a contrast theme the current page, a selected trade, and a job's bar take the highlight", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  await page.emulateMedia({ forcedColors: "active" })
  const systemColour = (name: string) =>
    page.evaluate((colour) => {
      const probe = document.createElement("span")
      probe.style.color = colour
      document.body.append(probe)
      const shown = getComputedStyle(probe).color
      probe.remove()
      return shown
    }, name)

  await page.goto(`/runs/run/trades?key=${key}`)
  await page.getByTestId("trade-row").first().click()

  const highlight = await systemColour("Highlight")
  const current = page.locator('aside a[aria-current="page"]')
  await expect(current).toHaveText("Runs")
  expect(
    await current.evaluate((row) => getComputedStyle(row).borderTopColor)
  ).toBe(highlight)
  expect(
    await page
      .getByTestId("trade-row")
      .first()
      .evaluate((row) => getComputedStyle(row).outlineColor)
  ).toBe(highlight)

  await startDemoJobs(page.request, 1)
  try {
    await page.goto("/")
    const bar = page.locator('[data-slot="progress"]').first()
    await expect(bar).toBeVisible()
    expect(
      await bar
        .locator('[data-slot="progress-indicator"]')
        .evaluate((fill) => getComputedStyle(fill).backgroundColor)
    ).toBe(highlight)
    expect(
      await bar.evaluate((track) => getComputedStyle(track).borderTopColor)
    ).toBe(await systemColour("CanvasText"))
  } finally {
    await cancelActiveJobs(page.request)
  }
})
