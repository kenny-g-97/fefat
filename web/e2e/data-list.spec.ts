import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The Data page's list since the builder's fourth check of step 5.4 (D-97): each row's type, the
// search and the dropdowns over its rows, the sources the rows came from, and the guide's own
// page. The seed holds one provider, `synthetic`, which no source of the guide reads, with every
// row unchecked until data.spec.ts checks MES, so the dropdowns and the sources are drawn from
// the catalog's answer rewritten here to three providers and three qualities. Nothing here
// starts a sync, whichever order Playwright runs the files in.

const SEEDED = ["MES", "BTCUSDT-PERP", "ES"]
/** The provider and the quality each seeded root is given: two presets of one source, a second
 * source, and a quality each. */
const REWRITTEN: ReadonlyMap<
  string,
  Readonly<{ provider: string; quality: string }>
> = new Map([
  ["MES", { provider: "databento", quality: "flagged" }],
  ["BTCUSDT-PERP", { provider: "ninjatrader", quality: "unchecked" }],
  ["ES", { provider: "databento-csv", quality: "clean" }],
])
const stored = z.looseObject({
  id: z.string(),
  provider: z.string(),
  root: z.string(),
  schema_name: z.string(),
  quality: z.string(),
})
const catalogStatus = z.looseObject({
  products: z.array(z.looseObject({ datasets: z.array(stored) })),
  unlisted: z.array(stored),
})

type Stored = z.infer<typeof stored>

/** Answer `GET /v1/catalog` with the seed's datasets as three providers would hold them. */
async function threeProviders(page: Page): Promise<void> {
  const catalog = catalogStatus.parse(
    await (await page.request.get("/v1/catalog")).json()
  )
  const rewritten = (dataset: Stored): Stored => {
    const given = REWRITTEN.get(dataset.root)
    if (given === undefined) {
      throw new Error(`Expected a root of the seed, got ${dataset.root}.`)
    }
    return {
      ...dataset,
      ...given,
      id: `${given.provider}:${dataset.schema_name}:${dataset.root}`,
    }
  }
  await page.route("**/v1/catalog", (route) =>
    route.fulfill({
      json: {
        ...catalog,
        products: catalog.products.map((product) => ({
          ...product,
          datasets: product.datasets.map(rewritten),
        })),
        unlisted: catalog.unlisted.map(rewritten),
      },
    })
  )
}

function list(page: Page): Locator {
  return page.getByRole("region", { name: "Imported data" })
}

function listedRoots(page: Page): Locator {
  return list(page).getByTestId("imported-root")
}

function searchOf(page: Page): Locator {
  return list(page).getByRole("searchbox", { name: "Search" })
}

function dropdown(page: Page, column: string): Locator {
  return list(page).getByLabel(column, { exact: true })
}

function sources(page: Page): Locator {
  return page.getByRole("region", { name: "Sources", exact: true })
}

async function choose(
  page: Page,
  column: string,
  option: string
): Promise<void> {
  await dropdown(page, column).click()
  await page.getByRole("option", { name: option, exact: true }).click()
}

test("each row says its type, and the search keeps the rows that hold every word typed", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.goto("/data")

  await expect(listedRoots(page)).toHaveText(SEEDED)
  // Every dataset the catalog lists is market data: alternative data arrives with Phase 10.
  await expect(list(page).getByTestId("imported-type")).toHaveText(
    SEEDED.map(() => "Market")
  )
  // A word of any cell, capitals ignored: an instrument, what the data holds, a trade date; two
  // words are both asked for, in whichever cells. "es" would keep all three, through "Trades".
  const kept: readonly (readonly [string, readonly string[]])[] = [
    ["btc", ["BTCUSDT-PERP"]],
    ["Mes", ["MES"]],
    ["1-second", ["BTCUSDT-PERP", "ES"]],
    ["2025", ["MES"]],
    ["trades synthetic", ["BTCUSDT-PERP", "ES"]],
    ["", SEEDED],
  ]
  for (const [typed, roots] of kept) {
    await searchOf(page).fill(typed)
    await expect(listedRoots(page), `searching for "${typed}"`).toHaveText(
      roots
    )
  }
  // Escape clears a search field, which the list follows: the field shows no clear button of
  // the browser's own, off the palette in both themes.
  await searchOf(page).fill("btc")
  await searchOf(page).press("Escape")
  await expect(searchOf(page)).toHaveValue("")
  await expect(listedRoots(page)).toHaveText(SEEDED)
  expect(errors).toEqual([])
})

test("each dropdown keeps the rows of its value, and the search and the dropdowns combine", async ({
  loggedIn: page,
}) => {
  await threeProviders(page)
  await page.goto("/data")
  await expect(listedRoots(page)).toHaveText(SEEDED)

  // The five fields stand on one line at the harness's 1280 px.
  const fields = [
    searchOf(page),
    ...["Instrument", "Provider", "Type", "Quality"].map((column) =>
      dropdown(page, column)
    ),
  ]
  const tops = await Promise.all(
    fields.map(async (field) => (await field.boundingBox())?.y)
  )
  expect(tops).not.toContain(undefined)
  expect(new Set(tops).size, "one line of fields").toBe(1)

  // A dropdown offers its column's values as the list holds them, in its order.
  await dropdown(page, "Provider").click()
  await expect(page.getByRole("option")).toHaveText([
    "All",
    "databento",
    "ninjatrader",
    "databento-csv",
  ])
  await page.getByRole("option", { name: "databento", exact: true }).click()
  // The value alone: databento-csv is another provider, as MES is another instrument than ES.
  await expect(listedRoots(page)).toHaveText(["MES"])
  await choose(page, "Provider", "All")
  await choose(page, "Instrument", "ES")
  await expect(listedRoots(page)).toHaveText(["ES"])
  await choose(page, "Instrument", "All")
  await dropdown(page, "Quality").click()
  await expect(page.getByRole("option")).toHaveText([
    "All",
    "Flagged",
    "Unchecked",
    "Clean",
  ])
  await page.getByRole("option", { name: "Clean", exact: true }).click()
  await expect(listedRoots(page)).toHaveText(["ES"])
  await choose(page, "Type", "Market")
  await expect(listedRoots(page)).toHaveText(["ES"])
  await choose(page, "Quality", "All")
  await expect(listedRoots(page)).toHaveText(SEEDED)

  // Together: a word and two values.
  await searchOf(page).fill("bars")
  await choose(page, "Quality", "Flagged")
  await expect(listedRoots(page)).toHaveText(["MES"])
  await choose(page, "Provider", "ninjatrader")
  await expect(listedRoots(page)).toHaveCount(0)
  await choose(page, "Provider", "databento")
  await expect(listedRoots(page)).toHaveText(["MES"])
  // The pointer off the page's rows, onto the top bar's empty part, for the picture.
  await page.mouse.move(700, 36)
  await screenshot(page, "data-catalog-filtered")
})

test("filters that match nothing say so, and Clear filters brings every row back", async ({
  loggedIn: page,
}) => {
  await threeProviders(page)
  await page.goto("/data")
  await choose(page, "Quality", "Clean")
  await searchOf(page).fill("mes")

  await expect(list(page).getByRole("status")).toHaveText(
    "No imported data matches the search and the filters."
  )
  await expect(listedRoots(page)).toHaveCount(0)
  // The columns' headers go with the rows; the fields stay, to change what was asked.
  await expect(list(page).getByTestId("imported-head")).toHaveCount(0)
  await expect(searchOf(page)).toHaveValue("mes")
  await screenshot(page, "data-catalog-no-match")

  await list(page).getByRole("button", { name: "Clear filters" }).click()

  await expect(listedRoots(page)).toHaveText(SEEDED)
  await expect(list(page).getByTestId("imported-head")).toBeVisible()
  await expect(searchOf(page)).toHaveValue("")
  await expect(dropdown(page, "Quality")).toHaveText("All")
  // The button left with its message, so the focus goes to the search rather than nowhere.
  await expect(searchOf(page)).toBeFocused()
})

test("the sources are those the rows came from, each opening the rows held from it", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await threeProviders(page)
  await page.goto("/data")
  const groups = sources(page).getByTestId("imported-source")

  // A source of the guide for each provider its presets name, in the list's order: Databento
  // reads `databento` and `databento-csv`, and no source stands here that holds no row.
  await expect(groups.locator("summary")).toHaveText([
    /^Databento\s*Vendor$/,
    /^NinjaTrader 8\s*Platform$/,
  ])
  await expect(sources(page).getByTestId("source-row")).toHaveCount(0)
  const held = groups.first().getByTestId("imported-row")
  await expect(held.first()).toBeHidden()

  await groups.first().locator("summary").click()

  await expect(held.getByTestId("imported-root")).toHaveText(["MES", "ES"])
  await expect(held.getByTestId("provider-chip")).toHaveText([
    "databento",
    "databento-csv",
  ])
  await expect(held.first()).toHaveAttribute(
    "href",
    "/data/dataset?instrument=MES&provider=databento"
  )
  await expect(held.last()).toHaveAttribute(
    "href",
    "/data/dataset?instrument=ES&provider=databento-csv"
  )
  await expect(groups.last().getByTestId("imported-row")).toBeHidden()
  // A row under the pointer takes the accent alone: an open source is no group of its rows.
  await held.first().hover()
  const colours = await held
    .getByTestId("imported-root")
    .evaluateAll((roots) => roots.map((root) => getComputedStyle(root).color))
  expect(
    colours[0],
    "the row under the pointer in the accent, the other not"
  ).not.toBe(colours[1])
  await page.mouse.move(700, 36)
  await screenshot(page, "data-catalog-sources")
})

test("All sources leads to the guide's own page, a source's terms and its Import a click away", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/data")
  const all = sources(page).getByRole("link", { name: "All sources" })
  await expect(all).toHaveAttribute("href", "/data/sources")

  await all.click()

  await expect(page).toHaveURL("/data/sources")
  await expect(page).toHaveTitle("Sources – FEAT")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sources")
  // The sidebar's Data row is the current page; the way back to it never is.
  await expect(
    page
      .getByRole("navigation", { name: "Main" })
      .getByRole("link", { name: "Data", exact: true })
  ).toHaveAttribute("aria-current", "page")
  await expect(
    page.getByRole("link", { name: "Back to Data" })
  ).not.toHaveAttribute("aria-current")
  const guide = page.getByRole("region", { name: "Source guide" })
  await expect(guide).toContainText(/Researched on \d{4}-\d{2}-\d{2}/)
  await expect(guide.getByTestId("source-row")).toHaveCount(27)
  const databento = guide
    .getByTestId("source-row")
    .filter({ hasText: "Databento" })
    .first()
  await databento.getByText("Databento", { exact: true }).click()
  await expect(
    databento.getByRole("link", { name: "Terms page" })
  ).toHaveAttribute(
    "href",
    "https://databento.com/legal/databento-user-agreement"
  )
  const importWith = databento.getByRole("link", {
    name: "Import with Databento DBN batch download",
  })
  await expect(importWith).toHaveAttribute(
    "href",
    "/data/import?preset=databento"
  )
  await page.mouse.move(700, 36)
  await screenshot(page, "data-sources")

  await importWith.click()

  await expect(page).toHaveURL("/data/import?preset=databento")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Import")
  await expect(page.getByText("Not built yet")).toBeVisible()
  await screenshot(page, "data-import")
  // From the builder's check of step 5.4: no way back to Data but the sidebar's row.
  await page.getByRole("link", { name: "Back to Data" }).click()
  await expect(page).toHaveURL("/data")
  expect(errors).toEqual([])
})
