import type { Locator, Page } from "@playwright/test"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { inBothThemes, noSidewaysScroll } from "./support/import-wizard.ts"
import { cancelActiveJobs, startDemoJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The Delete card of step 5.18 (D-107, ADR-0023) against the seeded server: the end of a
// dataset's page says what a delete of the instrument's data from the provider removes and how
// many saved runs read it, ES from synthetic being what the seed's demo run read; Delete asks
// once in place, and Keep and a double click keep; a job under way refuses the delete, and a
// refusal says why under the buttons; Delete now takes MES from synthetic off the Data page for
// good. It runs in a project of its own after every other, since it removes seeded data the
// other specs read.

// The builder's checks as clips (the UI recipe): Keep on ES, then Delete now on MES.
test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const ES_PAGE = "/data/dataset?instrument=ES&provider=synthetic"
const MES_PAGE = "/data/dataset?instrument=MES&provider=synthetic"
/** A refusal of the shape a file held open gives, its path made up (D-80): a Windows path
 * breaks at no space, so the card must break it anywhere. */
const HELD_OPEN = String.raw`Expected to remove D:\TradingResearch\FEAT\store\databento\trades\root=MNQ\contract=MNQZ2026\date=2026-09-21, got "The process cannot access the file because it is being used by another process": close the programs that read it, such as a chart or a notebook, then delete again, which finishes the delete.`

test.afterEach(async ({ page }) => {
  await cancelActiveJobs(page.request)
})

function deleteCard(page: Page): Locator {
  return page.getByRole("region", { name: "Delete this data" })
}

function importedRow(page: Page, root: string): Locator {
  return page
    .getByRole("region", { name: "Imported data" })
    .getByTestId("imported-row")
    .filter({
      has: page.getByTestId("imported-root").getByText(root, { exact: true }),
    })
}

/** The DELETE requests the page sends, as it sends them. */
function deletesOf(page: Page): readonly string[] {
  const sent: string[] = []
  page.on("request", (request) => {
    if (request.method() === "DELETE") {
      sent.push(new URL(request.url()).pathname)
    }
  })
  return sent
}

test("the card says what a delete removes, and Keep and a double click keep", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const errors = consoleErrors(page)
  const sent = deletesOf(page)
  await page.goto(ES_PAGE)
  const card = deleteCard(page)
  const trigger = card.getByRole("button", { name: "Delete", exact: true })

  await expect(card.getByTestId("delete-data")).toContainText(
    "1 saved run read this data: it keeps its results, but FEAT can no longer explain its trades or check it again."
  )
  await expect(card).toContainText(
    /Delete removes 1-minute bars, 1-second bars, and trades from \d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d/
  )
  await expect(card).toContainText(
    "Your own files stay where you keep them, and can be imported again afterwards."
  )
  await expect(card).toContainText("This cannot be undone.")
  await trigger.click()
  const keep = card.getByRole("button", { name: "Keep" })
  await expect(keep).toBeFocused()
  await expect(card.getByRole("button", { name: "Delete now" })).toBeVisible()
  await inBothThemes(page, "dataset-delete-asked")
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await keep.click()
  await expect(trigger).toBeFocused()
  // From the keyboard, each of the card's buttons draws its focus ring.
  await page.keyboard.press("Enter")
  await expect(keep).toBeFocused()
  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
  await page.keyboard.press("Shift+Tab")
  await expect(card.getByRole("button", { name: "Delete now" })).toBeFocused()
  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
  await page.keyboard.press("Tab")
  await page.keyboard.press("Enter")
  await expect(trigger).toBeFocused()
  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
  // The second click lands on Keep, which took the trigger's place and gives the focus back.
  await trigger.dblclick()
  await expect(trigger).toBeFocused()

  expect(sent).toEqual([])
  await page.goto("/data")
  await expect(importedRow(page, "ES")).toHaveCount(1)
  expect(errors).toEqual([])
})

test("a job under way refuses the delete, and the refusal says why under the buttons", async ({
  loggedIn: page,
}) => {
  await page.goto(MES_PAGE)
  const card = deleteCard(page)
  await expect(card.getByTestId("delete-data")).toBeVisible()
  await startDemoJobs(page.request, 1)

  await card.getByRole("button", { name: "Delete", exact: true }).click()
  await card.getByRole("button", { name: "Delete now" }).click()

  await expect(card.getByRole("alert")).toContainText(
    "Expected no job queued or running, got 1 job: delete once it ends, or cancel it in the jobs drawer"
  )
  await expect(card.getByRole("button", { name: "Delete now" })).toBeEnabled()
  await expect(page).toHaveURL(MES_PAGE)
})

test("Keep waits while a delete runs, and a refusal of a file held open stays in the card", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(MES_PAGE)
  const card = deleteCard(page)
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/stored-data/synthetic/MES", async (route) => {
    if (route.request().method() !== "DELETE") {
      await route.continue()
      return
    }
    await released
    await route.fulfill(problemAnswer(409, HELD_OPEN))
  })

  await card.getByRole("button", { name: "Delete", exact: true }).click()
  await card.getByRole("button", { name: "Delete now" }).click()
  await expect(card.getByRole("button", { name: "Keep" })).toBeDisabled()
  await expect(card.getByRole("button", { name: "Delete now" })).toBeDisabled()
  await expect(card.getByRole("status")).toHaveText("Deleting")
  release()

  await expect(card.getByRole("alert")).toHaveText(HELD_OPEN)
  await expect(card.getByRole("button", { name: "Delete now" })).toBeEnabled()
  // The wait dropped the focus; the confirm takes it back, to be pressed again.
  await expect(card.getByRole("button", { name: "Delete now" })).toBeFocused()
  await noSidewaysScroll(page)
  await inBothThemes(page, "dataset-delete-refused")
  expect(await lowContrastInEachTheme(page)).toEqual([])
})

test("a delete that ends after the trader left its page leaves them where they went", async ({
  loggedIn: page,
}) => {
  await page.goto(MES_PAGE)
  const card = deleteCard(page)
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  // Answered by the test, so that the seeded MES stays for the last test.
  await page.route("**/v1/stored-data/synthetic/MES", async (route) => {
    if (route.request().method() !== "DELETE") {
      await route.continue()
      return
    }
    await released
    await route.fulfill({ status: 204 })
  })

  await card.getByRole("button", { name: "Delete", exact: true }).click()
  await card.getByRole("button", { name: "Delete now" }).click()
  await page.getByRole("link", { name: "Home", exact: true }).click()
  await expect(page).toHaveURL("/")
  const answered = page.waitForResponse(
    (response) =>
      response.request().method() === "DELETE" &&
      response.url().endsWith("/v1/stored-data/synthetic/MES")
  )
  release()
  await answered
  await page.waitForTimeout(1_000)

  await expect(page).toHaveURL("/")
})

test("Delete now takes the data off the Data page for good", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(MES_PAGE)
  const card = deleteCard(page)
  await expect(card).toContainText("No saved run read this data.")
  await inBothThemes(page, "dataset-delete")

  await card.getByRole("button", { name: "Delete", exact: true }).click()
  await card.getByRole("button", { name: "Delete now" }).click()

  await expect(page).toHaveURL("/data")
  await expect(
    page.getByRole("status").filter({ hasText: "Deleted MES from synthetic." })
  ).toBeVisible()
  await expect(
    page.getByRole("status").filter({ hasText: "Deleted MES from synthetic." })
  ).toBeFocused()
  await expect(importedRow(page, "ES")).toHaveCount(1)
  await expect(importedRow(page, "MES")).toHaveCount(0)
  await screenshot(page, "data-after-delete")
  await page.reload()
  await expect(importedRow(page, "ES")).toHaveCount(1)
  await expect(importedRow(page, "MES")).toHaveCount(0)
  await page.goto(MES_PAGE)
  await expect(page.getByRole("alert")).toContainText(
    "FEAT holds no data of MES from synthetic."
  )
  await expect(
    page.getByRole("region", { name: "Delete this data" })
  ).toHaveCount(0)
  expect(errors).toEqual([])
})
