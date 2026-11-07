import { test as base, expect, type Page } from "@playwright/test"
import { E2E_PASSWORD } from "./password.ts"

/** Specs that start logged in: `loggedIn` is the page after a login through the API, whose
 * session cookie the page's browser context keeps. */
export const test = base.extend<{ loggedIn: Page }>({
  loggedIn: async ({ page }, use) => {
    const login = await page.request.post("/v1/auth/login", {
      data: { password: E2E_PASSWORD },
    })
    expect(login.status()).toBe(200)
    await use(page)
  },
})

export { expect }
