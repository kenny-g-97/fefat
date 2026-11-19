import { readFileSync } from "node:fs"
import path from "node:path"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  chosen,
  continued,
  IMPORT_MS,
  importRoot,
  inBothThemes,
  READ_MS,
  shown,
  signOf,
  step,
  stepSays,
  verdict,
  WITH_A_BREAK,
  WITHOUT_A_BREAK,
} from "./support/import-wizard.ts"
import { screenshot } from "./support/screenshots.ts"

// The import wizard's correction of bars in a break (step 5.15), in a project that runs after
// `import-next.spec.ts`'s, since it reads the profile `import.spec.ts` kept. It chooses files
// through the picker alone, so no path of this machine shows, and records its clip, the click
// path of your check (the UI recipe).
test.use({
  video: { mode: "on", size: { width: 1280, height: 800 } },
  actionTimeout: 15_000,
})

// Step 5.15 (ADR-0022): the seed's exports under `breaks`, chosen through the picker so that no
// path of this machine shows. One file whose break after 02-03 holds nine bars, the last
// closing at the next open, is refused for them alone, its verdict in the negative; its box of
// counts ends on the choice, the file not imported chosen at the start, and you import it
// without them, choose back, choose again by the keys, and import (D-106). Then a round of two
// such files and one without them (D-105): the two rows say on themselves, in the negative,
// what stops them, and Import waits for a decision on them; the round's box asks it once for
// both, counting a skip made in a row, which its correction leaves standing, and its answer for
// both turns them positive, each row still offering its skip, and one job imports the three.

test("a file with bars in a break imports without them once you choose so", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await shown(page, "file")

  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (await picker).setFiles(path.join(root, "breaks", WITH_A_BREAK[0]))
  await expect(page.getByTestId("import-chosen")).toContainText(WITH_A_BREAK[0])
  await continued(page, "layout")
  await chosen(page, "import-profile", "xes-minutes, yours")
  await step(page, "review")

  // The refusal, worded by the wizard from the server's counts and trade dates.
  await expect(verdict(page)).toHaveText(
    "It would be refused for its bars in a break",
    { timeout: READ_MS }
  )
  await expect.poll(() => signOf(verdict(page))).toBe("negative")
  const box = page.getByTestId("breaks-account")
  await expect(box).toContainText(
    "Breaks: 9 bars in the break after the trade date 2026-02-03"
  )
  await expect(box).toContainText("Sessions beside: 2026-02-03, 2026-02-04")
  await expect(box).toContainText(
    "Records: 2,769 in all, those bars among them"
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "It would be refused for its bars in a break"
  )

  // The choice under the counts, each option saying what it does, the one that imports
  // nothing chosen at the start, since it is what happens if nothing is chosen (D-106).
  const leaveOut = box.getByRole("radio", {
    name: "Import the file without those bars",
  })
  const refuse = box.getByRole("radio", { name: "Do not import the file" })
  await expect(refuse).toBeChecked()
  await expect(leaveOut).not.toBeChecked()
  await expect(box.getByTestId("bars-choice-leave-out")).toContainText(
    "FEAT leaves out 2,769 records, those bars and the sessions listed above, and imports the rest of the file."
  )
  await expect(box.getByTestId("bars-choice-refuse")).toContainText(
    "It stays refused for these bars, and nothing is written."
  )
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-bars-choice")

  // A press anywhere on an option's row chooses it, its description too; the file then imports
  // without those bars, and the box says what the calendar check lists.
  await box
    .getByTestId("bars-choice-leave-out")
    .getByText("imports the rest of the file")
    .click()
  await expect(leaveOut).toBeChecked()
  await expect(verdict(page)).toHaveText(
    "It imports without its bars in a break",
    { timeout: READ_MS }
  )
  await expect.poll(() => signOf(verdict(page))).toBe("positive")
  await expect(box).toContainText(
    "The calendar check may list the sessions left out as having no prints."
  )
  await expect(
    page.getByText("Reading your latest change", { exact: true })
  ).toHaveCount(0, { timeout: READ_MS })
  await inBothThemes(page, "import-left-out")

  // Choosing the other line refuses the file again, and the keys choose as the pointer does,
  // the radio keeping the focus through the file's reading; chosen once more, it imports.
  await refuse.click()
  await expect(verdict(page)).toHaveText(
    "It would be refused for its bars in a break",
    { timeout: READ_MS }
  )
  await expect(page.getByTestId("import-run")).toBeDisabled()
  await expect(refuse).toBeFocused()
  // Held as a person holds a key: the group chooses the radio its arrow moves to while the key
  // is down.
  await page.keyboard.press("ArrowUp", { delay: 100 })
  await expect(leaveOut).toBeChecked()
  // The radio the keys reached shows its ring, at 3 : 1 in both themes (the UI verifier).
  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await expect(verdict(page)).toHaveText(
    "It imports without its bars in a break",
    { timeout: READ_MS }
  )
  await expect(leaveOut).toBeFocused()
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-left-out")).toHaveText(
    "Left out 2,769 records, the bars in a break and the sessions the review listed, as you approved.",
    { timeout: IMPORT_MS }
  )
  await screenshot(page, "import-left-out-done")
  expect(errors).toEqual([])
})

test("a round asks of its files' bars in a break in one box, then imports them without those bars", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await shown(page, "file")

  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (
    await picker
  ).setFiles(
    [WITH_A_BREAK[1], WITH_A_BREAK[2], WITHOUT_A_BREAK].map((name) =>
      path.join(root, "breaks", name)
    )
  )
  await continued(page, "layout")
  await chosen(page, "import-profile", "xes-minutes, yours")
  await step(page, "review")

  // Each file's own review; the two with bars in a break say so on their rows, unopened, in
  // the negative, and the one without them reads Imports in the positive (D-105).
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "1 of 3 files import as they are",
    { timeout: READ_MS }
  )
  await expect(
    page.getByText("2 files would be refused for their bars in a break")
  ).toBeVisible()
  const rows = page.getByTestId("review-file")
  const row = rows.filter({ hasText: WITH_A_BREAK[1] })
  const aside = row.getByTestId("review-file-aside")
  await expect(aside).toHaveText("Bars in a break")
  await expect.poll(() => signOf(aside)).toBe("negative")
  const reason = row.getByTestId("review-file-reason")
  await expect(reason).toBeVisible()
  await expect(reason).toHaveText(
    "It would be refused for its bars in a break: 9 bars in the break after the trade date 2026-02-03"
  )
  await expect.poll(() => signOf(reason)).toBe("negative")
  const clean = rows
    .filter({ hasText: WITHOUT_A_BREAK })
    .getByTestId("review-file-aside")
  await expect(clean).toHaveText("Imports")
  await expect.poll(() => signOf(clean)).toBe("positive")
  const run = page.getByTestId("import-run")
  await expect(run).toBeDisabled()
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Decide what to do with 2 files first"
  )
  await stepSays(page, "review", "incomplete", "2 files wait for your decision")

  // Under the rows, one box asks it of both, its options saying what each does, none chosen
  // (D-106).
  const decision = page.getByTestId("decision-bars")
  await expect(decision).toContainText("2 files hold bars in a break")
  await expect(decision).toContainText(
    "These files hold bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early."
  )
  const correct = decision.getByRole("radio", {
    name: "Import them without those bars",
  })
  const skipThem = decision.getByRole("radio", { name: "Skip them" })
  await expect(correct).not.toBeChecked()
  await expect(skipThem).not.toBeChecked()
  await expect(
    decision.getByTestId("decision-bars-options-skipped")
  ).toContainText("None of these 2 files is imported.")
  await expect(page.getByTestId("decision-other")).toHaveCount(0)
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-several-refused")

  // The row's own summary; its review holds the calendar check's, which lists those bars, and
  // whose chevron stays closed while the row it stands in is open; the choice is the box's.
  await row.locator("summary").first().click()
  await expect(row.getByTestId("breaks-account")).toContainText(
    "Records: 2,769 in all, those bars among them"
  )
  await expect(row.getByTestId("bars-choice")).toHaveCount(0)
  await expect(row.locator("summary").first().locator("svg")).toHaveCSS(
    "rotate",
    "90deg"
  )
  await expect(
    row.getByTestId("review-mismatches").locator("summary svg")
  ).toHaveCSS("rotate", "none")

  // A skip in a row stays in the box, which counts it; the other file still waits.
  await row.getByRole("button", { name: "Skip this file" }).click()
  await expect(row.getByRole("button", { name: "Do not skip" })).toBeFocused()
  await expect(decision).toContainText("1 of these 2 files is skipped.")
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Decide what to do with 1 file first"
  )

  // A double click's second click, landing on an option that a change moved under the
  // pointer, on its radio or anywhere on its row, chooses nothing (the design review).
  await skipThem.dispatchEvent("click", { detail: 2 })
  await decision
    .getByTestId("decision-bars-options-skipped")
    .dispatchEvent("click", { detail: 2 })
  await expect(skipThem).not.toBeChecked()

  // The correction lets in the file not skipped, and the skip made in the row stands (the step
  // review), so Import names the two files it sends. While that file is read again, held here
  // for two seconds, the rows keep their last reasons, so the box holds still under the pointer
  // (the design review).
  const other = rows.filter({ hasText: WITH_A_BREAK[2] })
  let holding = true
  await page.route("**/v1/imports/preview", async (route) => {
    if (holding) {
      await new Promise((resolve) => setTimeout(resolve, 2_000))
    }
    await route.continue()
  })
  await correct.click()
  await expect(correct).toBeChecked()
  await expect(
    page
      .getByTestId("import-review")
      .getByText("Reading your latest change", { exact: true })
  ).toBeVisible()
  await expect(other.getByTestId("review-file-reason")).toBeVisible()
  holding = false
  await expect(rows.getByTestId("review-file-aside")).toHaveText(
    ["Skipped", "Without bars in a break", "Imports"],
    { timeout: READ_MS }
  )
  await expect(decision).toContainText("1 of these 2 files is skipped.")
  await expect(run).toHaveText("Import 2 files")
  await expect(run).toBeEnabled({ timeout: READ_MS })

  // Skip them keeps both out, leaving the file that imports.
  await skipThem.click()
  await expect(skipThem).toBeChecked()
  await expect(rows.getByTestId("review-file-aside")).toHaveText([
    "Skipped",
    "Skipped",
    "Imports",
  ])
  await expect(decision).not.toContainText("is skipped.")
  await expect(run).toHaveText("Import 1 file")
  await expect(run).toBeEnabled()

  // Import them without those bars, where both are skipped, lets both in at once.
  await correct.click()
  await expect(correct).toBeChecked()
  await expect(page.getByTestId("review-files-verdict")).toHaveText(
    "1 of 3 files import as they are",
    { timeout: READ_MS }
  )
  // The headline counts the last answers while the files are read again, so the round's
  // own line waits for the new ones.
  await expect(
    page.getByText("2 files import without their bars in a break")
  ).toBeVisible({ timeout: READ_MS })
  await expect(correct).toBeFocused()
  await expect(aside).toHaveText("Without bars in a break")
  await expect.poll(() => signOf(aside)).toBe("positive")
  await expect(reason).toHaveCount(0)
  await expect(decision).toContainText(
    "Each file's calendar check may list the sessions left out as having no prints."
  )
  await expect(page.getByTestId("import-waits")).toHaveCount(0)
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-several-left-out")

  // The row of a file the box let in still offers its skip (the step review), which the box
  // counts; the way back brings the file back without its bars, as the box chose.
  await row.getByRole("button", { name: "Skip this file" }).click()
  await expect(row.getByRole("button", { name: "Do not skip" })).toBeFocused()
  await expect(decision).toContainText("1 of these 2 files is skipped.")
  await expect(correct).toBeChecked()
  await expect(run).toHaveText("Import 2 files")
  await row.getByRole("button", { name: "Do not skip" }).click()
  await expect(
    row.getByRole("button", { name: "Skip this file" })
  ).toBeFocused()
  await expect(aside).toHaveText("Without bars in a break")
  await expect(decision).not.toContainText("is skipped.")

  // One job imports the three, and sums what it left out.
  await expect(run).toHaveText("Import 3 files")
  await run.click()
  await expect(page.getByTestId("round-account")).toContainText(
    "3 of 3 files imported",
    { timeout: IMPORT_MS }
  )
  await expect(page.getByTestId("import-left-out")).toHaveText(
    "Left out 5,538 records, the bars in a break and the sessions the review listed, as you approved."
  )
  await screenshot(page, "import-several-left-out-done")
  expect(errors).toEqual([])
})

test("a file that cannot be read says why on its row, closed and open", async ({
  loggedIn: page,
}) => {
  test.setTimeout(10 * 60_000)
  const errors = consoleErrors(page)
  const root = await importRoot(page)
  await page.goto("/data/import")
  await shown(page, "file")

  // A .gz that is no archive, which the server refuses before any verdict, beside an export
  // the round above imported, which needs no decision.
  const broken = "XES 12-28.Last.txt.gz"
  const picker = page.waitForEvent("filechooser")
  await page.getByRole("button", { name: "Choose files", exact: true }).click()
  await (
    await picker
  ).setFiles([
    {
      name: broken,
      mimeType: "application/gzip",
      buffer: Buffer.from("not an archive"),
    },
    {
      name: WITHOUT_A_BREAK,
      mimeType: "text/plain",
      buffer: readFileSync(path.join(root, "breaks", WITHOUT_A_BREAK)),
    },
  ])
  await expect(page.getByTestId("import-chosen")).toContainText(
    "and 1 more file"
  )
  await continued(page, "layout")
  await chosen(page, "import-profile", "xes-minutes, yours")
  await step(page, "review")

  // Closed, the row says Not read and why, in the negative (D-105).
  const rows = page.getByTestId("review-file")
  const row = rows.filter({ hasText: broken })
  const aside = row.getByTestId("review-file-aside")
  await expect(aside).toHaveText("Not read", { timeout: READ_MS })
  await expect.poll(() => signOf(aside)).toBe("negative")
  const reason = row.getByTestId("review-file-reason")
  await expect(reason).toBeVisible()
  const why = await reason.textContent()
  if (why === null || why === "") {
    throw new Error(
      "Expected the row to say why its file was not read, got nothing."
    )
  }
  await expect(
    rows.filter({ hasText: WITHOUT_A_BREAK }).getByTestId("review-file-aside")
  ).toHaveText("Imported before")
  await expect(page.getByTestId("import-waits")).toHaveText(
    "Decide what to do with 1 file first"
  )

  // No correction fits it, so its box under the rows, a group named by its title and described
  // by its message for a screen reader (the design review), offers the skip alone, and its way
  // back, each taking the focus from the other (D-106).
  const decision = page.getByTestId("decision-other")
  await expect(decision).toContainText("1 file does not import as it is read")
  const message =
    "Its row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip the file."
  await expect(decision).toContainText(message)
  await expect(
    page.getByRole("group", { name: "1 file does not import as it is read" })
  ).toHaveAccessibleDescription(message)
  await expect(decision.getByRole("radio")).toHaveCount(0)
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  const skip = decision.getByRole("button", { name: "Skip the file" })
  // A double click's second click skips nothing (the design review).
  await skip.dispatchEvent("click", { detail: 2 })
  await expect(aside).toHaveText("Not read")
  await skip.click()
  const wayBack = decision.getByRole("button", { name: "Do not skip it" })
  await expect(wayBack).toBeFocused()
  await expect(aside).toHaveText("Skipped")
  // With no option to show it, the box says the file is skipped (the design review).
  await expect(decision).toContainText("The file is skipped.")
  await expect(page.getByTestId("import-waits")).toHaveText("No file to import")
  await wayBack.click()
  await expect(
    decision.getByRole("button", { name: "Skip the file" })
  ).toBeFocused()
  await expect(aside).toHaveText("Not read")
  await expect(decision).not.toContainText("The file is skipped.")

  // Open, the reason gives way to what the row discloses: why, and the skip.
  await row.locator("summary").first().click()
  await expect(reason).toBeHidden()
  await expect(row.getByTestId("review-file-why")).toHaveText(why)
  await row.getByRole("button", { name: "Skip this file" }).click()
  await expect(row.getByRole("button", { name: "Do not skip" })).toBeFocused()
  await expect(row.getByTestId("review-file-why")).toHaveText(why)
  await expect(page.getByTestId("import-waits")).toHaveText("No file to import")
  await screenshot(page, "import-several-unread")
  expect(errors).toEqual([])
})
