import { expect, test } from "./support/fixtures.ts"

// The Contemporary skin of web/DESIGN.md (D-88), as the browser paints it on the settings page,
// which holds every kind of control the shell has: Geist Mono for every text, one 12 px radius,
// the hot pink on the primary action, and the skill's measures for the sidebar, its rows, the
// page title, and the cards.

test("the shell wears the Contemporary skin and its measures", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")
  await expect(
    page.getByRole("heading", { level: 1, name: "Settings" })
  ).toBeVisible()

  const skin = await page.evaluate(() => {
    const style = (selector: string) => {
      const element = document.querySelector(selector)
      if (element === null) {
        throw new Error(`Expected an element for ${selector}, got none.`)
      }
      return getComputedStyle(element)
    }
    const row = style('nav[aria-label="Main"] a[aria-current="page"]')
    const primary = style('main button[type="submit"]')
    const card = style("main section")
    return {
      font: style("body").fontFamily.split(",")[0].replaceAll('"', ""),
      sidebarWidth: style("aside").width,
      rowHeight: row.height,
      rowRadius: row.borderTopLeftRadius,
      titleWeight: style("main h1").fontWeight,
      cardRadius: card.borderTopLeftRadius,
      cardPadding: card.paddingTop,
      fieldRadius: style('[data-slot="input"]').borderTopLeftRadius,
      primaryRadius: primary.borderTopLeftRadius,
      primaryFill: primary.backgroundColor,
    }
  })

  expect(skin).toEqual({
    font: "Geist Mono",
    sidebarWidth: "256px",
    rowHeight: "40px",
    rowRadius: "12px",
    titleWeight: "600",
    cardRadius: "12px",
    cardPadding: "24px",
    fieldRadius: "12px",
    primaryRadius: "12px",
    primaryFill: "rgb(244, 65, 116)",
  })
})
