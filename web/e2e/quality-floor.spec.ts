import { expect, test } from "./support/fixtures.ts"

// The quality floor of 08-code-design.md section 5 on every page of the shell, served by
// `fefat up` under its content security policy: nothing scrolls sideways at 1280 px, the
// console stays free of errors (a refused style or font among them), keyboard focus shows, and
// reduced motion stops the transitions. A page a later step adds joins PATHS.

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

test("the login page logs no error either", async ({ page }) => {
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

  expect(errors).toEqual([])
})

test("keyboard focus is visible", async ({ loggedIn: page }) => {
  await page.goto("/")
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()

  await page.keyboard.press("Tab")

  const ring = await page.evaluate(() => {
    const focused = document.activeElement
    if (focused === null || focused === document.body) {
      return "nothing focused"
    }
    const style = getComputedStyle(focused)
    return style.outlineStyle !== "none" || style.boxShadow !== "none"
      ? "visible"
      : "no ring"
  })
  expect(ring).toBe("visible")
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
