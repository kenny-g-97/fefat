import path from "node:path"
import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard of step 5.12 against the seeded server (`scripts/e2e_server.py`), which
// writes two NinjaTrader exports of XES, a product FEAT does not know, under the import root of
// its config.toml, the second sharing two sessions with the first. Done means 1: the first is
// chosen and copied in, read through a new profile made from the NinjaTrader preset in
// Chicago's time zone, with XES as a new instrument; the review says the records run six hours
// late and names the time zone; corrected to UTC, the file imports, and the job's card leads to
// the dataset and its chart. Done means 3 through the page: the second, typed as a path, imports
// by the saved profile's name alone, the review counting the sessions it adds and the records
// FEAT holds already. The spec writes a dataset, so it runs in a project of its own after every
// other (plan call 12); its screenshots mask the paths of this machine (D-80).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const EXPORT = "XES 03-26.Last.txt"
const READ_MS = 60_000
const IMPORT_MS = 180_000
const settings = z.looseObject({
  server: z.looseObject({ import_roots: z.array(z.string()).min(1) }),
})

/** The seed's import root, as the server's settings name it. */
async function importRoot(page: Page): Promise<string> {
  const answer = await page.request.get("/v1/settings")
  const [root] = settings.parse(await answer.json()).server.import_roots
  if (root === undefined) {
    throw new Error("Expected the seed's import root, got none.")
  }
  return root
}

/** Type `text` into the field `id` and keep it, as Enter keeps a wizard's field. */
async function typed(page: Page, id: string, text: string) {
  const field = page.locator(`#${id}`)
  await field.fill(text)
  await field.press("Enter")
}

/** Choose `option` in the select `id`. */
async function chosen(page: Page, id: string, option: string) {
  await page.locator(`#${id}`).click()
  await page.getByRole("option", { name: option, exact: true }).click()
}

function verdict(page: Page): Locator {
  return page.getByTestId("review-verdict")
}

test("a new product's export imports once its time zone is corrected, and its next by the profile alone", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
  await expect(page.getByTestId("import-missing")).toContainText(
    "Choose a file, or type its path"
  )

  // The first export, chosen as a trader picks it, copied into FEAT's folder.
  await page
    .locator("#import-file-input")
    .setInputFiles(path.join(root, "first", EXPORT))
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await expect(page.getByTestId("import-rows")).toContainText("column_1", {
    timeout: READ_MS,
  })

  // A new profile from the NinjaTrader preset, read in Chicago's time zone, with XES new.
  await chosen(page, "import-profile", "ninjatrader")
  await page.getByTestId("new-profile").click()
  await typed(page, "profile-name", "xes-minutes")
  await typed(page, "profile-time-zone", "America/Chicago")
  await page.getByRole("radio", { name: "A new instrument" }).click()
  await typed(page, "instrument-root", "XES")
  await typed(page, "instrument-tick", "0.25")
  await typed(page, "instrument-point", "50")
  await typed(page, "instrument-first-trade-date", "2010-01-04")

  // The review says the records run six hours late, and in which time zone they were read.
  await expect(verdict(page)).toHaveText("It would be refused", {
    timeout: READ_MS,
  })
  const offset = page.getByTestId("review-offset")
  await expect(offset).toContainText(
    "The records run 6 hours late against their calendar"
  )
  await expect(offset).toContainText(
    "check the time zone of the file's times, America/Chicago"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await screenshot(page, "import-time-zone-late")

  // Corrected to UTC, the file imports as it is.
  await typed(page, "profile-time-zone", "UTC")
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  await expect(page.getByTestId("review-offset")).toHaveCount(0)
  await expect(page.getByTestId("first-records")).toContainText("XESH2026")
  await expect(page.getByTestId("merge-account")).toContainText(
    "ninjatrader/ohlcv-1m/root=XES"
  )
  await screenshot(page, "import-review")
  // The review in the light theme too, for the pull request's readers.
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "import-review-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-done")).toContainText("Imported", {
    timeout: IMPORT_MS,
  })
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await screenshot(page, "import-done")

  // The second export by its path, through the profile kept by the first import, no mapping.
  await page.goto("/data/import")
  await page.getByRole("button", { name: "Type a path instead" }).click()
  await typed(page, "import-path", path.join(root, "second", EXPORT))
  await chosen(page, "import-profile", "xes-minutes, yours")
  await expect(page.getByTestId("profile-form")).toHaveCount(0)
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  const account = page.getByTestId("merge-account")
  await expect(account).toContainText("Sessions: 3 new, 0 extended")
  await expect(account).toContainText(
    /Records: [\d,]+ new, [\d,]+ held already, 0 differing/
  )
  await screenshot(page, "import-second-review", [
    page.locator("#import-path"),
    page.getByTestId("import-roots"),
  ])
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-done")).toContainText("held already", {
    timeout: IMPORT_MS,
  })

  // The dataset and its chart, as the done card leads to them.
  const dataset = "/data/dataset?instrument=XES&provider=ninjatrader"
  await expect(page.getByTestId("open-dataset")).toHaveAttribute(
    "href",
    dataset
  )
  await page.getByTestId("open-chart").click()
  await chartReady(page)
  await expect(page.getByTestId("readout-contract")).toHaveText("XESH2026")
  await screenshot(page, "import-chart")
  await page.goto(dataset)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "XES from ninjatrader"
  )
  expect(errors).toEqual([])
})
