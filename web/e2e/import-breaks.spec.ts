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
// closing at the next open, is refused for them alone, its verdict in the negative; you leave
// them out behind an inline confirmation, take it back, approve again, and import. Then a round
// of two such files and one without them (D-105): the two rows say on themselves, in the
// negative, what stops them, and Import waits for a decision on them; one approval for both
// turns them positive, and one job imports the three.

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
  await expect.poll(() => signOf(verdict(page))).toBe("positive")
  // The way back takes the focus from the confirm it replaces.
  const wayBack = page.getByRole("button", { name: "Leave nothing out" })
  await expect(wayBack).toBeFocused()
  const leaveOut = page.getByTestId("leave-out")
  await expect(leaveOut).toContainText(
    "These bars and the sessions above are left out of the import, so the calendar check may list those sessions as having no prints."
  )
  await expect(
    page.getByText("Reading your latest change", { exact: true })
  ).toHaveCount(0, { timeout: READ_MS })
  await inBothThemes(page, "import-left-out")

  // The way back refuses the file again and gives the focus to the offer; approved once more,
  // it imports.
  await wayBack.click()
  await expect(verdict(page)).toHaveText(
    "It would be refused for its bars in a break",
    { timeout: READ_MS }
  )
  await expect(offer).toBeFocused()
  await offer.click()
  await confirm.click()
  await expect(verdict(page)).toHaveText(
    "It imports without its bars in a break",
    { timeout: READ_MS }
  )
  await page.getByTestId("import-run").click()
  await expect(page.getByTestId("import-left-out")).toHaveText(
    "Left out 2,769 records, the bars in a break and the sessions the review listed, as you approved.",
    { timeout: IMPORT_MS }
  )
  await screenshot(page, "import-left-out-done")
  expect(errors).toEqual([])
})

test("a round waits on its files' bars in a break, then leaves them out with one approval", async ({
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
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-several-refused")

  // The row's own summary; its review holds the calendar check's, which lists those bars, and
  // whose chevron stays closed while the row it stands in is open.
  await row.locator("summary").first().click()
  await expect(row.getByTestId("breaks-account")).toContainText(
    "Records: 2,769 in all, those bars among them"
  )
  await expect(row.getByTestId("leave-out")).toHaveCount(0)
  await expect(row.locator("summary").first().locator("svg")).toHaveCSS(
    "rotate",
    "90deg"
  )
  await expect(
    row.getByTestId("review-mismatches").locator("summary svg")
  ).toHaveCSS("rotate", "none")

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
    "1 of 3 files import as they are",
    { timeout: READ_MS }
  )
  // The headline counts the last answers while the files are read again, so the round's
  // own line waits for the new ones.
  await expect(
    page.getByText("2 files import without their bars in a break")
  ).toBeVisible({ timeout: READ_MS })
  await expect(
    page.getByRole("button", { name: "Leave nothing out" })
  ).toBeFocused()
  await expect(aside).toHaveText("Without bars in a break")
  await expect.poll(() => signOf(aside)).toBe("positive")
  await expect(reason).toHaveCount(0)
  await expect(page.getByTestId("leave-out")).toContainText(
    "The bars in a break of 2 files and the sessions their rows list are left out of the import, so each file's calendar check may list those sessions as having no prints."
  )
  await expect(page.getByTestId("import-waits")).toHaveCount(0)
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await inBothThemes(page, "import-several-left-out")

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
