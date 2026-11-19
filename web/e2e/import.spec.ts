import path from "node:path"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  continued,
  EXPORT,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  noSidewaysScroll,
  READ_MS,
  shown,
  step,
  stepSays,
  typed,
  verdict,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard of step 5.12, as the stepper of step 5.17 (D-105), against the seeded server
// (`scripts/e2e_server.py`), which writes three NinjaTrader exports of XES, a product FEAT does
// not know, under the import root of its config.toml. The first is chosen through the browser's
// picker, its copy held back across a change of step; read on Layout through a new profile made
// from the NinjaTrader preset in Chicago's time zone, with XES as a new instrument; the review
// says the records run six hours late, and the Layout step says to check the time zone, as its
// field does; corrected to UTC, the file imports, the done card saying what was kept, and leads
// to the chart. Each step is opened by Continue, the list, the keyboard, or the browser's Back,
// and pictured in both themes. The spec writes a dataset, so it runs in a project of its own
// after every other (step 5.12, plan call 12), and `import-next.spec.ts` in one after it. Its
// clip is the click path of the step's checks: nothing in it shows a path of this machine (D-80).

test.use({
  video: { mode: "on", size: { width: 1280, height: 800 } },
  actionTimeout: 15_000,
})

test("a new product's export imports once its time zone is corrected", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
  await shown(page, "file")

  // Done means 2: each step of the list says what it still needs.
  await stepSays(page, "file", "incomplete", "Choose files, or type a path")
  await stepSays(page, "layout", "incomplete", "Choose a profile, or make one")
  await stepSays(page, "instrument", "incomplete", "Waits for Layout")
  await stepSays(page, "review", "incomplete", "Waits for 3 steps")
  await inBothThemes(page, "import-file")

  // Done means 3: on the last step Import stands in Continue's place, disabled, saying why.
  await step(page, "review")
  await expect(page.getByTestId("step-continue")).toHaveCount(0)
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Complete File, Layout, and Instrument first"
  )
  await expect(page.getByTestId("import-missing")).toContainText(
    "Choose files, or type a path"
  )
  await step(page, "file")

  // Done means 1: the first export, chosen as a trader picks it, through the browser's own
  // picker; its copy, held back, outlives two changes of step, then keeps the file.
  let release = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/uploads**", async (route) => {
    await held
    await route.continue()
  })
  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (await picker).setFiles(path.join(root, "first", EXPORT))
  const copying = page.getByText("Copying the file into FEAT's folder", {
    exact: true,
  })
  await expect(copying).toBeVisible()
  await step(page, "layout")
  await step(page, "file")
  await expect(copying).toBeVisible()
  release()
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await page.unroute("**/v1/uploads**")
  await stepSays(page, "file", "complete", EXPORT)

  // The file's rows stand on Layout, where the preset names its columns' roles over them; a
  // new profile is made from it, its base fixed while it is drafted.
  await continued(page, "layout")
  await expect(page.getByTestId("import-rows")).toContainText("column_1", {
    timeout: READ_MS,
  })
  await chosen(page, "import-profile", "ninjatrader")
  await expect(page.getByTestId("import-rows")).toContainText("Timestamp", {
    timeout: READ_MS,
  })
  await stepSays(page, "layout", "complete", "ninjatrader")
  await page.getByTestId("new-profile").click()
  await expect(page.getByTestId("made-from")).toHaveText(
    "Made from ninjatrader"
  )
  await expect(page.getByTestId("use-base")).toHaveText(
    "Use ninjatrader as it is"
  )
  await typed(page, "profile-name", "xes-minutes")
  await typed(page, "profile-time-zone", "America/Chicago")

  // A column's role taken away is asked for under Layout, and given back.
  await chosen(page, "import-role-5", "Not read")
  await stepSays(
    page,
    "layout",
    "incomplete",
    "Choose the column of the volume"
  )
  await chosen(page, "import-role-5", "Volume")
  await stepSays(page, "layout", "complete", "xes-minutes, new")
  // The rows scroll inside their card, never the page.
  await noSidewaysScroll(page)
  await inBothThemes(page, "import-layout")

  // A new instrument, which the step asks of field by field.
  await continued(page, "instrument")
  await page.getByRole("radio", { name: "A new instrument" }).click()
  await stepSays(page, "instrument", "incomplete", "4 things to give")
  await typed(page, "instrument-root", "XES")
  await typed(page, "instrument-tick", "0.25")
  await typed(page, "instrument-point", "50")
  await typed(page, "instrument-first-trade-date", "2010-01-04")
  await stepSays(page, "instrument", "complete", "XES, new")
  await inBothThemes(page, "import-instrument")

  // The review says the records run six hours late, in which time zone they were read, and the
  // Layout step loses its check for it, an alert; Import says which step to complete.
  await continued(page, "review")
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
  await stepSays(page, "layout", "incomplete", "Check the time zone")
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Check the time zone under Layout first"
  )
  await inBothThemes(page, "import-time-zone-late")

  // Back to Layout by the list, where the time zone's field says so too.
  await step(page, "layout")
  await expect(page.locator("#profile-time-zone")).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  await expect(page.locator("#profile-time-zone-refusal")).toHaveText(
    "The records run 6 hours late against their calendar"
  )

  // Corrected to UTC, the file imports as it is.
  await typed(page, "profile-time-zone", "UTC")
  await step(page, "review")
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  await expect(page.getByTestId("review-offset")).toHaveCount(0)
  await stepSays(page, "layout", "complete", "xes-minutes, new")
  await stepSays(page, "review", "complete", "Ready to import")
  await expect(page.getByTestId("first-records")).toContainText("XESH2026")
  const account = page.getByTestId("merge-account")
  await expect(account).toContainText("XES from ninjatrader, 1-minute bars")
  await expect(account).toContainText("Sessions: 5 new, 0 already held in part")
  await expect(page.getByTestId("import-waits")).toHaveCount(0)
  await expect(page.getByTestId("import-run")).toBeEnabled()
  await noSidewaysScroll(page)
  await inBothThemes(page, "import-review")

  // The browser's Back returns to Layout with the draft whole.
  await page.goBack()
  await shown(page, "layout")
  await expect(page.locator("#profile-name")).toHaveValue("xes-minutes")
  await expect(page.locator("#profile-time-zone")).toHaveValue("UTC")
  await expect(page.locator("#profile-time-zone")).toHaveAttribute(
    "aria-invalid",
    "false"
  )
  // Back, named for the step it opens, returns to File, the file still chosen.
  await expect(page.getByTestId("step-back")).toHaveText("Back to File")
  await page.getByTestId("step-back").click()
  await shown(page, "file")
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await stepSays(page, "file", "complete", EXPORT)

  // The list answers the keyboard: Tab to Instrument and Enter, the focus on its card.
  await page.getByTestId("step-layout").focus()
  await page.keyboard.press("Tab")
  await expect(page.getByTestId("step-instrument")).toBeFocused()
  await expect(page.getByTestId("step-instrument")).toHaveCSS(
    "outline-style",
    "solid"
  )
  await page.keyboard.press("Enter")
  await shown(page, "instrument")
  await expect(page.getByTestId("step-card-instrument")).toBeFocused()
  await expect(page.locator("#instrument-root")).toHaveValue("XES")

  // A double click on Continue opens the review alone, and Import, which stands where Continue
  // stood, ignores the second click of a double click.
  await page.getByTestId("step-continue").dblclick()
  await shown(page, "review")
  await page.getByTestId("import-run").dispatchEvent("click", { detail: 2 })
  await expect(page.getByTestId("import-job")).toHaveCount(0)
  await expect(page.getByTestId("import-run")).toBeEnabled()

  // Imported, the done card says what was kept, and outlives a change of step.
  await page.getByTestId("import-run").click()
  const done = page.getByTestId("import-done")
  await expect(done).toContainText("Imported", { timeout: IMPORT_MS })
  await expect(done).toContainText(
    "The new profile is kept and the new instrument saved"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(verdict(page)).toHaveCount(0)
  await stepSays(page, "review", "complete", "Imported")
  await expect(page.getByTestId("import-waits")).toHaveText("Imported")
  await screenshot(page, "import-done")
  await step(page, "file")
  await step(page, "review")
  await expect(done).toContainText(
    "The new profile is kept and the new instrument saved"
  )

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
