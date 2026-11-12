import type { APIRequestContext, Page } from "@playwright/test"
import { z } from "zod"
import { chartReady } from "./support/chart.ts"
import { expect, test } from "./support/fixtures.ts"
import { cancelActiveJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The Data page of step 5.4 against the seeded server: the catalog's products, MES among them
// with a year of synthetic minutes (`scripts/e2e_server.py`), your data, the fixtures' ES and
// bitcoin, the instruments, and the source guide; Update checks a product's quality as a job
// (Done means 1, the amended update flow), MES unchecked until then, since no spec before this
// one runs a sync (the specs run in file order on one worker). A sync writes reports no route
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

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

function consoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  page.on("pageerror", (error) => errors.push(error.message))
  return errors
}

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
  await expect(mes.getByRole("link", { name: "Chart" })).toHaveAttribute(
    "href",
    "/data/chart?instrument=MES&provider=synthetic"
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
  expect(errors).toEqual([])
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
  ).toContainText("Catalog update")
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
  await expect(job).toContainText("Catalog update")
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
  for (let screen = 0; screen < 12; screen += 1) {
    await chart.press("PageUp")
    await page.waitForTimeout(PAUSE_MS / 2)
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
