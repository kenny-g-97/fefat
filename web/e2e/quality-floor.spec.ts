import type { Page } from "@playwright/test"
import { lowContrast } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"

// The quality floor of 08-code-design.md section 5 on every page of the shell, served by
// `fefat up` under its content security policy: nothing scrolls sideways at 1280 px, the
// console stays free of errors (a refused style or font among them), keyboard focus shows,
// reduced motion stops the transitions, and text, fields, and focus rings keep WCAG's
// contrast in both themes. A page a later step adds joins PATHS.

const PATHS = [
  "/",
  "/lab",
  "/strategies",
  "/runs",
  "/prop",
  "/agent",
  "/data",
  "/settings",
]
const THEMES = ["dark", "light"] as const

/** The page in `theme` at once, as the shell paints the server's setting; specs that call it
 * reduce motion first, so that no colour is measured halfway through its transition. */
function showTheme(page: Page, theme: (typeof THEMES)[number]) {
  return page.evaluate(
    (dark) => document.documentElement.classList.toggle("dark", dark),
    theme === "dark"
  )
}

test("no page scrolls sideways at 1280 px or logs an error", async ({
  loggedIn: page,
}) => {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  page.on("pageerror", (error) => errors.push(error.message))

  for (const path of PATHS) {
    await page.goto(path)
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    )
    expect(overflow, path).toBeLessThanOrEqual(0)
  }
  expect(errors).toEqual([])
})

test("the login page neither scrolls sideways nor logs an error", async ({
  page,
}) => {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })

  await page.goto("/login")
  await expect(
    page.getByRole("heading", { level: 1, name: "FEFAT" })
  ).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth
  )

  expect(overflow).toBeLessThanOrEqual(0)
  expect(errors).toEqual([])
})

test("keyboard focus is visible on the first stops of the page", async ({
  loggedIn: page,
}) => {
  // Reduced motion lets the ring settle at once, and each control is compared with itself
  // unfocused, so that a resting shadow never passes for a ring.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()

  const rings: string[] = []
  for (let stop = 0; stop < 3; stop += 1) {
    await page.keyboard.press("Tab")
    rings.push(
      await page.evaluate(() => {
        const focused = document.activeElement
        if (!(focused instanceof HTMLElement) || focused === document.body) {
          return "nothing focused"
        }
        // Chrome changes an outline's width on focus even when none is drawn.
        const look = (style: CSSStyleDeclaration) =>
          style.outlineStyle === "none"
            ? style.boxShadow
            : `${style.outlineStyle} ${style.outlineWidth} ${style.boxShadow}`
        const withFocus = look(getComputedStyle(focused))
        focused.blur()
        const withoutFocus = look(getComputedStyle(focused))
        focused.focus()
        return withFocus === withoutFocus
          ? `no ring on ${focused.textContent}`
          : "ring"
      })
    )
  }
  expect(rings).toEqual(["ring", "ring", "ring"])
})

test("reduced motion stops every transition", async ({ loggedIn: page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  const moving = await page.evaluate(() =>
    [...document.querySelectorAll("a, button, input")]
      .map((element) => getComputedStyle(element).transitionDuration)
      .filter((duration) =>
        duration.split(",").some((part) => parseFloat(part) > 0)
      )
  )
  expect(moving).toEqual([])
})

test("keyboard focus shows in a contrast theme of Windows too", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ forcedColors: "active" })
  await page.goto("/")
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()

  await page.keyboard.press("Tab")

  const outline = await page.evaluate(() =>
    document.activeElement === null
      ? "nothing focused"
      : getComputedStyle(document.activeElement).outlineStyle
  )
  expect(outline).toBe("solid")
})

test("reduced motion switches the theme without a fade", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/settings")
  const html = page.locator("html")
  const saved = (theme: string) =>
    page.waitForResponse(
      (response) =>
        response.url().endsWith("/v1/settings") &&
        response.request().method() === "PUT" &&
        response.request().postData()?.includes(theme) === true
    )

  const light = saved("light")
  await page.getByRole("radio", { name: "Light" }).click()
  await light
  await expect(html).not.toHaveClass(/dark/)
  const running = await page.evaluate(() => document.getAnimations().length)

  const dark = saved("dark")
  await page.getByRole("radio", { name: "Dark" }).click()
  await dark
  await expect(html).toHaveClass(/dark/)
  expect(running).toBe(0)
})

test("text, placeholders, and field borders keep their contrast on every page, in both themes", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const problems: string[] = []
  for (const path of PATHS) {
    await page.goto(path)
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    await page.waitForLoadState("networkidle")
    for (const theme of THEMES) {
      await showTheme(page, theme)
      for (const problem of await lowContrast(page, "text")) {
        problems.push(`${path}, ${theme}: ${problem}`)
      }
    }
  }
  expect(problems).toEqual([])
})

test("the login page keeps its contrast", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/login")
  await expect(
    page.getByRole("heading", { level: 1, name: "FEFAT" })
  ).toBeVisible()

  expect(await lowContrast(page, "text")).toEqual([])
})

test("a focused button's ring keeps 3 : 1 against the page, in both themes", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/settings")
  await page.waitForLoadState("networkidle")
  const problems: string[] = []
  for (const theme of THEMES) {
    await showTheme(page, theme)
    // Tab from the field before it, so that the browser shows the focus as a keyboard's.
    await page.getByLabel("Token name").focus()
    await page.keyboard.press("Tab")
    await expect(
      page.getByRole("button", { name: "Create token" })
    ).toBeFocused()
    for (const problem of await lowContrast(page, "focus ring")) {
      problems.push(`${theme}: ${problem}`)
    }
  }
  expect(problems).toEqual([])
})
