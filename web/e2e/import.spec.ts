import path from "node:path"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  EXPORT,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  READ_MS,
  typed,
  verdict,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard of step 5.12 against the seeded server (`scripts/e2e_server.py`), which
// writes three NinjaTrader exports of XES, a product FEAT does not know, under the import root
// of its config.toml. Done means 1: the first is chosen through the browser's picker and copied
// in, read through a new profile made from the NinjaTrader preset in Chicago's time zone, with
// XES as a new instrument; the review says the records run six hours late, and the time zone's
// field says so too; corrected to UTC, the file imports, the done card saying what was kept, and
// leads to the chart. The spec writes a dataset, so it runs in a project of its own after every
// other (plan call 12), and `import-next.spec.ts` in one after it. Its clip is the click path of
// the step's checks: nothing in it shows a path of this machine (D-80).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

test("a new product's export imports once its time zone is corrected", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
  await expect(page.getByTestId("import-missing")).toContainText(
    "Choose files, or type a path"
  )
  await inBothThemes(page, "import-empty")

  // The first export, chosen as a trader picks it, through the browser's own picker.
  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (await picker).setFiles(path.join(root, "first", EXPORT))
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await expect(page.getByTestId("import-rows")).toContainText("column_1", {
    timeout: READ_MS,
  })

  // The preset names its columns' roles over the rows; a new profile is made from it, its base
  // fixed while it is drafted.
  await chosen(page, "import-profile", "ninjatrader")
  await expect(page.getByTestId("import-rows")).toContainText("Timestamp", {
    timeout: READ_MS,
  })
  await page.getByTestId("new-profile").click()
  await expect(page.getByTestId("made-from")).toHaveText(
    "Made from ninjatrader"
  )
  await expect(page.getByTestId("use-base")).toHaveText(
    "Use ninjatrader as it is"
  )
  await typed(page, "profile-name", "xes-minutes")
  await typed(page, "profile-time-zone", "America/Chicago")

  // A column's role taken away is asked for, and given back.
  await chosen(page, "import-role-5", "Not read")
  await expect(page.getByTestId("import-missing")).toContainText(
    "Choose the column of the volume"
  )
  await chosen(page, "import-role-5", "Volume")
  await page.getByRole("radio", { name: "A new instrument" }).click()
  await typed(page, "instrument-root", "XES")
  await typed(page, "instrument-tick", "0.25")
  await typed(page, "instrument-point", "50")
  await typed(page, "instrument-first-trade-date", "2010-01-04")

  // The review says the records run six hours late, in which time zone they were read, and the
  // time zone's field says so too.
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
  await expect(page.locator("#profile-time-zone")).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  await expect(page.locator("#profile-time-zone-refusal")).toHaveText(
    "The records run 6 hours late against their calendar"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await screenshot(page, "import-time-zone-late")

  // Corrected to UTC, the file imports as it is.
  await typed(page, "profile-time-zone", "UTC")
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  await expect(page.getByTestId("review-offset")).toHaveCount(0)
  await expect(page.locator("#profile-time-zone")).toHaveAttribute(
    "aria-invalid",
    "false"
  )
  await expect(page.getByTestId("first-records")).toContainText("XESH2026")
  const account = page.getByTestId("merge-account")
  await expect(account).toContainText("XES from ninjatrader, 1-minute bars")
  await expect(account).toContainText("Sessions: 5 new, 0 already held in part")
  await inBothThemes(page, "import-review")
  await page.getByTestId("import-run").click()
  const done = page.getByTestId("import-done")
  await expect(done).toContainText("Imported", { timeout: IMPORT_MS })
  await expect(done).toContainText(
    "The new profile is kept and the new instrument saved"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(verdict(page)).toHaveCount(0)
  await screenshot(page, "import-done")

  // The jobs drawer lists the import with the jobs.
  await page.getByTestId("jobs-indicator").click()
  const drawer = page.getByRole("dialog", { name: "Jobs" })
  const imports = drawer.getByTestId("job-row").filter({ hasText: "Import" })
  await expect(imports.first()).toContainText("Succeeded")
  await page.keyboard.press("Escape")
  await expect(drawer).toHaveCount(0)

  // The chart, as the done card leads to it.
  await expect(page.getByTestId("open-dataset")).toHaveAttribute(
    "href",
    "/data/dataset?instrument=XES&provider=ninjatrader"
  )
  await page.getByTestId("open-chart").click()
  await chartReady(page)
  await expect(page.getByTestId("readout-contract")).toHaveText("XESH2026")
  await screenshot(page, "import-chart")
  expect(errors).toEqual([])
})
