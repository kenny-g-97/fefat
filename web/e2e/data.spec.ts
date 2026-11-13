import type { APIRequestContext, Locator, Page } from "@playwright/test"
import { z } from "zod"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The Data pages of step 5.4 against the seeded server: the list of imported data, a row an
// instrument's data from one provider, MES among them with a year of synthetic minutes
// (`scripts/e2e_server.py`), then the catalog's products not imported yet, the instruments, and
// the source guide; a row opens its dataset's page, where Check quality checks the instrument's
// quality as a job (Done means 1, the amended update flow), MES unchecked until then, since no
// other spec runs a sync; its check before it fails at once if one ever does, whichever order
// Playwright runs the files in (it groups those that record video apart). A sync writes reports
// no route removes, so MES stays checked for the specs after it, which read the API's status;
// the spec ends with the builder's checks recorded as a clip (the UI recipe), after its own
// check.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const MES_MINUTES = "synthetic:ohlcv-1m:MES"
const MES_PAGE = "/data/dataset?instrument=MES&provider=synthetic"
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
const stored = z.looseObject({
  id: z.string(),
  provider: z.string(),
  root: z.string(),
  contracts: z.number(),
  first_trade_date: z.string(),
  last_trade_date: z.string(),
  quality: z.string(),
})
const catalogStatus = z.looseObject({
  products: z.array(
    z.looseObject({
      root: z.string(),
      history_from: z.string(),
      recommended_source: z.string(),
      datasets: z.array(stored),
    })
  ),
  unlisted: z.array(stored),
})

type Stored = z.infer<typeof stored>

/** An instrument's data from one provider, as the list shows it in a row. */
type Imported = Readonly<{
  root: string
  provider: string
  from: string
  to: string
  quality: string
}>

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

async function qualityOf(request: APIRequestContext, datasetId: string) {
  const answer = await request.get(`/v1/datasets/${datasetId}/quality`)
  expect(answer.status()).toBe(200)
  return quality.parse(await answer.json())
}

async function catalogOf(request: APIRequestContext) {
  return catalogStatus.parse(await (await request.get("/v1/catalog")).json())
}

/** The rows the API's catalog calls for, in its order: its datasets by instrument and provider,
 * each with the earliest and the latest trade date among them and their quality, stale once
 * one of them is. */
function importedBy(catalog: z.infer<typeof catalogStatus>): Imported[] {
  const datasets = [
    ...catalog.products.flatMap((product) => product.datasets),
    ...catalog.unlisted,
  ]
  const rows = new Map<string, Stored[]>()
  for (const dataset of datasets) {
    const key = `${dataset.root} ${dataset.provider}`
    rows.set(key, [...(rows.get(key) ?? []), dataset])
  }
  return [...rows.values()].map((held) => ({
    root: held[0].root,
    provider: held[0].provider,
    from: held.map((each) => each.first_trade_date).sort()[0],
    to: held
      .map((each) => each.last_trade_date)
      .sort()
      .reverse()[0],
    quality: held.some((each) => each.quality === "stale")
      ? "stale"
      : held[0].quality,
  }))
}

function importedRows(page: Page): Locator {
  return page
    .getByRole("region", { name: "Imported data" })
    .getByTestId("imported-row")
}

function importedRow(page: Page, root: string, provider: string): Locator {
  return importedRows(page)
    .filter({
      has: page.getByTestId("imported-root").getByText(root, { exact: true }),
    })
    .filter({
      has: page
        .getByTestId("provider-chip")
        .getByText(provider, { exact: true }),
    })
}

test("the imported data, the products not imported yet, the instruments, and the sources each show", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  const listed = instruments.parse(
    await (await page.request.get("/v1/instruments")).json()
  )
  const catalog = await catalogOf(page.request)
  const imported = importedBy(catalog)

  await page.goto("/data")

  // From the builder's second check of step 5.4: a simple list of what was imported, a row an
  // instrument's data from one provider, a catalog product's or not; its figures are the API's.
  const rows = importedRows(page)
  expect(imported.map((each) => each.root)).toEqual([
    "MES",
    "BTCUSDT-PERP",
    "ES",
  ])
  await expect(rows.getByTestId("imported-root")).toHaveText(
    imported.map((each) => each.root)
  )
  await expect(rows.getByTestId("provider-chip")).toHaveText(
    imported.map((each) => each.provider)
  )
  await expect(rows.getByTestId("imported-from")).toHaveText(
    imported.map((each) => each.from)
  )
  await expect(rows.getByTestId("imported-to")).toHaveText(
    imported.map((each) => `to ${each.to}`)
  )
  await expect(rows.getByTestId("quality-badge")).toHaveText(
    imported.map((each) => QUALITY_LABELS[each.quality])
  )
  const mes = importedRow(page, "MES", "synthetic")
  await expect(mes.getByTestId("imported-kinds")).toHaveText("1-minute bars")
  await expect(mes).toHaveAttribute("href", MES_PAGE)
  const es = importedRow(page, "ES", "synthetic")
  for (const kind of ["1-minute bars", "1-second bars", "Trades"]) {
    await expect(es.getByTestId("imported-kinds")).toContainText(kind)
  }
  // The catalog's products without data stand under the list, a line each.
  const missing = catalog.products.filter(
    (product) => product.datasets.length === 0
  )
  const lines = page
    .getByRole("region", { name: "Not imported yet" })
    .getByTestId("not-imported")
  expect(catalog.products.length).toBe(4)
  await expect(lines).toHaveCount(missing.length)
  for (const product of missing) {
    await expect(
      lines.filter({
        has: page.getByText(product.root, { exact: true }),
      })
    ).toContainText(
      `History from ${product.history_from}, ${product.recommended_source} recommended`
    )
  }
  expect(missing.map((product) => product.root)).toContain("MCL")
  // The list in the light theme too, for the pull request's readers.
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "data-catalog-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

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
  expect(
    Math.abs(title.y - untouched.y),
    "the title where a page without an action has its own"
  ).toBeLessThanOrEqual(1)
  await action.click()

  await expect(page).toHaveURL("/data/import")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
})

test("a row opens its dataset's page, with the figures the API gives and its chart", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  const catalog = await catalogOf(page.request)
  await page.goto("/data")

  await importedRow(page, "MES", "synthetic").click()

  await expect(page).toHaveURL(MES_PAGE)
  // The title names the provider too: an instrument held from three has three pages.
  await expect(page).toHaveTitle("MES from synthetic – FEAT")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "MES from synthetic"
  )
  const held = page.getByRole("main")
  await expect(held.getByTestId("provider-chip")).toHaveText("synthetic")
  await expect(held.getByTestId("dataset-row")).toContainText("1-minute bars")
  // The table's figures are the API's.
  const minutes = catalog.products
    .flatMap((product) => product.datasets)
    .find((dataset) => dataset.id === MES_MINUTES)
  const product = catalog.products.find((each) => each.root === "MES")
  if (minutes === undefined || product === undefined) {
    throw new Error(`Expected ${MES_MINUTES} in the catalog, got none.`)
  }
  for (const figure of [
    String(minutes.contracts),
    minutes.first_trade_date,
    minutes.last_trade_date,
  ]) {
    await expect(held.getByTestId("dataset-row")).toContainText(figure)
  }
  await expect(held.getByRole("link", { name: "Chart" })).toHaveAttribute(
    "href",
    "/data/chart?instrument=MES&provider=synthetic&timeframe=5m"
  )
  await expect(held).toContainText(
    `History from ${product.history_from}, ${product.recommended_source} recommended`
  )
  // The quality card asks for its own report, which the picture waits for.
  await page.waitForLoadState("networkidle")
  await screenshot(page, "data-dataset")
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(page).toHaveURL("/data")

  await importedRow(page, "ES", "synthetic").click()
  await expect(page).toHaveURL("/data/dataset?instrument=ES&provider=synthetic")
  await expect(page.getByRole("main").getByTestId("dataset-row")).toHaveCount(3)
  expect(errors).toEqual([])
})

test("a row of the list shows its focus ring whole, and steps its surface when pressed, never scaling", async ({
  loggedIn: page,
}) => {
  // Every link scales when pressed (the design brief), which would move a row as wide as its
  // card by 9 px at each end: web/DESIGN.md's Motion steps such a row's surface instead.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/data")
  const row = importedRow(page, "MES", "synthetic")
  await expect(row).toBeVisible()
  await page
    .getByRole("main")
    .getByRole("link", { name: "Import data", exact: true })
    .focus()
  await page.keyboard.press("Tab")
  await expect(row).toBeFocused()

  const ring = await row.evaluate((element) => {
    const style = getComputedStyle(element)
    const reach =
      parseFloat(style.outlineOffset) + parseFloat(style.outlineWidth)
    const card = element.closest("section")
    if (card === null) {
      throw new Error("Expected the row in its card, got none.")
    }
    const around = card.getBoundingClientRect()
    const own = element.getBoundingClientRect()
    return {
      style: style.outlineStyle,
      inside:
        own.left - reach >= around.left && own.right + reach <= around.right,
    }
  })
  expect(ring).toEqual({ style: "solid", inside: true })

  const box = await row.boundingBox()
  if (box === null) {
    throw new Error("Expected the row on the page, got none.")
  }
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  const pressed = await row.evaluate((element) => {
    const probe = document.createElement("div")
    probe.style.backgroundColor = "var(--accent)"
    document.body.append(probe)
    const hoverStep = getComputedStyle(probe).backgroundColor
    probe.remove()
    const style = getComputedStyle(element)
    return {
      transform: style.transform,
      onTheHoverStep: style.backgroundColor === hoverStep,
    }
  })
  // Released away from the row, so that the press opens nothing.
  await page.mouse.move(0, 0)
  await page.mouse.up()

  expect(pressed).toEqual({ transform: "none", onTheHoverStep: true })
  await expect(page).toHaveURL("/data")
})

test("Check quality checks an instrument's quality as a job, and its coverage shows by month", async ({
  loggedIn: page,
}) => {
  // Done means 1, the update flow as amended (D-93) and named since the builder's second check
  // (D-97): MES reads unchecked until a check.
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(MES_PAGE)
  const mes = page.getByRole("main")
  const before = await qualityOf(page.request, MES_MINUTES)
  expect(before.quality, "MES unchecked until this spec checks it").toBe(
    "unchecked"
  )
  await expect(mes.getByTestId("quality-badge")).toHaveText("Unchecked")
  await expect(mes.getByTestId("coverage-month")).toHaveCount(0)
  await expect(mes).toContainText(
    "No quality report yet. Check quality, above, writes one and shows the coverage by month."
  )
  // The strip's legend comes with the strip: before a report its keys explain nothing.
  const legend = mes.getByRole("list", {
    name: "Coverage by month, the legend",
  })
  await expect(legend).toHaveCount(0)

  await mes.getByRole("button", { name: "Check quality" }).click()
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
  await expect(legend).toBeVisible()
  await screenshot(page, "data-dataset-checked")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "data-dataset-checked-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  // The list reads the same quality.
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(
    importedRow(page, "MES", "synthetic").getByTestId("quality-badge")
  ).toHaveText(QUALITY_LABELS[after.quality])
  expect(errors).toEqual([])
})

/** A catalog sync of MES as `GET /v1/jobs` lists it, running or ended. */
function syncOfMes(status: "running" | "succeeded") {
  const ended = status === "succeeded"
  return {
    id: "sync-of-mes",
    kind: "catalog_sync",
    payload: { root: "MES" },
    status,
    progress: ended ? 100 : 40,
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
    finished_at: ended ? "2026-11-12T10:00:09Z" : null,
  }
}

test("an instrument a check covers reads Checking, and its Check quality waits", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/jobs", (route) =>
    route.fulfill({ json: [syncOfMes("running")] })
  )
  await page.route("**/v1/streams/**", (route) => route.abort())

  await page.goto(MES_PAGE)

  const mes = page.getByRole("main")
  await expect(mes.getByTestId("quality-badge")).toHaveText("Checking")
  await expect(
    mes.getByRole("button", { name: "Check quality" })
  ).toBeDisabled()
  await page.waitForLoadState("networkidle")
  await screenshot(page, "data-dataset-checking")
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(
    importedRow(page, "MES", "synthetic").getByTestId("quality-badge")
  ).toHaveText("Checking")
  await expect(
    importedRow(page, "ES", "synthetic").getByTestId("quality-badge")
  ).not.toHaveText("Checking")
})

test("a check refused on one dataset's page is not shown on another's, reached through the browser's history", async ({
  loggedIn: page,
}) => {
  // Step 5.4's code review of the second check: the page kept its refusal as the address went
  // from one dataset to another, since both are one route.
  await page.route("**/v1/catalog/sync", (route) =>
    route.fulfill(problemAnswer(503, "The check could not start."))
  )
  await page.goto("/data")
  await importedRow(page, "MES", "synthetic").click()
  await page.getByRole("link", { name: "Back to Data" }).click()
  await importedRow(page, "ES", "synthetic").click()
  const shown = page.getByRole("main")
  await shown.getByRole("button", { name: "Check quality" }).click()
  await expect(shown.getByRole("alert")).toHaveText(
    "The check could not start."
  )

  // Two entries back is MES's page: the history goes from one dataset's page to another's.
  await page.evaluate(() => window.history.go(-2))

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "MES from synthetic"
  )
  await expect(shown.getByRole("alert")).toHaveCount(0)
})

test("a dataset whose catalog cannot be read again loses its actions with its cards", async ({
  loggedIn: page,
}) => {
  // Step 5.4's code review of the second check: the header's actions stayed, on the catalog's
  // last answer, over the failure that took the cards' place.
  let jobs = [syncOfMes("running")]
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: jobs }))
  await page.route("**/v1/streams/**", (route) => route.abort())
  await page.goto(MES_PAGE)
  const shown = page.getByRole("main")
  await expect(
    shown.getByRole("button", { name: "Check quality" })
  ).toBeVisible()

  // The check ends, which reads the catalog again, and that reading fails. The jobs are read
  // again when the window comes back into view.
  jobs = [syncOfMes("succeeded")]
  await page.route("**/v1/catalog", (route) =>
    route.fulfill(problemAnswer(500, "The catalog could not be read."))
  )
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))

  await expect(shown.getByRole("alert")).toHaveText(
    "The catalog could not be read."
  )
  await expect(
    shown.getByRole("button", { name: "Check quality" })
  ).toHaveCount(0)
  await expect(
    shown.getByRole("link", { name: "Import more data" })
  ).toHaveCount(0)
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

test("a flagged dataset shows its findings, its months held in part, and its last import", async ({
  loggedIn: page,
}) => {
  // Step 5.4's UI verification: the seed reaches no finding, no month held in part, and no last
  // import, so the API's answers are given these here, the page drawn and measured with them.
  const catalog = await catalogOf(page.request)
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
  const row = importedRow(page, "MES", "synthetic")
  await expect(row.getByTestId("quality-badge")).toHaveText("Flagged")
  // The list with a flagged row, measured in each theme, then dark again for the row's page.
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await row.click()
  // The page's title, since the list's badges stay in the page until the dataset's page draws.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "MES from synthetic"
  )

  const mes = page.getByRole("main")
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
  // Opened, so that the findings are pictured and their text is measured with the rest.
  await mes.getByText("2 findings").click()
  await expect(mes.getByRole("cell", { name: "2026-02-18" })).toBeVisible()
  await expect(mes.getByRole("cell", { name: "MESH2026" })).toBeVisible()
  await screenshot(page, "data-dataset-flagged")
  // Measured in each theme, which leaves the page in the light one for its screenshot.
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await screenshot(page, "data-dataset-flagged-light")
})

test("Import more data on a dataset's page leads to the import page with its provider as the preset", async ({
  loggedIn: page,
}) => {
  // From the builder's second check of step 5.4: a way to update a data source with new files.
  // The import page is a placeholder until step 5.12's wizard, which reads the preset.
  await page.goto(MES_PAGE)
  const header = page.getByRole("main")
  const more = header.getByRole("link", { name: "Import more data" })

  await expect(more).toHaveAttribute("href", "/data/import?preset=synthetic")
  const check = await header
    .getByRole("button", { name: "Check quality" })
    .boundingBox()
  const primary = await more.boundingBox()
  if (check === null || primary === null) {
    throw new Error("Expected the page's two actions, got none.")
  }
  expect(
    check.x + check.width,
    "Check quality before the primary action, on one line"
  ).toBeLessThanOrEqual(primary.x)
  expect(
    Math.abs(check.y + check.height / 2 - (primary.y + primary.height / 2))
  ).toBeLessThanOrEqual(1)
  await more.click()

  await expect(page).toHaveURL("/data/import?preset=synthetic")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
})

test("an address that names no data FEAT holds says so, with no actions", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/dataset?instrument=ES&provider=nobody")

  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "FEAT holds no data of ES from nobody. Choose a row of Imported data on the Data page."
  )
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "ES from nobody"
  )
  await expect(page.getByRole("button", { name: "Check quality" })).toHaveCount(
    0
  )
  await expect(
    page.getByRole("link", { name: "Import more data" })
  ).toHaveCount(0)
  await screenshot(page, "data-dataset-unknown")
  // Half an address says what it lacks.
  await page.goto("/data/dataset?instrument=ES")
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "This address needs an instrument and a provider. Choose a row of Imported data on the Data page."
  )
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dataset")
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(page).toHaveURL("/data")
})

test("a store without data invites the import, and lists the catalog's products", async ({
  loggedIn: page,
}) => {
  const catalog = await catalogOf(page.request)
  const empty = {
    ...catalog,
    products: catalog.products.map((product) => ({
      ...product,
      datasets: [],
    })),
    unlisted: [],
  }
  await page.route("**/v1/catalog", (route) => route.fulfill({ json: empty }))

  await page.goto("/data")

  await expect(
    page.getByRole("region", { name: "Imported data" })
  ).toContainText(
    "No data imported yet. Import data, above, brings your own files in."
  )
  await expect(importedRows(page)).toHaveCount(0)
  await expect(
    page
      .getByRole("region", { name: "Not imported yet" })
      .getByTestId("not-imported")
  ).toHaveCount(catalog.products.length)
  await screenshot(page, "data-catalog-empty")
})

test("step 5.4's checks, recorded: Check quality on MES, its chart scrolled back, and the chart's style", async ({
  loggedIn: page,
}) => {
  await page.goto("/")
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Data", exact: true })
    .click()
  await page.waitForTimeout(PAUSE_MS)
  await importedRow(page, "MES", "synthetic").click()
  const mes = page.getByRole("main")
  await page.waitForTimeout(PAUSE_MS)

  await mes.getByRole("button", { name: "Check quality" }).click()
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
