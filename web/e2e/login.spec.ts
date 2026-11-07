import { expect, test, type Page } from "@playwright/test"
import { E2E_PASSWORD } from "./support/password.ts"
import { screenshot } from "./support/screenshots.ts"

// Done means 1 and 2 of step 4.3: the login, which the dev-proxy project repeats through the
// Vite dev server's proxy, where a cookie that does not pass through makes every request 401.

async function logIn(page: Page, password: string) {
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Log in" }).click()
}

test("the app asks for the password before anything else", async ({ page }) => {
  await page.goto("/")

  await expect(page).toHaveURL((url) => url.pathname === "/login")
  await expect(page).toHaveTitle("Log in – FEFAT")
  await expect(
    page.getByRole("heading", { level: 1, name: "FEFAT" })
  ).toBeVisible()
  await expect(
    page.getByText("feature engineering for algorithmic trading")
  ).toBeVisible()
  await screenshot(page, "login")
})

test("a wrong password is refused with what to do", async ({ page }) => {
  await page.goto("/login")

  await logIn(page, "not the password")

  await expect(page.getByRole("alert")).toHaveText(
    "That is not FEFAT's password. Type it again."
  )
  await expect(page).toHaveURL((url) => url.pathname === "/login")
  await expect(page.getByLabel("Password")).toBeFocused()
  await screenshot(page, "login-refused")
})

test("the password opens the home page, and logging out ends the session", async ({
  page,
}) => {
  await page.goto("/login")

  await logIn(page, E2E_PASSWORD)

  await expect(page).toHaveURL("/")
  await expect(page).toHaveTitle("Home – FEFAT")
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()
  await page.getByRole("button", { name: "Log out" }).click()
  await expect(page).toHaveURL((url) => url.pathname === "/login")
  await page.goto("/settings")
  await expect(page).toHaveURL((url) => url.pathname === "/login")
})

test("logging out asks the server for nothing with the ended session", async ({
  page,
}) => {
  await page.goto("/login")
  await logIn(page, E2E_PASSWORD)
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()
  const asked: string[] = []
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith("/v1/")) {
      asked.push(path)
    }
  })

  await page.getByRole("button", { name: "Log out" }).click()

  await expect(
    page.getByRole("heading", { level: 1, name: "FEFAT" })
  ).toBeVisible()
  await page.waitForLoadState("networkidle")
  // The session's CSRF token is asked for just before the logout; nothing may follow it.
  expect(asked.slice(asked.indexOf("/v1/auth/logout"))).toEqual([
    "/v1/auth/logout",
  ])
})

test("logging out after another tab logged in again ends the live session", async ({
  page,
}) => {
  await page.goto("/login")
  await logIn(page, E2E_PASSWORD)
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()
  // Another tab logs in again: the browser's cookie now names a new session.
  const again = await page.request.post("/v1/auth/login", {
    data: { password: E2E_PASSWORD },
  })
  expect(again.status()).toBe(200)

  await page.getByRole("button", { name: "Log out" }).click()

  await expect(page).toHaveURL((url) => url.pathname === "/login")
  expect((await page.request.get("/v1/me")).status()).toBe(401)
})

test("logging out of a session that already ended goes to the login all the same", async ({
  page,
}) => {
  await page.goto("/login")
  await logIn(page, E2E_PASSWORD)
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible()
  // Another tab logs out first.
  const { csrf_token: csrfToken } = await (
    await page.request.get("/v1/me")
  ).json()
  const elsewhere = await page.request.post("/v1/auth/logout", {
    headers: { "X-CSRF-Token": csrfToken },
  })
  expect(elsewhere.status()).toBe(204)

  await page.getByRole("button", { name: "Log out" }).click()

  await expect(page).toHaveURL((url) => url.pathname === "/login")
  await expect(page.getByRole("alert")).toHaveCount(0)
})

test("a login returns to the page that asked for it", async ({ page }) => {
  await page.goto("/settings")
  await expect(page).toHaveURL(
    (url) => url.searchParams.get("redirect") === "/settings"
  )

  await logIn(page, E2E_PASSWORD)

  await expect(page).toHaveURL("/settings")
  await expect(
    page.getByRole("heading", { level: 1, name: "Settings" })
  ).toBeVisible()
})

test("a return to another site is ignored", async ({ page }) => {
  await page.goto("/login?redirect=//example.com/")

  await logIn(page, E2E_PASSWORD)

  await expect(page).toHaveURL("/")
})
