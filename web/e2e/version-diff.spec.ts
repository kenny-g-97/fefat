import type { Locator } from "@playwright/test"
import { lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { strategyFromTemplate } from "./support/strategies.ts"

// The version diff of step 5.10 (D-126) against the seeded server: demo's version 2, a wider
// stop, beside its version 1 on the strategy page, the earlier on the left, the stop's change
// marked in the accent and never in the merge view's red and green (Done means 1 for the diff),
// and no Changes card for a strategy of one version.

/** The accent and the hover step in the dark theme, as the browser computes them. */
const BRAND = "rgb(252, 115, 77)"
const HOVER_STEP = "rgb(26, 26, 26)"

test("the latest version stands beside the one before it, the stop's change in the accent", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.goto("/strategies/strategy?name=demo")

  const changes = page.getByRole("region", { name: "Changes" })
  await expect(changes).toContainText(
    "Version 1 on the left, version 2 on the right"
  )
  const earlier = changes.locator(".cm-merge-a .cm-changedText")
  const later = changes.locator(".cm-merge-b .cm-changedText")
  await expect(earlier).toHaveText(["1.5"])
  await expect(later).toHaveText(["2.0"])
  await expect(
    changes.getByRole("textbox", { name: "Version 1" })
  ).toBeVisible()
  await expect(
    changes.getByRole("textbox", { name: "Version 2" })
  ).toBeVisible()
  const marked = await later.first().evaluate((text) => {
    const line = text.closest(".cm-changedLine")
    return {
      outline: getComputedStyle(text).outlineColor,
      line: line === null ? "" : getComputedStyle(line).backgroundColor,
    }
  })
  expect(marked.outline).toBe(BRAND)
  expect(marked.line).toBe(HOVER_STEP)
  // Each side's gutter bars its changed line in the accent, the earlier's too, never the merge
  // view's red or green.
  for (const side of ["a", "b"]) {
    const bars = await changes
      .locator(`.cm-merge-${side} .cm-changedLineGutter`)
      .evaluateAll((marks) =>
        marks.map((mark) => getComputedStyle(mark).backgroundColor)
      )
    expect(bars.length).toBeGreaterThan(0)
    expect(new Set(bars)).toEqual(new Set([BRAND]))
  }
  // CodeMirror measures an editor's lines once it is in view, its gutter estimated before.
  await changes.scrollIntoViewIfNeeded()
  await expect.poll(() => gutterAligned(changes)).toBe(true)
  await page.mouse.move(700, 36)
  await screenshot(page, "version-diff")
  await lightThemeDrawn(page, [])
  await screenshot(page, "version-diff-light")
  expect(errors).toEqual([])
})

test("version 1 stands beside the one after it, and a strategy of one version has no changes", async ({
  loggedIn: page,
}) => {
  await page.goto("/strategies/strategy?name=demo&version=1")
  await expect(page.getByRole("region", { name: "Changes" })).toContainText(
    "Version 1 on the left, version 2 on the right"
  )

  await strategyFromTemplate(page.request, "one_version", "breakout")
  await page.goto("/strategies/strategy?name=one_version")
  await expect(
    page.getByRole("region", { name: "Code", exact: true })
  ).toBeVisible()
  await expect(page.getByRole("region", { name: "Changes" })).toHaveCount(0)
})

/** Whether each side's last line number stands level with its last line of code. */
function gutterAligned(changes: Locator): Promise<boolean> {
  return changes.locator(".cm-editor").evaluateAll((editors) =>
    editors.every((editor) => {
      const numbers = editor.querySelectorAll(
        ".cm-lineNumbers .cm-gutterElement"
      )
      const lines = editor.querySelectorAll(".cm-content .cm-line")
      const number = numbers.item(numbers.length - 1)
      const line = lines.item(lines.length - 1)
      return (
        Math.abs(
          number.getBoundingClientRect().top - line.getBoundingClientRect().top
        ) < 1
      )
    })
  )
}
