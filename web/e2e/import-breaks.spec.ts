import path from "node:path"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  READ_MS,
  verdict,
  WITH_A_BREAK,
  WITHOUT_A_BREAK,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard's correction of bars in a break (step 5.15), in a project that runs after
// `import-next.spec.ts`'s, since it reads the profile `import.spec.ts` kept. It chooses files
// through the picker alone, so no path of this machine shows, and records its clip, the click
// path of your check (the UI recipe).
test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

// Step 5.15 (ADR-0022): the seed's exports under `breaks`, chosen through the picker so that no
// path of this machine shows. One file whose break after 02-03 holds nine bars, the last
// closing at the next open, is refused for them alone; you leave them out behind an inline
// confirmation, take it back, approve again, and import. Then a round of two such files and
// one without them: one approval for both, and one job that imports the three.

test("a file with bars in a break imports without them once you approve", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")

  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (await picker).setFiles(path.join(root, "breaks", WITH_A_BREAK[0]))
  await expect(page.getByTestId("import-chosen")).toContainText(WITH_A_BREAK[0])
  await chosen(page, "import-profile", "xes-minutes, yours")

  // The refusal, worded by the wizard from the server's counts and trade dates.
  await expect(verdict(page)).toHaveText(
    "It would be refused for its bars in a break",
    { timeout: READ_MS }
  )
  const box = page.getByTestId("breaks-account")
  await expect(box).toContainText(
    "Breaks: 9 bars in the break after the trade date 2026-02-03"
  )
  await expect(box).toContainText(
    "Sessions beside: 2026-02-03, 2026-02-04, 2,769 records in all"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()

  // Leaving them out asks first, counting the records that go.
  const offer = page.getByRole("button", {
    name: "Leave out the bars in a break",
  })
  await offer.click()
  const confirm = page.getByRole("button", { name: "Leave out 2,769 records" })
  await expect(confirm).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Keep", exact: true })
  ).toBeFocused()
  await inBothThemes(page, "import-leave-out")
  await confirm.click()
  await expect(verdict(page)).toHaveText(
    "It imports without its bars in a break",
    { timeout: READ_MS }
  )
  const leaveOut = page.getByTestId("leave-out")
  await expect(leaveOut).toContainText(
    "These bars and the sessions beside them are left out of the import, 2,769 records in all."
  )
  await expect(
    page.getByText("Reading your latest change", { exact: true })
  ).toHaveCount(0, { timeout: READ_MS })
  await inBothThemes(page, "import-left-out")

  // The way back refuses the file again; approved once more, it imports.
  await page.getByRole("button", { name: "Leave nothing out" }).click()
  await expect(verdict(page)).toHaveText(
    "It would be refused for its bars in a break",
    { timeout: READ_MS }
  )
  await offer.click()
  await confirm.click()
  await expect(verdict(page)).toHaveText(
    "It imports without its bars in a break",
    { timeout: READ_MS }
  )
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-left-out")).toHaveText(
    "Left out 2,769 records of 2 sessions beside bars in a break, as you approved.",
    { timeout: IMPORT_MS }
  )
  await screenshot(page, "import-left-out-done")
  expect(errors).toEqual([])
})

test("a round leaves out the files' bars in a break with one approval", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")

  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (
    await picker
  ).setFiles(
    [WITH_A_BREAK[1], WITH_A_BREAK[2], WITHOUT_A_BREAK].map((name) =>
      path.join(root, "breaks", name)
    )
  )
  await chosen(page, "import-profile", "xes-minutes, yours")

  // Each file's own review; the two with bars in a break show them, with no offer of their own.
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "1 of 3 files import as they are",
    { timeout: READ_MS }
  )
  await expect(
    page.getByText("2 files would be refused for their bars in a break")
  ).toBeVisible()
  const row = page
    .getByTestId("review-file")
    .filter({ hasText: WITH_A_BREAK[1] })
  await expect(row).toContainText("Bars in a break")
  // The row's own summary; its review holds the calendar check's, which lists those bars.
  await row.locator("summary").first().click()
  await expect(row.getByTestId("breaks-account")).toContainText(
    "Sessions beside: 2026-02-03, 2026-02-04, 2,769 records in all"
  )
  await expect(row.getByTestId("leave-out")).toHaveCount(0)

  // One approval for the round, counting files, since two files of one contract share sessions.
  await page
    .getByRole("button", { name: "Leave out the files' bars in a break" })
    .click()
  const confirm = page.getByRole("button", {
    name: "Leave them out of 2 files",
  })
  await expect(confirm).toBeVisible()
  await inBothThemes(page, "import-several-leave-out")
  await confirm.click()
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "3 of 3 files import as they are",
    { timeout: READ_MS }
  )
  await expect(page.getByTestId("leave-out")).toContainText(
    "The bars in a break of 2 files and the sessions beside them are left out of the import; each file's row says which."
  )
  await inBothThemes(page, "import-several-left-out")

  // One job imports the three, and sums what it left out.
  await expect(page.getByTestId("import-run")).toHaveText("Import 3 files")
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("round-account")).toContainText(
    "3 of 3 files imported",
    { timeout: IMPORT_MS }
  )
  await expect(page.getByTestId("import-left-out")).toHaveText(
    "Left out 5,538 records of 4 sessions beside bars in a break, as you approved."
  )
  await screenshot(page, "import-several-left-out-done")
  expect(errors).toEqual([])
})
