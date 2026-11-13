import { lowContrastInEachTheme } from "./support/contrast.ts"
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
  "/data/dataset?instrument=MES&provider=synthetic",
  "/data/chart?instrument=MES",
  "/data/import",
  "/settings",
  "/no-such-page",
]

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
    // Once its requests are answered, so that a page is measured with what it loads drawn.
    await page.waitForLoadState("networkidle")
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
    page.getByRole("heading", { level: 1, name: "FEAT", exact: true })
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

test("a skip link leads past the sidebar to the page", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  await page.keyboard.press("Tab")
  const skip = page.getByRole("link", { name: "Skip to content" })
  await expect(skip).toBeFocused()
  await expect(skip).toBeInViewport()
  await page.keyboard.press("Enter")
  await page.keyboard.press("Tab")

  // The page's first control, the theme's checked radio, past the sidebar's ten stops.
  await expect(page.getByRole("radio", { name: "Dark" })).toBeFocused()
})

test("in a short window the sidebar scrolls, so Log out is reached without scrolling the page", async ({
  loggedIn: page,
}) => {
  await page.setViewportSize({ width: 1280, height: 460 })
  await page.goto("/settings")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  const logOut = page.getByRole("button", { name: "Log out" })
  await logOut.scrollIntoViewIfNeeded()

  await expect(logOut).toBeInViewport()
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})

test("reduced motion stops every transition, on every page", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const moving: string[] = []
  for (const path of PATHS) {
    await page.goto(path)
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    await page.waitForLoadState("networkidle")
    const found = await page.evaluate(() =>
      [...document.querySelectorAll("a, button, input, summary")]
        .map((element) => getComputedStyle(element).transitionDuration)
        .filter((duration) =>
          duration.split(",").some((part) => parseFloat(part) > 0)
        )
    )
    moving.push(...found.map((duration) => `${path}: ${duration}`))
  }
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

  // A field shows its focus as a ring, which a contrast theme drops, so there it takes an
  // outline too: the Phase 4 exit's step review found the first stop, a link, outlined anyway.
  await page.goto("/settings")
  const field = page.getByLabel("Token name")
  await field.focus()
  await expect(field).toHaveCSS("outline-style", "solid")
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
    for (const problem of await lowContrastInEachTheme(page)) {
      problems.push(`${path}, ${problem}`)
    }
  }
  expect(problems).toEqual([])
})

test("the login page keeps its contrast in both themes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/login")
  await expect(
    page.getByRole("heading", { level: 1, name: "FEAT", exact: true })
  ).toBeVisible()

  // A logout from the light theme leaves the login light until a reload.
  expect(await lowContrastInEachTheme(page)).toEqual([])
})

test("a new token's box and its revocation keep their contrast, in both themes", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/settings")
  await page.getByLabel("Token name").fill("e2e-contrast")
  await page.getByRole("button", { name: "Create token" }).click()
  const row = page.getByRole("row", { name: /e2e-contrast/ })
  await row.getByRole("button", { name: "Revoke" }).click()
  await expect(row.getByRole("button", { name: "Revoke now" })).toBeVisible()
  await expect(page.getByTestId("new-token")).toBeVisible()

  expect(await lowContrastInEachTheme(page)).toEqual([])
  // Revoked, so that the settings page's screenshots show their own token alone.
  await row.getByRole("button", { name: "Revoke now" }).click()
  await expect(row).toBeHidden()
})

test("a focused button's ring keeps 3 : 1 against the page, in both themes", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/settings")
  await page.waitForLoadState("networkidle")
  // Tab from the field before it, so that the browser shows the focus as a keyboard's.
  await page.getByLabel("Token name").focus()
  await page.keyboard.press("Tab")
  await expect(page.getByRole("button", { name: "Create token" })).toBeFocused()

  expect(await lowContrastInEachTheme(page, "focus ring")).toEqual([])
})
