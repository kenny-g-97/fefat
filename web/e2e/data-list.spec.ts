import type { Locator, Page } from "@playwright/test"
import { z } from "zod"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The Data page's list since the builder's fourth check of step 5.4 (D-97): each row's type, the
// search and the dropdowns over its rows, the sources the rows came from, and the guide's own
// page. The seed holds one provider, `synthetic`, which no source of the guide reads, with every
// row unchecked until data.spec.ts checks MES, so the dropdowns and the sources are drawn from
// the catalog's answer rewritten here to three providers and three qualities, with no job under
// way. Nothing here starts a sync, whichever order Playwright runs the files in.

const SEEDED = ["MES", "BTCUSDT-PERP", "ES"]
const COLUMNS = ["Instrument", "Provider", "Type", "Quality"]
/** The provider and the quality each seeded root is given: two presets of one source, a second
 * source, and a quality each, in another order than the Quality dropdown's own. */
const REWRITTEN: ReadonlyMap<
  string,
  Readonly<{ provider: string; quality: string }>
> = new Map([
  ["MES", { provider: "databento", quality: "clean" }],
  ["BTCUSDT-PERP", { provider: "ninjatrader", quality: "unchecked" }],
  ["ES", { provider: "databento-csv", quality: "flagged" }],
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

/** Answer `GET /v1/catalog` with the seed's datasets as three providers would hold them, and
 * `GET /v1/jobs` with none, so that no check another spec left under way reads Checking here. */
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
  await page.route("**/v1/jobs", (route) => route.fulfill({ json: [] }))
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

/** Whether the focused element looks other than it does at rest: its border, its ring, or its
 * outline, each control compared with itself. */
async function focusShows(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const focused = document.activeElement
    if (!(focused instanceof HTMLElement) || focused === document.body) {
      throw new Error("Expected a field with the focus, got none.")
    }
    const look = (style: CSSStyleDeclaration) =>
      `${style.borderColor} ${style.boxShadow} ${style.outlineStyle}`
    const withFocus = look(getComputedStyle(focused))
    focused.blur()
    const atRest = look(getComputedStyle(focused))
    focused.focus()
    return withFocus !== atRest
  })
}

test("each row says its type, and the search keeps the rows that hold every word typed", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  // A focus ring leaves at once, so that the field's two pictures below are of a field at rest.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/data")

  await expect(listedRoots(page)).toHaveText(SEEDED)
  // Every dataset the catalog lists is market data: alternative data arrives with Phase 10.
  await expect(list(page).getByTestId("imported-type")).toHaveText(
    SEEDED.map(() => "Market")
  )
  // A word of any cell, capitals ignored: an instrument, what the data holds, a trade date; two
  // words are both asked for, in whichever cells, and a comma parts them as a space does, so
  // the Data cell typed as it reads is found. "es" would keep all three, through "Trades".
  const kept: readonly (readonly [string, readonly string[]])[] = [
    ["btc", ["BTCUSDT-PERP"]],
    ["Mes", ["MES"]],
    ["1-second", ["BTCUSDT-PERP", "ES"]],
    ["2025", ["MES"]],
    ["trades synthetic", ["BTCUSDT-PERP", "ES"]],
    ["1-second bars, Trades", ["BTCUSDT-PERP", "ES"]],
    ["", SEEDED],
  ]
  for (const [typed, roots] of kept) {
    await searchOf(page).fill(typed)
    await expect(listedRoots(page), `searching for "${typed}"`).toHaveText(
      roots
    )
  }
  // Escape clears the search, and the list follows.
  await searchOf(page).fill("btc")
  await searchOf(page).press("Escape")
  await expect(searchOf(page)).toHaveValue("")
  await expect(listedRoots(page)).toHaveText(SEEDED)
  // The clearing is FEAT's own, for the browsers whose search fields have none (step 5.4's
  // reviews of the fourth check): a key the page is sent, which no browser acts on, clears too.
  await searchOf(page).fill("btc")
  await expect(listedRoots(page)).toHaveText(["BTCUSDT-PERP"])
  await searchOf(page).dispatchEvent("keydown", { key: "Escape" })
  await expect(searchOf(page)).toHaveValue("")
  await expect(listedRoots(page)).toHaveText(SEEDED)
  // While an input method composes a word, Escape is the method's, to drop what it offers: the
  // search keeps what was typed.
  await searchOf(page).fill("btc")
  await searchOf(page).dispatchEvent("keydown", {
    key: "Escape",
    isComposing: true,
  })
  await expect(searchOf(page)).toHaveValue("btc")
  // The field shows no clear button of the browser's own, white on the dark theme and blue on
  // the light one, no colour of the palette. Chrome draws its own at the end of a search field
  // that holds text while the pointer is on it, so the field's end is pictured under the
  // pointer empty, then holding text, and the two pictures are one: both under the pointer, so
  // that a hover style the field may gain is in both.
  const field = await searchOf(page).boundingBox()
  if (field === null) {
    throw new Error("Expected the search field on the page, got none.")
  }
  const end = {
    x: field.x + field.width - 40,
    y: field.y + 2,
    width: 36,
    height: field.height - 4,
  }
  const ends: Buffer[] = []
  for (const typed of ["", "btc"]) {
    await searchOf(page).fill(typed)
    await searchOf(page).blur()
    await searchOf(page).hover()
    ends.push(await page.screenshot({ clip: end }))
  }
  expect(
    ends[1].equals(ends[0]),
    "the field's end the same with text as without: no clear button of the browser's"
  ).toBe(true)
  expect(errors).toEqual([])
})

test("each dropdown keeps the rows of its value, and the search and the dropdowns combine", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await threeProviders(page)
  // A window 1280 px wide leaves about 1265 px beside the scrollbar a long page brings, which
  // the harness's browser never draws: the five fields stand on one line there too.
  await page.setViewportSize({ width: 1265, height: 800 })
  await page.goto("/data")
  await expect(listedRoots(page)).toHaveText(SEEDED)
  const fields = [
    searchOf(page),
    ...COLUMNS.map((column) => dropdown(page, column)),
  ]
  const tops = await Promise.all(
    fields.map(async (field) => (await field.boundingBox())?.y)
  )
  expect(tops).not.toContain(undefined)
  expect(new Set(tops).size, "one line of fields beside a scrollbar").toBe(1)
  await page.setViewportSize({ width: 1280, height: 800 })
  // Each field shows the keyboard's focus, reached by Tab in the columns' order.
  await searchOf(page).focus()
  for (const field of fields) {
    await expect(field).toBeFocused()
    expect(await focusShows(page), "a focused field's ring").toBe(true)
    await page.keyboard.press("Tab")
  }

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
  // Quality's few values keep one order, whatever the rows': here they read Clean, Unchecked,
  // then Flagged down the list.
  await dropdown(page, "Quality").click()
  await expect(page.getByRole("option")).toHaveText([
    "All",
    "Flagged",
    "Unchecked",
    "Clean",
  ])
  await page.getByRole("option", { name: "Clean", exact: true }).click()
  await expect(listedRoots(page)).toHaveText(["MES"])
  await choose(page, "Type", "Market")
  await expect(listedRoots(page)).toHaveText(["MES"])
  await choose(page, "Quality", "All")
  await expect(listedRoots(page)).toHaveText(SEEDED)

  // A dropdown shows its value whole: the longest provider FEAT's presets name, 13 characters,
  // and the seed's longest root, 12, which the chart's narrower select would cut.
  await choose(page, "Provider", "databento-csv")
  await choose(page, "Instrument", "BTCUSDT-PERP")
  for (const column of ["Provider", "Instrument"]) {
    const cut = await dropdown(page, column)
      .locator('[data-slot="select-value"]')
      .evaluate((value) => value.scrollWidth - value.clientWidth)
    expect(cut, `${column}'s value shown whole`).toBeLessThanOrEqual(0)
  }
  await choose(page, "Instrument", "All")
  await choose(page, "Provider", "All")

  // Together: a word and two values.
  await searchOf(page).fill("bars")
  await choose(page, "Quality", "Flagged")
  await expect(listedRoots(page)).toHaveText(["ES"])
  await choose(page, "Provider", "ninjatrader")
  await expect(listedRoots(page)).toHaveCount(0)
  await choose(page, "Provider", "databento-csv")
  await expect(listedRoots(page)).toHaveText(["ES"])
  // The pointer off the page's rows, onto the top bar's empty part, for the picture.
  await page.mouse.move(700, 36)
  await screenshot(page, "data-catalog-filtered")
})

test("filters that match nothing say so, and Clear filters brings every row back", async ({
  loggedIn: page,
}) => {
  await threeProviders(page)
  await page.goto("/data")
  // The message's place is there from the start, empty, so that a screen reader hears the
  // message arrive in it.
  await expect(list(page).getByRole("status")).toHaveText("")
  await choose(page, "Quality", "Clean")
  await searchOf(page).fill("btc")

  await expect(list(page).getByRole("status")).toHaveText(
    "No imported data matches the filters."
  )
  await expect(listedRoots(page)).toHaveCount(0)
  // The columns' headers go with the rows; the fields stay, to change what was asked.
  await expect(list(page).getByTestId("imported-head")).toHaveCount(0)
  await expect(searchOf(page)).toHaveValue("btc")
  await screenshot(page, "data-catalog-no-match")

  await list(page).getByRole("button", { name: "Clear filters" }).click()

  await expect(listedRoots(page)).toHaveText(SEEDED)
  await expect(list(page).getByTestId("imported-head")).toBeVisible()
  await expect(list(page).getByRole("status")).toHaveText("")
  await expect(searchOf(page)).toHaveValue("")
  await expect(dropdown(page, "Quality")).toHaveText("All")
  // The button left with its message, so the focus goes to the search rather than nowhere.
  await expect(searchOf(page)).toBeFocused()
})

test("two clicks on Clear filters clear, and open no row", async ({
  loggedIn: page,
}) => {
  // Step 5.4's design review of the fourth check: the button stood where the first row comes
  // back, so the second click of a double click opened that row's page. It stands beside its
  // message, where the rows' header, which answers no click, comes back; in a card too narrow
  // for the two on one line the message wraps, never the button under it.
  await threeProviders(page)
  for (const width of [1280, 760]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto("/data")
    await searchOf(page).fill("no such word")
    await expect(listedRoots(page)).toHaveCount(0)

    await list(page).getByRole("button", { name: "Clear filters" }).dblclick()

    await expect(listedRoots(page)).toHaveText(SEEDED)
    await expect(page, `at ${width} px`).toHaveURL("/data")
  }
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
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "data-catalog-sources-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // A source's row leads where the list's does.
  await held.first().click()
  await expect(page).toHaveURL(
    "/data/dataset?instrument=MES&provider=databento"
  )
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "MES from databento"
  )
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
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "data-sources-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

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
