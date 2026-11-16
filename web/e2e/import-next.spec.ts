import { readFileSync } from "node:fs"
import path from "node:path"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  EXPORT,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  MORE,
  READ_MS,
  typed,
  verdict,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard of step 5.12 after `import.spec.ts`, in a project that runs once that one's
// has, since it reads the profile and the dataset the first import kept. Done means 3 through the
// page: the seed's second export, which shares two sessions with the first, typed as a path,
// imports by the saved profile's name alone; the third, the first revised, its last bar one lot
// more, dropped on the drop target, differs from what FEAT holds, and Take the file's records
// asks before anything is taken. Then a round of several files (D-102): the seed's two more
// contracts and the revised export, chosen at once, are each reviewed, the two that import as
// they are go in one job, and the file left is reviewed again. It types a path of this machine,
// so it records no clip, and its screenshots mask the path and the roots (D-80).

test("the next export imports by the profile alone, and a revised one asks before its records are taken", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)

  // The second export by its path, through the profile kept by the first import, no mapping.
  await page.goto("/data/import")
  await page.getByRole("button", { name: "Type a path instead" }).click()
  await typed(page, "import-path", path.join(root, "second", EXPORT))
  await chosen(page, "import-profile", "xes-minutes, yours")
  await expect(page.getByTestId("profile-form")).toHaveCount(0)
  await expect(page.getByTestId("profile-instrument")).toHaveText(
    "xes-minutes reads its records as XES, an instrument it carries. Another instrument needs a new profile, under Layout."
  )
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  const account = page.getByTestId("merge-account")
  await expect(account).toContainText("Sessions: 3 new, 0 already held in part")
  await expect(account).toContainText(
    /Records: [\d,]+ new, [\d,]+ held already, 0 differing/
  )
  await expect(page.getByText("Reading the file", { exact: true })).toHaveCount(
    0,
    { timeout: READ_MS }
  )
  await screenshot(page, "import-second-review", [
    page.locator("#import-path"),
    page.getByTestId("import-roots"),
  ])
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-done")).toContainText("held already", {
    timeout: IMPORT_MS,
  })

  // The first export revised, dropped on the drop target: its last bar differs from the one
  // FEAT holds, and taking it asks first, counting the stored record that would give way.
  await page.getByRole("button", { name: "Choose files instead" }).click()
  const revised: Readonly<{ bytes: number[]; name: string }> = {
    bytes: [...readFileSync(path.join(root, "revised", EXPORT))],
    name: EXPORT,
  }
  const dropped = await page.evaluateHandle(({ bytes, name }) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File([new Uint8Array(bytes)], name))
    return transfer
  }, revised)
  await page.dispatchEvent('[data-slot="file-drop"]', "drop", {
    dataTransfer: dropped,
  })
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await expect(verdict(page)).toHaveText(
    "Its records differ from the ones FEAT holds",
    { timeout: READ_MS }
  )
  await expect(account).toContainText("1 differing")
  await page.getByRole("button", { name: "Take the file's records" }).click()
  await expect(
    page.getByRole("button", { name: "Replace 1 stored record" })
  ).toBeVisible()
  const keep = page.getByRole("button", { name: "Keep", exact: true })
  await expect(keep).toBeFocused()
  await inBothThemes(page, "import-take-records")
  await keep.click()
  await expect(
    page.getByRole("button", { name: "Take the file's records" })
  ).toBeFocused()
  await expect(page.getByTestId("import-run")).toBeDisabled()

  // The dataset the imports wrote, on its own page.
  await page.goto("/data/dataset?instrument=XES&provider=ninjatrader")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "XES from ninjatrader"
  )
  await expect(page.getByTestId("dataset-row")).toContainText("1-minute bars")
  // The quality card asks for its own report, which the picture waits for.
  await page.waitForLoadState("networkidle")
  await screenshot(page, "import-dataset")
  expect(errors).toEqual([])
})

test("several exports import in one round, and the file left is reviewed again", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")

  // Three files at once through the picker, each its own contract, read through the saved
  // profile; the contract is the files' names', so its field gives way to a note.
  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (
    await picker
  ).setFiles([
    ...MORE.map((name) => path.join(root, "more", name)),
    path.join(root, "revised", EXPORT),
  ])
  await expect(page.getByTestId("import-chosen")).toContainText(
    `${MORE[0]} and 2 more files`
  )
  await chosen(page, "import-profile", "xes-minutes, yours")
  await expect(page.getByTestId("several-contracts")).toHaveText(
    "Each file's name gives its contract."
  )
  await expect(page.locator("#import-contract")).toHaveCount(0)

  // Each file's own review, the revised one's records differing from those FEAT holds.
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "2 of 3 files import as they are",
    { timeout: READ_MS }
  )
  await expect(
    page.getByText("1 file holds records that differ from the ones FEAT holds")
  ).toBeVisible()
  const rows = page.getByTestId("review-file")
  await expect(rows).toHaveCount(3)
  const revised = rows.filter({ hasText: EXPORT })
  await expect(revised).toContainText("Differs")
  await revised.locator("summary").click()
  await expect(revised.getByTestId("merge-account")).toContainText(
    "1 differing"
  )
  // The round's records that differ are taken for every file at once, behind a confirmation
  // that counts nothing, since two files of one contract dispute the same stored records.
  await page.getByRole("button", { name: "Take the files' records" }).click()
  await expect(
    page.getByRole("button", { name: "Replace the stored records" })
  ).toBeVisible()
  await page.getByRole("button", { name: "Keep", exact: true }).click()
  await inBothThemes(page, "import-several-review")

  // One job imports the two, then the done card counts them and offers the file left.
  await page.getByTestId("import-run").click()
  const round = page.getByTestId("round-account")
  await expect(round).toContainText("2 files imported.", { timeout: IMPORT_MS })
  await expect(page.getByTestId("import-done")).toContainText(
    /Imported [\d,]+ records into XES/
  )
  await screenshot(page, "import-several-done")
  await page.getByTestId("review-left").click()
  await expect(page.getByTestId("import-chosen")).toContainText(EXPORT)
  await expect(page.getByTestId("several-contracts")).toHaveCount(0)
  await expect(verdict(page)).toHaveText(
    "Its records differ from the ones FEAT holds",
    { timeout: READ_MS }
  )
  expect(errors).toEqual([])
})
