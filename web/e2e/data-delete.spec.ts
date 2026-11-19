import type { Locator, Page } from "@playwright/test"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { inBothThemes } from "./support/import-wizard.ts"
import { cancelActiveJobs, startDemoJobs } from "./support/jobs.ts"
import { problemAnswer } from "./support/problems.ts"

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
    / from \d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d are deleted/
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
    "Expected no job queued or running, got 1 job"
  )
  await expect(card.getByRole("button", { name: "Delete now" })).toBeEnabled()
  await expect(page).toHaveURL(MES_PAGE)
})

test("a delete that fails says what the server said", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(MES_PAGE)
  const card = deleteCard(page)
  await page.route("**/v1/stored-data/synthetic/MES", (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill(problemAnswer(409, "A file is held open, for this test."))
      : route.continue()
  )

  await card.getByRole("button", { name: "Delete", exact: true }).click()
  await card.getByRole("button", { name: "Delete now" }).click()

  await expect(card.getByRole("alert")).toHaveText(
    "A file is held open, for this test."
  )
  await inBothThemes(page, "dataset-delete-refused")
  expect(await lowContrastInEachTheme(page)).toEqual([])
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
  await expect(importedRow(page, "ES")).toHaveCount(1)
  await expect(importedRow(page, "MES")).toHaveCount(0)
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
