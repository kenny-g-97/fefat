import path from "node:path"
import { test, type Locator, type Page } from "@playwright/test"

/** Save the page as `test-results/screenshots/<name>.png`, which the ui-verifier reads and the
 * pull request shows, from the desktop project alone; `masked` covers what must not leave this
 * machine, such as a local path or a token (D-80). */
export async function screenshot(
  page: Page,
  name: string,
  masked: readonly Locator[] = []
) {
  const project = test.info().project
  if (project.name !== "desktop") {
    return
  }
  const file = path.join(project.outputDir, "screenshots", `${name}.png`)
  // From the top: a full page taken after a click scrolled it draws the sticky sidebar where
  // the window had scrolled to.
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: file,
    fullPage: true,
    animations: "disabled",
    mask: [...masked],
    maskColor: "#666666",
  })
}
