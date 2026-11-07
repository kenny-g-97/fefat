import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// Done means 2 and 3 of step 4.3: the sidebar's pages, served by `fefat up` from web/dist with
// its index for page paths, the error boundary, and the page for an unknown path.

type SidebarPage = { readonly name: string; readonly path: string }

const PAGES: readonly SidebarPage[] = [
  { name: "Home", path: "/" },
  { name: "Lab", path: "/lab" },
  { name: "Strategies", path: "/strategies" },
  { name: "Runs", path: "/runs" },
  { name: "Prop", path: "/prop" },
  { name: "Agent", path: "/agent" },
  { name: "Data", path: "/data" },
  { name: "Settings", path: "/settings" },
]

test("each page of the sidebar opens with its title and its row marked", async ({
  loggedIn: page,
}) => {
  await page.goto("/")
  const sidebar = page.getByRole("navigation", { name: "Main" })

  for (const { name, path } of PAGES) {
    const link = sidebar.getByRole("link", { name, exact: true })
    await link.click()

    await expect(page).toHaveURL(path)
    await expect(page).toHaveTitle(`${name} – FEFAT`)
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible()
    await expect(link).toHaveAttribute("aria-current", "page")
    await screenshot(page, `page-${name.toLowerCase()}`, [
      page.getByTestId("data-folder"),
    ])
  }
})

test("the home page links each widget to its page", async ({
  loggedIn: page,
}) => {
  await page.goto("/")

  for (const widget of [
    "Recent runs",
    "Running jobs",
    "Feature library",
    "Start",
  ]) {
    await expect(
      page.getByRole("heading", { level: 2, name: widget })
    ).toBeVisible()
  }
  await page.getByRole("link", { name: "Open the feature lab" }).click()
  await expect(page).toHaveURL("/lab")
})

test("a reload keeps the page, which the server answers with the app", async ({
  loggedIn: page,
}) => {
  await page.goto("/runs")
  await page.reload()

  await expect(
    page.getByRole("heading", { level: 1, name: "Runs" })
  ).toBeVisible()
})

test("an unknown page says so and leads home", async ({ loggedIn: page }) => {
  await page.goto("/no-such-page")

  await expect(
    page.getByRole("heading", { level: 1, name: "This page does not exist" })
  ).toBeVisible()
  await screenshot(page, "not-found")
  await page.getByRole("link", { name: "Go to the home page" }).click()
  await expect(page).toHaveURL("/")
})

test("a failure shows what broke and how to go on", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/api-tokens", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/problem+json",
      body: JSON.stringify({
        type: "about:blank",
        title: "Internal Server Error",
        status: 500,
        detail: "The server failed on purpose, for this test.",
        instance: "/v1/api-tokens",
        request_id: "e2e",
      }),
    })
  )

  await page.goto("/settings")

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Something broke on this page",
    })
  ).toBeVisible()
  await expect(
    page.getByText("The server failed on purpose, for this test.")
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible()
  await screenshot(page, "error")
})
