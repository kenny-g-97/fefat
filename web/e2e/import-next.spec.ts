import { readFileSync } from "node:fs"
import path from "node:path"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  continued,
  EXPORT,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  MORE,
  READ_MS,
  shown,
  signOf,
  step,
  stepSays,
  typed,
  verdict,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

/** A file the server kept, as its upload answers. */
const uploaded = z.looseObject({ id: z.string(), name: z.string() })
/** The round Import sends, by its files' uploads. */
const sentRound = z.looseObject({
  sources: z.array(z.looseObject({ upload_id: z.string() })),
})

// The import wizard of step 5.12 after `import.spec.ts`, in a project that runs once that one's
// has, since it reads the profile and the dataset the first import kept. The seed's second
// export, which shares two sessions with the first, typed as a path, imports by the saved
// profile's name alone; the third, the first revised, its last bar one lot more, dropped on the
// drop target, differs from what FEAT holds, and Take the file's records asks before anything is
// taken. Then a round of several files (D-102): the seed's two more contracts and the revised
// export, chosen at once, are each reviewed, and Import waits until the revised file has a
// decision (D-105), skipped under the rows or in its own row; the two that import go in one job,
// and the file left is reviewed again. It types a path of this machine, so it records no clip,
// and its screenshots mask the path and the roots (D-80).

test.use({ actionTimeout: 15_000 })

test("the next export imports by the profile alone, and a revised one asks before its records are taken", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)

  // The second export by its path, through the profile kept by the first import, no mapping.
  await page.goto("/data/import")
  await shown(page, "file")
  await page.getByRole("button", { name: "Type a path instead" }).click()
  await typed(page, "import-path", path.join(root, "second", EXPORT))
  // The list names the file alone, never the folder it was typed in (D-80).
  await stepSays(page, "file", "complete", EXPORT)
  await continued(page, "layout")
  await chosen(page, "import-profile", "xes-minutes, yours")
  await expect(page.getByTestId("profile-form")).toHaveCount(0)
  await continued(page, "instrument")
  await expect(page.getByTestId("profile-instrument")).toHaveText(
    "xes-minutes reads its records as XES, an instrument it carries. Another instrument needs a new profile, under Layout."
  )
  await continued(page, "review")
  await expect(verdict(page)).toHaveText("It imports as it is", {
    timeout: READ_MS,
  })
  await expect.poll(() => signOf(verdict(page))).toBe("positive")
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
  await step(page, "file")
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
  await step(page, "review")
  await expect(verdict(page)).toHaveText(
    "Its records differ from the ones FEAT holds",
    { timeout: READ_MS }
  )
  await expect.poll(() => signOf(verdict(page))).toBe("negative")
  // One file alone has no Skip: Import waits, saying why (D-105).
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Its records differ from the ones FEAT holds"
  )
  await expect(
    page.getByRole("button", { name: "Skip this file" })
  ).toHaveCount(0)
  await expect(account).toContainText("1 differing")
  await page.getByRole("button", { name: "Take the file's records" }).click()
  await expect(
    page.getByRole("button", { name: "Replace 1 stored record" })
  ).toBeVisible()
  const keep = page.getByRole("button", { name: "Keep", exact: true })
  await expect(keep).toBeFocused()
  await inBothThemes(page, "import-take-records")
  await keep.click()
  const take = page.getByRole("button", { name: "Take the file's records" })
  await expect(take).toBeFocused()
  // Taken, the way back takes the focus from the confirm it replaces, and pressed, gives it
  // to the trigger again (step 5.15); the file, read again, differs as before, and Import
  // stays disabled for it.
  await take.click()
  await page.getByRole("button", { name: "Replace 1 stored record" }).click()
  const stored = page.getByRole("button", { name: "Keep the stored records" })
  await expect(stored).toBeFocused()
  await stored.click()
  await expect(take).toBeFocused()
  await expect(verdict(page)).toHaveText(
    "Its records differ from the ones FEAT holds",
    { timeout: READ_MS }
  )
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

test("a round waits for a decision on the file that differs, then imports the others", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  // The id the server gives each file it keeps, by the file's name.
  // Read on Playwright's side, since the browser drops the answer to a large upload.
  const ids = new Map<string, string>()
  await page.route("**/v1/uploads**", async (route) => {
    const response = await route.fetch()
    const file = uploaded.parse(await response.json())
    ids.set(file.name, file.id)
    await route.fulfill({ response })
  })
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
  await stepSays(page, "file", "complete", "3 files")
  await continued(page, "layout")
  await chosen(page, "import-profile", "xes-minutes, yours")
  await continued(page, "instrument")
  await expect(page.getByTestId("several-contracts")).toHaveText(
    "Each file's name gives its contract."
  )
  await expect(page.locator("#import-contract")).toHaveCount(0)
  await stepSays(page, "instrument", "complete", "XES")

  // Each file's own review: the two that import read Imports in the positive, and the revised
  // one says on its row, unopened, what stops it, in the negative (D-105).
  await continued(page, "review")
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "2 of 3 files import as they are",
    { timeout: READ_MS }
  )
  await expect(
    page.getByText("1 file holds records that differ from the ones FEAT holds")
  ).toBeVisible()
  const rows = page.getByTestId("review-file")
  await expect(rows).toHaveCount(3)
  const revisedRow = rows.filter({ hasText: EXPORT })
  const revisedAside = revisedRow.getByTestId("review-file-aside")
  await expect(revisedAside).toHaveText("Differs")
  await expect.poll(() => signOf(revisedAside)).toBe("negative")
  const reason = revisedRow.getByTestId("review-file-reason")
  await expect(reason).toBeVisible()
  await expect(reason).toHaveText(
    /^Its records differ from the ones FEAT holds: 1 record on 2026-02-\d\d$/
  )
  await expect.poll(() => signOf(reason)).toBe("negative")
  const importing = rows
    .filter({ hasText: MORE[0] })
    .getByTestId("review-file-aside")
  await expect(importing).toHaveText("Imports")
  await expect.poll(() => signOf(importing)).toBe("positive")

  // Import waits, saying how many files wait for a decision, and the Review step says so too.
  const run = page.getByTestId("import-run")
  await expect(run).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Decide what to do with 1 file first"
  )
  await stepSays(page, "review", "incomplete", "1 file waits for your decision")

  // The round's records that differ are taken for every file at once, behind a confirmation
  // that counts nothing, since two files of one contract dispute the same stored records.
  await revisedRow.locator("summary").first().click()
  await expect(revisedRow.getByTestId("merge-account")).toContainText(
    "1 differing"
  )
  await page.getByRole("button", { name: "Take the files' records" }).click()
  await expect(
    page.getByRole("button", { name: "Replace the stored records" })
  ).toBeVisible()
  await page.getByRole("button", { name: "Keep", exact: true }).click()
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-several-review")

  // Skip the 1 file, under the rows: Import names the two it sends; Skip none takes it back.
  const skipAll = page.getByRole("button", { name: "Skip the 1 file" })
  await skipAll.click()
  const skipNone = page.getByRole("button", { name: "Skip none" })
  await expect(skipNone).toBeFocused()
  await expect(revisedAside).toHaveText("Skipped")
  await expect(reason).toHaveCount(0)
  await expect(page.getByText("1 file is skipped, as you chose")).toBeVisible()
  await expect(run).toHaveText("Import 2 files")
  await expect(run).toBeEnabled()
  await expect(page.getByTestId("import-waits")).toHaveCount(0)
  await stepSays(page, "review", "complete", "2 files to import")
  await inBothThemes(page, "import-several-skipped")
  await skipNone.click()
  await expect(skipAll).toBeFocused()
  await expect(run).toBeDisabled()

  // Skip this file, in its own row, the way back taking the focus.
  await revisedRow.getByRole("button", { name: "Skip this file" }).click()
  await expect(
    revisedRow.getByRole("button", { name: "Do not skip" })
  ).toBeFocused()
  await expect(run).toHaveText("Import 2 files")
  await expect(run).toBeEnabled()

  // One job imports the two; the skipped file is never sent, and the done card counts it.
  const sent = page.waitForRequest(
    (request) =>
      request.url().endsWith("/v1/imports") && request.method() === "POST"
  )
  await run.click()
  const body = sentRound.parse((await sent).postDataJSON())
  expect(body.sources.map((source) => source.upload_id)).toEqual(
    MORE.map((name) => ids.get(name))
  )
  expect(ids.get(EXPORT)).toBeDefined()
  const round = page.getByTestId("round-account")
  await expect(round).toContainText(
    "2 of 3 files imported, 1 skipped, as you chose.",
    { timeout: IMPORT_MS }
  )
  await expect(page.getByTestId("import-done")).toContainText(
    /Imported [\d,]+ records into XES/
  )
  await screenshot(page, "import-several-done")
  await page.getByTestId("review-left").click()
  await expect(page.getByTestId("import-review")).toBeFocused()
  await stepSays(page, "file", "complete", EXPORT)
  await expect(page.getByTestId("several-contracts")).toHaveCount(0)
  await expect(verdict(page)).toHaveText(
    "Its records differ from the ones FEAT holds",
    { timeout: READ_MS }
  )
  expect(errors).toEqual([])
})
