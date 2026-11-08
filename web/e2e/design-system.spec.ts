import { expect, test } from "./support/fixtures.ts"

// The Contemporary skin of web/DESIGN.md (D-88, D-89), as the browser paints it on the settings
// page, which holds every kind of control the shell has: Geist Mono for every text, one 12 px
// radius, the orange on the primary action, and the skill's measures for the sidebar, its rows,
// the page title, and the cards; the light theme's darker orange on a checked radio's dot; then
// the purple of a link to another page, on the home page.

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
      rowBorder: row.borderTopColor,
      rowTransition: `${row.transitionProperty} ${row.transitionDuration}`,
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
    rowBorder: "rgb(64, 31, 22)",
    rowTransition:
      "color, background-color, border-color, box-shadow, transform 0.15s",
    titleWeight: "600",
    cardRadius: "12px",
    cardPadding: "24px",
    fieldRadius: "12px",
    primaryRadius: "12px",
    primaryFill: "rgb(252, 115, 77)",
  })
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await expect(
    page.locator('[data-slot="radio-group-indicator"] svg')
  ).toHaveCSS("fill", "rgb(180, 56, 15)")
  await page.goto("/")
  await expect(page.getByRole("link", { name: "All runs" })).toHaveCSS(
    "color",
    "rgb(168, 85, 247)"
  )
})
