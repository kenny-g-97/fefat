import path from "node:path"
import { test, type Locator, type Page } from "@playwright/test"

/** The projects whose pages are saved: the built app's, not the dev server's, which shows the
 * same pages again. */
const SAVED_PROJECTS: ReadonlySet<string> = new Set([
  "desktop",
  "desktop-import",
  "desktop-import-next",
  "desktop-import-breaks",
  "desktop-delete",
  "desktop-runs",
])

/** Save the page as `test-results/screenshots/<name>.png`, which the ui-verifier reads and the
 * pull request shows, from the built app's projects alone; `masked` covers what must not leave
 * this machine, such as a local path or a token (D-80); `"window"` keeps to the window, where a
 * modal's scrim would stop at its edge on a full page. */
export async function screenshot(
  page: Page,
  name: string,
  masked: readonly Locator[] = [],
  extent: "page" | "window" = "page"
) {
  const project = test.info().project
  if (!SAVED_PROJECTS.has(project.name)) {
    return
  }
  const file = path.join(project.outputDir, "screenshots", `${name}.png`)
  // From the top: a full page taken after a click scrolled it draws the sticky sidebar where
  // the window had scrolled to.
  await page.evaluate(() => window.scrollTo(0, 0))
  // Every image drawn, the sidebar's logo among them, which no assertion waits for; a broken
  // image counts as complete too, but has no width.
  await page.waitForFunction(() =>
    [...document.images].every(
      (image) => image.complete && image.naturalWidth > 0
    )
  )
  await page.screenshot({
    path: file,
    fullPage: extent === "page",
    animations: "disabled",
    mask: [...masked],
    maskColor: "#666666",
  })
}
