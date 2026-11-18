import { expect, type Locator, type Page } from "@playwright/test"
import { z } from "zod"
import { screenshot } from "./screenshots.ts"

/** The wizard's steps, as its list and its cards' frames name them (D-105). */
export type WizardStep = "file" | "layout" | "instrument" | "review"

/** Wait until `name` is the step shown: the current one of the list, its card in view. A text
 * assertion passes on a hidden card, so every assertion of a card follows this. */
export async function shown(page: Page, name: WizardStep) {
  await expect(page.getByTestId(`step-${name}`)).toHaveAttribute(
    "aria-current",
    "step"
  )
  await expect(page.getByTestId(`step-card-${name}`)).toBeVisible()
}

/** Open the step `name` from the list at the left. */
export async function step(page: Page, name: WizardStep) {
  await page.getByTestId(`step-${name}`).click()
  await shown(page, name)
}

/** Press Continue, and wait for the step `to` it opens. */
export async function continued(page: Page, to: WizardStep) {
  await page.getByTestId("step-continue").click()
  await shown(page, to)
}

/** Expect the list's step `name` to be marked `mark` and to say `line`. */
export async function stepSays(
  page: Page,
  name: WizardStep,
  mark: "complete" | "incomplete" | "not needed",
  line: string
) {
  const row = page.getByTestId(`step-${name}`)
  await expect(row).toHaveAttribute("data-state", mark)
  await expect(row).toContainText(line)
}

/** Expect the page not to scroll sideways, whatever a card's table holds. */
export async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

/** The name NinjaTrader gives the seed's exports of XES (`scripts/e2e_server.py`). */
export const EXPORT = "XES 03-26.Last.txt"
/** The seed's two more contracts of XES, under `more`, for a round of several files (D-102). */
export const MORE: readonly [string, string] = [
  "XES 06-26.Last.txt",
  "XES 09-26.Last.txt",
]
/** The seed's exports under `breaks`: three contracts whose break after 2026-02-03 holds nine
 * bars, the last closing at the next open, and one without them (step 5.15). */
export const WITH_A_BREAK: readonly [string, string, string] = [
  "XES 12-26.Last.txt",
  "XES 03-27.Last.txt",
  "XES 06-27.Last.txt",
]
export const WITHOUT_A_BREAK = "XES 09-27.Last.txt"
/** How long a preview may take to read a file. */
export const READ_MS = 60_000
/** How long an import's job may take. */
export const IMPORT_MS = 180_000

const settings = z.looseObject({
  server: z.looseObject({ import_roots: z.array(z.string()).min(1) }),
})

/** The seed's import root, as the server's settings name it. */
export async function importRoot(page: Page): Promise<string> {
  const answer = await page.request.get("/v1/settings")
  const [root] = settings.parse(await answer.json()).server.import_roots
  if (root === undefined) {
    throw new Error("Expected the seed's import root, got none.")
  }
  return root
}

/** Type `text` into the field `id` and keep it, as Enter keeps a wizard's field. */
export async function typed(page: Page, id: string, text: string) {
  const field = page.locator(`#${id}`)
  await field.fill(text)
  await field.press("Enter")
}

/** Choose `option` in the select `id`. */
export async function chosen(page: Page, id: string, option: string) {
  await page.locator(`#${id}`).click()
  await page.getByRole("option", { name: option, exact: true }).click()
}

/** The page's screenshot `name` in the dark theme, then in the light one as `<name>-light`. */
export async function inBothThemes(
  page: Page,
  name: string,
  masked: Locator[] = []
) {
  await screenshot(page, name, masked)
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, `${name}-light`, masked)
  await page.evaluate(() => document.documentElement.classList.add("dark"))
}

/** The review's verdict. */
export function verdict(page: Page): Locator {
  return page.getByTestId("review-verdict")
}
