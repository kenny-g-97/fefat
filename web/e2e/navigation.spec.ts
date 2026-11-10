import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// Done means 2 and 3 of step 4.3: the sidebar's pages, served by `fefat up` from web/dist with
// its index for page paths, the error boundary, and the page for an unknown path.

type SidebarPage = { readonly name: string; readonly path: string }

/** Each link of the home page's panels, with the page it leads to. */
const HOME_LINKS: readonly (readonly [string, string])[] = [
  ["All runs", "/runs"],
  ["All features", "/lab"],
  ["Build a strategy", "/strategies"],
  ["Open the feature lab", "/lab"],
  ["Run a backtest", "/runs"],
  ["Import data", "/data"],
]

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
    await expect(page).toHaveTitle(`${name} – FEAT`)
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible()
    await expect(link).toHaveAttribute("aria-current", "page")
    // The mark leads home too, so it is the current page on Home alone.
    await expect(page.locator('a[aria-current="page"]')).toHaveCount(
      path === "/" ? 2 : 1
    )
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
  // The Phase 4 exit's step review: every link leads to its page, not the one clicked alone.
  for (const [name, href] of HOME_LINKS) {
    await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute(
      "href",
      href
    )
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
  await page.goto("/lab/no-such-page")
  await expect(
    page.getByRole("heading", { level: 1, name: "This page does not exist" })
  ).toBeVisible()
  await expect(page.getByRole("main")).toHaveCount(1)
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0)
  await expect(
    page.getByRole("main").getByRole("img", { name: "FEAT", exact: true })
  ).toBeVisible()
})

test("the sidebar shows the version the server reports", async ({
  loggedIn: page,
}) => {
  const versions = await page.request.get("/v1/version")
  const { fefat_app: version } = await versions.json()

  await page.goto("/")

  await expect(page.getByTestId("version")).toHaveText(`FEAT ${version}`)
})

test("the shell's own failure stands alone under the logo", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/me", (route) =>
    route.fulfill(
      problemAnswer(500, "The server failed on purpose, for this test.")
    )
  )

  await page.goto("/")

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Something broke on this page",
    })
  ).toBeVisible()
  await expect(page.getByRole("main")).toHaveCount(1)
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0)
  await expect(
    page.getByRole("main").getByRole("img", { name: "FEAT", exact: true })
  ).toBeVisible()
})

test("a failure shows what broke and how to go on", async ({
  loggedIn: page,
}) => {
  await page.route("**/v1/api-tokens", (route) =>
    route.fulfill(
      problemAnswer(500, "The server failed on purpose, for this test.")
    )
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
