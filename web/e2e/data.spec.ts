import type { APIRequestContext, Page } from "@playwright/test"
import { z } from "zod"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The Data page of step 5.4 against the seeded server: the catalog's products, MES among them
// with a year of synthetic minutes (`scripts/e2e_server.py`), your data, the fixtures' ES and
// bitcoin, the instruments, and the source guide; Update checks a product's quality as a job
// (Done means 1, the amended update flow), MES unchecked until then, since no other spec runs a
// sync; its check before Update fails at once if one ever does, whichever order Playwright runs
// the files in (it groups those that record video apart). A sync writes reports no route
// removes, so MES stays checked for the specs after it, which read the API's status; the spec
// ends with the builder's checks recorded as a clip (the UI recipe), after its own Update.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const MES_MINUTES = "synthetic:ohlcv-1m:MES"
const PAUSE_MS = 500
const QUALITY_LABELS: Readonly<Record<string, string>> = {
  clean: "Clean",
  flagged: "Flagged",
  unchecked: "Unchecked",
  stale: "Stale",
}
const quality = z.object({
  quality: z.string(),
  checked_through: z.string().nullable(),
  months: z.array(
    z.object({
      month: z.string(),
      sessions: z.number(),
      with_records: z.number(),
    })
  ),
})
const instruments = z.array(
  z.object({ root: z.string(), tick_size: z.number() })
)
const storedDatasets = z.array(
  z.looseObject({
    id: z.string(),
    contracts: z.number(),
    first_trade_date: z.string(),
    last_trade_date: z.string(),
  })
)
const catalogStatus = z.looseObject({
  products: z.array(
    z.looseObject({ datasets: z.array(z.looseObject({ id: z.string() })) })
  ),
})

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

async function qualityOf(request: APIRequestContext, datasetId: string) {
  const answer = await request.get(`/v1/datasets/${datasetId}/quality`)
  expect(answer.status()).toBe(200)
  return quality.parse(await answer.json())
}

function rootBlock(page: Page, panel: string, root: string) {
  return page
    .getByRole("region", { name: panel })
    .getByTestId("root-block")
    .filter({ has: page.getByRole("heading", { name: root, exact: true }) })
}

test("the catalog's products, your data, the instruments, and the sources each show", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  const listed = instruments.parse(
    await (await page.request.get("/v1/instruments")).json()
  )

  await page.goto("/data")

  const products = page.getByRole("region", { name: "Catalog products" })
  await expect(products.getByTestId("root-block")).toHaveCount(4)
  const mes = rootBlock(page, "Catalog products", "MES")
  await expect(mes.getByTestId("provider-chip")).toHaveText("synthetic")
  await expect(mes.getByTestId("dataset-row")).toContainText("1-minute bars")
  // The table's figures are the API's.
  const stored = storedDatasets
    .parse(await (await page.request.get("/v1/datasets")).json())
    .find((dataset) => dataset.id === MES_MINUTES)
  if (stored === undefined) {
    throw new Error(`Expected ${MES_MINUTES} among the datasets, got none.`)
  }
  for (const figure of [
    String(stored.contracts),
    stored.first_trade_date,
    stored.last_trade_date,
  ]) {
    await expect(mes.getByTestId("dataset-row")).toContainText(figure)
  }
  await expect(mes.getByRole("link", { name: "Chart" })).toHaveAttribute(
    "href",
    "/data/chart?instrument=MES&provider=synthetic&timeframe=5m"
  )
  await expect(rootBlock(page, "Catalog products", "MCL")).toContainText(
    "No data yet"
  )
  const yours = page.getByRole("region", { name: "Your data" })
  await expect(yours.getByRole("heading", { level: 3 })).toHaveText([
    "BTCUSDT-PERP",
    "ES",
  ])
  await expect(
    rootBlock(page, "Your data", "ES").getByTestId("dataset-row")
  ).toHaveCount(3)
  const table = page
    .getByRole("region", { name: "Instruments" })
    .getByRole("table")
  await expect(table.getByRole("row")).toHaveCount(listed.length + 1)
  const tableOverflow = await table.evaluate((element) =>
    element.parentElement === null
      ? 0
      : element.parentElement.scrollWidth - element.parentElement.clientWidth
  )
  expect(
    tableOverflow,
    "the instruments' table fits its card"
  ).toBeLessThanOrEqual(0)
  await expect(
    table.getByRole("row", { name: /^ES Futures 0\.25 50 1 USD / })
  ).toBeVisible()

  const sources = page.getByRole("region", { name: "Sources" })
  await expect(sources.getByTestId("source-row")).toHaveCount(27)
  const databento = sources
    .getByTestId("source-row")
    .filter({ hasText: "Databento" })
    .first()
  await databento.getByText("Databento", { exact: true }).click()
  await expect(
    databento.getByRole("link", { name: "Terms page" })
  ).toHaveAttribute(
    "href",
    "https://databento.com/legal/databento-user-agreement"
  )
  await expect(
    databento.getByRole("link", {
      name: "Import with Databento DBN batch download",
    })
  ).toHaveAttribute("href", "/data/import?preset=databento")
  await screenshot(page, "data-catalog")

  await databento
    .getByRole("link", { name: "Import with Databento DBN batch download" })
    .click()
  await expect(page).toHaveURL("/data/import?preset=databento")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
  await expect(page.getByText("Not built yet")).toBeVisible()
  await screenshot(page, "data-import")
  // From the builder's check of step 5.4: no way back to Data but the sidebar's row.
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(page).toHaveURL("/data")
  expect(errors).toEqual([])
})

test("Import data stands at the top of the Data page, on its title's line, and leads to the import page", async ({
  loggedIn: page,
}) => {
  // From the builder's second check of step 5.4: the one way to the import was a source's row,
  // at the bottom of the page.
  await page.goto("/lab")
  const untouched = await page.getByRole("heading", { level: 1 }).boundingBox()
  await page.goto("/data")
  const action = page
    .getByRole("main")
    .getByRole("link", { name: "Import data", exact: true })

  await expect(action).toBeInViewport()
  const title = await page.getByRole("heading", { level: 1 }).boundingBox()
  const button = await action.boundingBox()
  const content = await page
    .getByRole("region", { name: "Instruments" })
    .boundingBox()
  if (
    untouched === null ||
    title === null ||
    button === null ||
    content === null
  ) {
    throw new Error("Expected the header and a card on the page, got none.")
  }
  expect(
    Math.abs(button.y + button.height / 2 - (title.y + title.height / 2)),
    "the action centred on the title's line"
  ).toBeLessThanOrEqual(1)
  expect(
    Math.abs(button.x + button.width - (content.x + content.width)),
    "the action ending at the content's right edge"
  ).toBeLessThanOrEqual(1)
  expect(title.y, "the title where a page without an action has its own").toBe(
    untouched.y
  )
  await action.click()

  await expect(page).toHaveURL("/data/import")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
})

test("Update checks a product's quality as a job, and its coverage shows by month", async ({
  loggedIn: page,
}) => {
  // Done means 1, the update flow as amended (D-93): MES reads unchecked until a sync.
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/data")
  const mes = rootBlock(page, "Catalog products", "MES")
  const before = await qualityOf(page.request, MES_MINUTES)
  expect(before.quality, "MES unchecked until this spec updates it").toBe(
    "unchecked"
  )
  await expect(mes.getByTestId("quality-badge")).toHaveText("Unchecked")
  await expect(mes.getByTestId("coverage-month")).toHaveCount(0)

  await mes.getByRole("button", { name: "Update MES" }).click()
  await page.getByTestId("jobs-indicator").click()
  await expect(
    page.getByRole("dialog", { name: "Jobs" }).getByTestId("job-row").first()
  ).toContainText("Quality check")
  await page.keyboard.press("Escape")

  await expect
    .poll(async () => (await qualityOf(page.request, MES_MINUTES)).quality, {
      timeout: 60_000,
    })
    .not.toBe("unchecked")
  const after = await qualityOf(page.request, MES_MINUTES)
  await expect(mes.getByTestId("quality-badge")).toHaveText(
    QUALITY_LABELS[after.quality]
  )
  await expect(mes).toContainText(`Checked through ${after.checked_through}`)
  const [april] = after.months
  await expect(mes.getByTestId("coverage-month")).toHaveCount(12)
  await expect(mes.getByTestId("coverage-month").first()).toHaveAccessibleName(
    `${april.month}: ${april.with_records} of ${april.sessions} sessions with records, no findings`
  )
  await screenshot(page, "data-catalog-checked")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "data-catalog-checked-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("a product a sync is checking reads Checking, and its Update waits", async ({
  loggedIn: page,
}) => {
  const running = {
    id: "sync-of-mes",
    kind: "catalog_sync",
    payload: { root: "MES" },
    status: "running",
    progress: 40,
    message: "Checking the quality of synthetic MES",
    attempt: 1,
    max_attempts: 3,
    worker_pid: null,
    lease_expires_at: null,
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: "2026-11-12T10:00:00Z",
    started_at: "2026-11-12T10:00:01Z",
    finished_at: null,
  }
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: [running] }))
  await page.route("**/v1/streams/**", (route) => route.abort())

  await page.goto("/data")

  const mes = rootBlock(page, "Catalog products", "MES")
  await expect(mes.getByTestId("quality-badge")).toHaveText("Checking")
  await expect(mes.getByRole("button", { name: "Update MES" })).toBeDisabled()
})

test("a section that cannot load its data says why, and the others keep working", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/instruments", (route) =>
    route.fulfill(problemAnswer(500, "The instruments could not be read."))
  )

  await page.goto("/data")

  const failed = page.getByRole("region", { name: "Instruments" })
  await expect(failed.getByRole("alert")).toHaveText(
    "The instruments could not be read."
  )
  await expect(failed.getByRole("button", { name: "Try again" })).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Sources" }).getByTestId("source-row")
  ).toHaveCount(27)
})

test("a flagged product shows its findings, its months held in part, and its last import", async ({
  loggedIn: page,
}) => {
  // Step 5.4's UI verification: the seed reaches no finding, no month held in part, and no last
  // import, so the API's answers are given these here, the page drawn and measured with them.
  const catalog = catalogStatus.parse(
    await (await page.request.get("/v1/catalog")).json()
  )
  const flagged = {
    ...catalog,
    products: catalog.products.map((product) => ({
      ...product,
      datasets: product.datasets.map((dataset) =>
        dataset.id === MES_MINUTES
          ? {
              ...dataset,
              quality: "flagged",
              checked_through: "2026-03-31",
              last_import: "2026-04-01",
            }
          : dataset
      ),
    })),
  }
  const month = { tick_days: 0, second_days: 0, vendor_flagged: 0 }
  const report = {
    id: MES_MINUTES,
    quality: "flagged",
    checked_through: "2026-03-31",
    findings: [
      {
        trade_date: "2026-02-17",
        kind: "gap",
        schema_name: "ohlcv-1m",
        contract: null,
        count: 1,
      },
      {
        trade_date: "2026-02-18",
        kind: "duplicates",
        schema_name: "ohlcv-1m",
        contract: "MESH2026",
        count: 12,
      },
    ],
    findings_total: 2,
    months: [
      {
        ...month,
        month: "2026-01",
        sessions: 20,
        with_records: 20,
        minute_days: 20,
        findings: 0,
      },
      {
        ...month,
        month: "2026-02",
        sessions: 19,
        with_records: 15,
        minute_days: 15,
        findings: 2,
      },
      {
        ...month,
        month: "2026-03",
        sessions: 22,
        with_records: 0,
        minute_days: 0,
        findings: 0,
      },
    ],
  }
  await page.route("**/v1/catalog", (route) => route.fulfill({ json: flagged }))
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) ===
      `/v1/datasets/${MES_MINUTES}/quality`,
    (route) => route.fulfill({ json: report })
  )
  await page.emulateMedia({ reducedMotion: "reduce" })

  await page.goto("/data")

  const mes = rootBlock(page, "Catalog products", "MES")
  await expect(mes.getByTestId("quality-badge")).toHaveText("Flagged")
  await expect(mes).toContainText("Imported, last on 2026-04-01")
  const months = mes.getByTestId("coverage-month")
  await expect(months).toHaveCount(3)
  await expect(months.nth(1)).toHaveAccessibleName(
    "2026-02: 15 of 19 sessions with records, 2 findings"
  )
  await expect(months.nth(2)).toHaveAccessibleName(
    "2026-03: 0 of 22 sessions with records, no findings"
  )
  await expect(mes).toContainText("2026-02-18")
  await expect(mes).toContainText("MESH2026")
  await screenshot(page, "data-catalog-flagged")
  // Measured in each theme, which leaves the page in the light one for its screenshot.
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await screenshot(page, "data-catalog-flagged-light")
})

test("step 5.4's checks, recorded: Update on MES, its chart scrolled back, and the chart's style", async ({
  loggedIn: page,
}) => {
  await page.goto("/")
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Data", exact: true })
    .click()
  const mes = rootBlock(page, "Catalog products", "MES")
  await page.waitForTimeout(PAUSE_MS)

  await mes.getByRole("button", { name: "Update MES" }).click()
  await page.getByTestId("jobs-indicator").click()
  const job = page
    .getByRole("dialog", { name: "Jobs" })
    .getByTestId("job-row")
    .first()
  await expect(job).toContainText("Quality check")
  await expect(job).toContainText("Succeeded", { timeout: 60_000 })
  // A clip shows each moment for a while; nothing here waits on the app.
  await page.waitForTimeout(PAUSE_MS * 2)
  await page.keyboard.press("Escape")
  await expect(mes.getByTestId("coverage-month")).toHaveCount(12)
  await page.waitForTimeout(PAUSE_MS * 2)

  await mes.getByRole("link", { name: "Chart" }).click()
  await chartReady(page)
  const chart = page.getByTestId("price-chart")
  await chart.focus()
  // A few weeks back, as the builder's check says, into the second window.
  for (let screen = 0; screen < 32; screen += 1) {
    await chart.press("PageUp")
    await page.waitForTimeout(PAUSE_MS / 4)
  }
  await chartReady(page)
  await page.getByRole("button", { name: "Chart style" }).click()
  await page.waitForTimeout(PAUSE_MS * 3)
  await page
    .getByRole("dialog", { name: "Chart style" })
    .getByRole("button", { name: "Close" })
    .click()
  await page.waitForTimeout(PAUSE_MS)
})
