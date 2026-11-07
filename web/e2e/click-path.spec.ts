import { expect, test } from "@playwright/test"
import { E2E_PASSWORD } from "./support/password.ts"

// The builder's check of step 4.3 as a clip for the pull request (the UI recipe): log in, open
// each page of the sidebar, and switch to the light theme and back. The settings page's local
// path must stay below the fold of 800 px, out of the clip, since a video cannot be masked (D-80).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

const PAGES = ["Lab", "Strategies", "Runs", "Prop", "Agent", "Data", "Settings"]
const PAUSE_MS = 500

test("the builder's click path, recorded", async ({ page }) => {
  await page.goto("/")
  await page.getByLabel("Password").fill(E2E_PASSWORD)
  await page.getByRole("button", { name: "Log in" }).click()
  const sidebar = page.getByRole("navigation", { name: "Main" })

  for (const name of PAGES) {
    await sidebar.getByRole("link", { name, exact: true }).click()
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible()
    // A clip shows each page for a moment; nothing here waits on the app.
    await page.waitForTimeout(PAUSE_MS)
  }
  for (const theme of ["Light", "Dark"]) {
    await page.getByRole("radio", { name: theme }).click()
    await expect(page.getByRole("radio", { name: theme })).toBeChecked()
    await page.waitForTimeout(PAUSE_MS)
  }
  await expect(page.getByTestId("data-folder")).not.toBeInViewport()
})
