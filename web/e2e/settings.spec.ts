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

  await page.getByRole("radio", { name: "Light" }).check()
  await expect(html).not.toHaveClass(/dark/)
  await page.reload()
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked()
  await expect(html).not.toHaveClass(/dark/)
  await screenshot(page, "settings-light", [page.getByTestId("data-folder")])
  await page.goto("/")
  await screenshot(page, "page-home-light")

  await page.goto("/settings")
  await page.getByRole("radio", { name: "Dark" }).check()
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

test.describe("the password", () => {
  let changed = false

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
    await page.getByLabel("Password").fill(E2E_PASSWORD)
    await page.getByRole("button", { name: "Log in" }).click()
    await expect(page.getByRole("alert")).toBeVisible()
    await page.getByLabel("Password").fill(NEW_PASSWORD)
    await page.getByRole("button", { name: "Log in" }).click()
    await expect(page).toHaveURL("/")
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
