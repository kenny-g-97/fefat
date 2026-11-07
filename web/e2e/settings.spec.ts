import { expect, test } from "./support/fixtures.ts"
import { E2E_PASSWORD } from "./support/password.ts"
import { screenshot } from "./support/screenshots.ts"

// The settings page of step 4.3: the theme, kept by the server; the API tokens; the password;
// and the data folder, read-only. The password test changes it back after itself, so that the
// next spec can log in.

const NEW_PASSWORD = "chalk on slate"

test("the light theme stays chosen across a reload, and dark comes back", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")
  const html = page.locator("html")
  const saved = () =>
    page.waitForResponse(
      (response) =>
        response.url().endsWith("/v1/settings") &&
        response.request().method() === "PUT"
    )

  const light = saved()
  await page.getByRole("radio", { name: "Light" }).click()
  expect((await light).status()).toBe(200)
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked()
  await expect(html).not.toHaveClass(/dark/)
  await page.reload()
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked()
  await expect(html).not.toHaveClass(/dark/)
  // The theme painted on load moves nothing: the design brief counts that as motion.
  expect(await page.evaluate(() => document.getAnimations().length)).toBe(0)
  await screenshot(page, "settings-light", [page.getByTestId("data-folder")])
  await page.goto("/")
  await expect(
    page.getByRole("heading", { level: 1, name: "Home" })
  ).toBeVisible()
  await screenshot(page, "page-home-light")

  await page.goto("/settings")
  const dark = saved()
  await page.getByRole("radio", { name: "Dark" }).click()
  expect((await dark).status()).toBe(200)
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked()
  await expect(html).toHaveClass(/dark/)
})

test("a token is shown once, listed by its name, and revoked", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")

  await page.getByLabel("Token name").fill("e2e-notebook")
  await page.getByRole("button", { name: "Create token" }).click()

  const shown = page.getByTestId("new-token")
  await expect(shown).toContainText("fefat_")
  const row = page.getByRole("row", { name: /e2e-notebook/ })
  await expect(row).toBeVisible()
  await screenshot(page, "settings-token-created", [
    shown,
    page.getByTestId("data-folder"),
  ])
  await row.getByRole("button", { name: "Revoke" }).click()
  await row.getByRole("button", { name: "Revoke now" }).click()
  await expect(row).toBeHidden()
  await page.reload()
  await expect(page.getByTestId("new-token")).toBeHidden()
})

test("a double click on Revoke keeps the token", async ({ loggedIn: page }) => {
  await page.goto("/settings")
  await page.getByLabel("Token name").fill("e2e-double-click")
  await page.getByRole("button", { name: "Create token" }).click()
  const row = page.getByRole("row", { name: /e2e-double-click/ })

  const revoke = row.getByRole("button", { name: "Revoke", exact: true })
  await revoke.dblclick()

  // The second click lands on Keep, which took the trigger's place.
  await page.waitForLoadState("networkidle")
  await expect(revoke).toBeVisible()
  await revoke.click()
  await expect(row.getByRole("button", { name: "Keep" })).toBeFocused()
  await row.getByRole("button", { name: "Revoke now" }).click()
  await expect(row).toBeHidden()
})

test("a revocation the server refuses leaves the row's real state", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")
  await page.getByLabel("Token name").fill("e2e-revoked-elsewhere")
  await page.getByRole("button", { name: "Create token" }).click()
  const row = page.getByRole("row", { name: /e2e-revoked-elsewhere/ })
  await expect(row).toBeVisible()
  const { csrf_token: csrfToken } = await (
    await page.request.get("/v1/me")
  ).json()
  const elsewhere = await page.request.delete(
    "/v1/api-tokens/e2e-revoked-elsewhere",
    {
      headers: { "X-CSRF-Token": csrfToken },
    }
  )
  expect(elsewhere.status()).toBe(204)

  await row.getByRole("button", { name: "Revoke" }).click()
  await row.getByRole("button", { name: "Revoke now" }).click()

  await expect(row).toBeHidden()
})

test.describe("the password", () => {
  let changed = false

  test.beforeEach(() => {
    changed = false
  })

  test.afterEach(async ({ request }) => {
    if (!changed) {
      return
    }
    const login = await request.post("/v1/auth/login", {
      data: { password: NEW_PASSWORD },
    })
    const { csrf_token: csrfToken } = await login.json()
    const back = await request.post("/v1/auth/password", {
      data: { current_password: NEW_PASSWORD, new_password: E2E_PASSWORD },
      headers: { "X-CSRF-Token": csrfToken },
    })
    expect(back.status()).toBe(200)
  })

  test("changes with the current one, and the old one stops working", async ({
    loggedIn: page,
  }) => {
    await page.goto("/settings")

    await page.getByLabel("Current password").fill(E2E_PASSWORD)
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD)
    await page.getByLabel("New password again").fill(NEW_PASSWORD)
    await page.getByRole("button", { name: "Change password" }).click()
    changed = true

    await expect(page.getByText("Password changed")).toBeVisible()
    await expect(
      page.getByRole("heading", { level: 1, name: "Settings" })
    ).toBeVisible()
    await page.getByRole("button", { name: "Log out" }).click()
    await expect(page).toHaveURL((url) => url.pathname === "/login")
    await page.getByLabel("Password").fill(E2E_PASSWORD)
    await page.getByRole("button", { name: "Log in" }).click()
    await expect(page.getByRole("alert")).toBeVisible()
    await page.getByLabel("Password").fill(NEW_PASSWORD)
    await page.getByRole("button", { name: "Log in" }).click()
    await expect(page).toHaveURL("/")
  })

  test("changed in one tab, leaves the other tab working", async ({
    loggedIn: page,
  }) => {
    const other = await page.context().newPage()
    await other.goto("/settings")
    await expect(
      other.getByRole("heading", { level: 1, name: "Settings" })
    ).toBeVisible()
    await page.goto("/settings")

    await page.getByLabel("Current password").fill(E2E_PASSWORD)
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD)
    await page.getByLabel("New password again").fill(NEW_PASSWORD)
    await page.getByRole("button", { name: "Change password" }).click()
    changed = true
    await expect(page.getByText("Password changed")).toBeVisible()

    await other.getByLabel("Token name").fill("e2e-other-tab")
    await other.getByRole("button", { name: "Create token" }).click()
    await expect(other.getByTestId("new-token")).toContainText("fefat_")
    const row = other.getByRole("row", { name: /e2e-other-tab/ })
    await row.getByRole("button", { name: "Revoke" }).click()
    await row.getByRole("button", { name: "Revoke now" }).click()
    await expect(row).toBeHidden()
  })

  test("refuses a wrong current one under its field, which takes the focus", async ({
    loggedIn: page,
  }) => {
    await page.goto("/settings")

    await page.getByLabel("Current password").fill("not the password")
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD)
    await page.getByLabel("New password again").fill(NEW_PASSWORD)
    await page.getByRole("button", { name: "Change password" }).click()

    await expect(
      page.getByText("That is not the current password. Type it again.")
    ).toBeVisible()
    await expect(page.getByLabel("Current password")).toBeFocused()
  })

  test("refuses a new password typed twice differently", async ({
    loggedIn: page,
  }) => {
    await page.goto("/settings")

    await page.getByLabel("Current password").fill(E2E_PASSWORD)
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD)
    await page.getByLabel("New password again").fill("something else")
    await page.getByRole("button", { name: "Change password" }).click()

    await expect(
      page.getByText("Type the same new password twice")
    ).toBeVisible()
  })
})

test("the data folder is shown and cannot be edited", async ({
  loggedIn: page,
}) => {
  await page.goto("/settings")

  const folder = page.getByTestId("data-folder")
  await expect(folder).toContainText("fefat-e2e")
  await expect(page.getByRole("textbox", { name: "Data folder" })).toHaveCount(
    0
  )
})
